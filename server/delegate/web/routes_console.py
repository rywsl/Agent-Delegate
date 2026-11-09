"""Session JSON API for the console SPA.

The HTML site remains the source of the same operations. These routes expose that
behavior as JSON so the frontend can sign in with the session cookie and render
tasks, keys, providers and the audit trail without scraping templates.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote, urlsplit

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import audit
from ..config import get_settings
from ..models import ApiKey, AuditLog, ProviderConfig, Task, TaskEvent, TaskStatus, User, utcnow
from ..providers import SUPPORTED_PROVIDERS
from ..security import encrypt, generate_api_key, hash_password, verify_password
from ..tasks import (
    TaskInput,
    TaskInputError,
    create_task,
    get_user_task,
    raw_log_path,
    request_cancel,
    resolve_options,
    task_dir,
)
from .deps import csrf_token, current_user, get_db, login_session, require_admin, require_user, verify_csrf

router = APIRouter(prefix="/api/console")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PATCH_INLINE_LIMIT = 512 * 1024

PROVIDER_META = {
    "anthropic": {"name": "Anthropic", "python_package": "anthropic", "env_key": "ANTHROPIC_API_KEY", "env_base_url": "ANTHROPIC_BASE_URL"},
    "openai": {"name": "OpenAI", "python_package": "openai", "env_key": "OPENAI_API_KEY", "env_base_url": "OPENAI_BASE_URL"},
    "gemini": {"name": "Gemini", "python_package": "google-genai", "env_key": "GEMINI_API_KEY", "env_base_url": "GEMINI_BASE_URL"},
}


class AuthIn(BaseModel):
    email: str
    password: str
    display_name: str = ""


class SettingsIn(BaseModel):
    agent: str | None = None
    model: str | None = None
    sandbox: str | None = None
    harness: str | None = None
    timeout_min: int | None = None
    display_name: str | None = None


class TaskIn(BaseModel):
    task: str = Field(..., max_length=100_000)
    title: str | None = None
    repo_url: str | None = None
    repo_ref: str | None = None
    agent: str | None = None
    model: str | None = None
    sandbox: str | None = None
    harness: str | None = None
    timeout_min: int | None = None


class KeyIn(BaseModel):
    name: str = "default"


class ProviderIn(BaseModel):
    base_url: str = ""
    api_key: str = ""
    clear_api_key: bool = False
    enabled: bool | None = None


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _user_view(user: User) -> dict[str, Any]:
    name = user.display_name or user.email.split("@")[0]
    initials = "".join(part[:1] for part in re.split(r"[\s._-]+", name) if part)[:2].upper() or "U"
    return {
        "id": user.id,
        "email": user.email,
        "display_name": name,
        "is_admin": user.is_admin,
        "initials": initials,
    }


def _envelope(request: Request, **payload: Any) -> dict[str, Any]:
    payload["csrf"] = csrf_token(request)
    return payload


def _options_view(user: User) -> dict[str, Any]:
    s = get_settings()
    current = resolve_options(user)
    return {
        "current": current,
        "agents": s.agents,
        "sandboxes": s.sandboxes,
        "harnesses": s.harnesses,
        "models": {agent: s.models_for(agent) for agent in s.agents},
        "max_timeout_s": s.max_timeout_s,
        "allow_registration": s.allow_registration,
        "mcp_url": s.mcp_public_url,
        "public_url": s.public_url,
        "sandbox": {
            "memory": s.sandbox_memory,
            "cpus": s.sandbox_cpus,
            "pids": s.sandbox_pids,
            "network": s.sandbox_network,
            "capacity": s.sandbox_max_concurrent,
            "uid": 10001,
            "image": s.sandbox_image,
        },
    }


def _apply_settings(user: User, body: SettingsIn) -> dict[str, Any]:
    s = get_settings()
    agent = body.agent or user.pref_agent or s.default_agent
    if agent not in s.agents:
        raise HTTPException(422, "不支持的模型提供商")
    sandbox = body.sandbox or user.pref_sandbox or s.default_sandbox
    harness = body.harness or user.pref_harness or s.default_harness
    if sandbox not in s.sandboxes or harness not in s.harnesses:
        raise HTTPException(422, "不支持的沙箱或执行器")
    models = s.models_for(agent)
    model = body.model or (user.pref_model if agent == (user.pref_agent or s.default_agent) else None) or (models[0] if models else "")
    if model not in models:
        raise HTTPException(422, "当前提供商没有这个模型")
    if body.timeout_min is None:
        timeout = user.pref_timeout_s or s.default_timeout_s
    else:
        timeout = max(60, min(body.timeout_min * 60, s.max_timeout_s))
    before = {
        "agent": user.pref_agent, "model": user.pref_model, "sandbox": user.pref_sandbox,
        "harness": user.pref_harness, "timeout": user.pref_timeout_s,
    }
    user.pref_agent = agent
    user.pref_model = model
    user.pref_sandbox = sandbox
    user.pref_harness = harness
    user.pref_timeout_s = int(timeout)
    if body.display_name and body.display_name.strip():
        user.display_name = body.display_name.strip()[:100]
    return before


def _task_summary(task: Task) -> dict[str, Any]:
    return {
        "id": task.id,
        "title": task.title,
        "prompt": task.prompt,
        "source": task.source,
        "status": task.status,
        "status_reason": task.status_reason,
        "client_info": task.client_info or {},
        "agent": task.agent,
        "model": task.model,
        "sandbox": task.sandbox,
        "harness": task.harness,
        "timeout_s": task.timeout_s,
        "max_turns": task.max_turns,
        "created_at": _iso(task.created_at),
        "started_at": _iso(task.started_at),
        "finished_at": _iso(task.finished_at),
        "duration_s": round(task.duration_s, 1) if task.duration_s is not None else None,
        "repo_url": task.repo_url,
        "repo_ref": task.repo_ref,
        "container_id": task.container_id,
        "container_name": task.container_name,
        "sandbox_image": task.sandbox_image,
        "sandbox_limits": task.sandbox_limits or {},
        "exit_code": task.exit_code,
        "result_text": task.result_text,
        "patch_stats": task.patch_stats or {},
        "outputs": task.outputs or [],
        "agent_usage": task.agent_usage or {},
        "event_count": task.event_count,
        "cancel_requested": task.cancel_requested,
    }


def _event_view(event: TaskEvent) -> dict[str, Any]:
    data = event.data or {}
    tool_name = data.get("name") or data.get("tool") or data.get("tool_name")
    tool_args = data.get("input")
    if tool_args is None and isinstance(data.get("command"), str):
        tool_args = {"command": data["command"]}
    tool_result = data.get("content") if event.kind == "tool_result" and isinstance(data.get("content"), str) else None
    kind = "runner" if event.kind == "phase" else event.kind
    return {
        "id": f"ev-{event.id}",
        "seq": event.seq,
        "ts": _iso(event.ts),
        "kind": kind,
        "phase": data.get("phase"),
        "summary": event.summary,
        "tool_name": tool_name,
        "tool_args": tool_args if isinstance(tool_args, (dict, str)) else None,
        "tool_result": tool_result,
        "data": data,
    }


def _owned(db: Session, user: User, task_id: str) -> Task:
    task = get_user_task(db, user, task_id)
    if task is None:
        raise HTTPException(404, "任务不存在")
    return task


def _task_detail(db: Session, user: User, task: Task, *, events_after: int = 0) -> dict[str, Any]:
    view = _task_summary(task)
    patch_file = task_dir(task.id) / "changes.patch"
    patch_exists = patch_file.exists() and patch_file.stat().st_size > 0
    view["patch_exists"] = patch_exists
    view["raw_patch"] = None
    if patch_exists and patch_file.stat().st_size <= PATCH_INLINE_LIMIT:
        view["raw_patch"] = patch_file.read_bytes().decode("utf-8", errors="replace")
    view["raw_log_exists"] = raw_log_path(task.id).exists()
    api_key = db.get(ApiKey, task.api_key_id) if task.api_key_id else None
    view["api_key_prefix"] = api_key.prefix if api_key else None
    view["api_key_name"] = api_key.name if api_key else None
    view["artifacts"] = {
        "patch": f"/tasks/{task.id}/artifacts/patch" if patch_exists else None,
        "outputs": f"/tasks/{task.id}/artifacts/outputs" if task.outputs else None,
        "log": f"/tasks/{task.id}/artifacts/log" if view["raw_log_exists"] else None,
    }
    view["outputs"] = [
        {
            "path": item.get("path"),
            "size": item.get("size", 0),
            "sha256": item.get("sha256"),
            "download_url": f"/tasks/{task.id}/artifacts/output?path={quote(item.get('path') or '')}",
        }
        for item in (task.outputs or [])
    ]
    rows = db.scalars(select(TaskEvent).where(
        TaskEvent.task_id == task.id, TaskEvent.seq > events_after
    ).order_by(TaskEvent.seq).limit(2000)).all()
    view["events"] = [_event_view(row) for row in rows]
    view["can_cancel"] = task.status in TaskStatus.ACTIVE
    view["owner_is_self"] = task.user_id == user.id
    return view


def _provider_rows(db: Session) -> list[dict[str, Any]]:
    settings = get_settings()
    rows = []
    for name in SUPPORTED_PROVIDERS:
        meta = PROVIDER_META[name]
        config = db.get(ProviderConfig, name)
        from_admin = bool(config and config.api_key_enc)
        from_env = bool(settings.provider_api_key(name))
        configured = from_admin or from_env
        if from_admin:
            source = "后台"
        elif from_env:
            source = "环境变量"
        else:
            source = "未配置"
        base_url = ((config.base_url if config else "") or settings.provider_base_url(name) or "")
        rows.append({
            "id": name,
            "name": meta["name"],
            "python_package": meta["python_package"],
            "env_key": meta["env_key"],
            "env_base_url": meta["env_base_url"],
            "configured": configured,
            "enabled": True if config is None else config.enabled,
            "key_source": source,
            "api_key_masked": "已配置" if configured else "",
            "base_url": base_url,
            "models": settings.models_for(name),
            "default_model": (settings.models_for(name) or [""])[0],
        })
    return rows


def _level(lines: int) -> int:
    if lines <= 0:
        return 0
    if lines < 20:
        return 1
    if lines < 80:
        return 2
    if lines < 200:
        return 3
    return 4


def _local_day(value: datetime) -> datetime.date:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone().date()


def _heatmap(tasks: list[Task]) -> dict[str, Any]:
    today = datetime.now().astimezone().date()
    start = today - timedelta(days=52 * 7 - 1)
    buckets: dict[Any, int] = {}
    month_totals: dict[str, int] = {}
    patch_lines = 0
    for task in tasks:
        stats = task.patch_stats or {}
        lines = int(stats.get("insertions") or 0) + int(stats.get("deletions") or 0)
        patch_lines += lines
        if not task.created_at:
            continue
        day = _local_day(task.created_at)
        if start <= day <= today:
            buckets[day] = buckets.get(day, 0) + lines
            key = day.strftime("%Y-%m")
            month_totals[key] = month_totals.get(key, 0) + lines
    cells: list[int] = []
    months: list[str] = []
    seen_month = ""
    peak_day = None
    peak_lines = -1
    day = start
    while day <= today:
        lines = buckets.get(day, 0)
        cells.append(_level(lines))
        if lines > peak_lines:
            peak_lines = lines
            peak_day = day
        label = day.strftime("%b")
        month_key = day.strftime("%Y-%m")
        if month_key != seen_month:
            months.append(label)
            seen_month = month_key
        day += timedelta(days=1)
    active_month = "-"
    if month_totals:
        best = max(month_totals, key=month_totals.get)
        active_month = datetime.strptime(best, "%Y-%m").strftime("%B")
    return {
        "cells": cells,
        "months": months,
        "patch_lines": patch_lines,
        "active_month": active_month if patch_lines else "-",
        "peak_date": peak_day.strftime("%b %d, %Y") if peak_day and peak_lines > 0 else "-",
    }


@router.get("/session")
def session(request: Request, user: User | None = Depends(current_user)) -> dict[str, Any]:
    return _envelope(
        request,
        user=_user_view(user) if user else None,
        options=_options_view(user) if user else {
            "allow_registration": get_settings().allow_registration,
            "mcp_url": get_settings().mcp_public_url,
            "public_url": get_settings().public_url,
        },
    )


@router.post("/login", dependencies=[Depends(verify_csrf)])
def login(request: Request, body: AuthIn, db: Session = Depends(get_db)):
    email = body.email.strip().lower()
    user = db.scalar(select(User).where(func.lower(User.email) == email))
    if user is None or not verify_password(body.password, user.password_hash):
        audit.record(db, "auth.login_failed", actor="anonymous", user_id=user.id if user else None,
                     request=request, email=email[:200])
        return JSONResponse({"detail": "邮箱或密码错误"}, status_code=401)
    if not user.is_active:
        return JSONResponse({"detail": "账户已被停用"}, status_code=403)
    user.last_login_at = utcnow()
    login_session(request, user)
    audit.record(db, "auth.login", actor=f"user:{user.id}", user_id=user.id, request=request)
    return _envelope(request, user=_user_view(user), options=_options_view(user))


@router.post("/register", dependencies=[Depends(verify_csrf)])
def register(request: Request, body: AuthIn, db: Session = Depends(get_db)):
    if not get_settings().allow_registration:
        raise HTTPException(403, "当前未开放注册")
    email = body.email.strip().lower()
    if not EMAIL_RE.match(email):
        raise HTTPException(400, "邮箱格式不正确")
    if len(body.password) < 8:
        raise HTTPException(400, "密码至少 8 位")
    if db.scalar(select(User).where(func.lower(User.email) == email)):
        raise HTTPException(400, "该邮箱已注册")
    first_user = db.scalar(select(func.count()).select_from(User)) == 0
    user = User(
        email=email,
        display_name=body.display_name.strip()[:100] or email.split("@")[0],
        password_hash=hash_password(body.password),
        is_admin=first_user,
    )
    db.add(user)
    db.flush()
    audit.record(db, "auth.register", actor=f"user:{user.id}", user_id=user.id, request=request, admin=first_user)
    login_session(request, user)
    return _envelope(request, user=_user_view(user), options=_options_view(user),
                     message="注册成功" + ("，你是第一个用户，已获得管理员权限" if first_user else ""))


@router.post("/logout", dependencies=[Depends(verify_csrf)])
def logout(request: Request, user: User | None = Depends(current_user), db: Session = Depends(get_db)):
    if user:
        audit.record(db, "auth.logout", actor=f"user:{user.id}", user_id=user.id, request=request)
    request.session.clear()
    request.session["csrf"] = csrf_token(request)
    return _envelope(request, user=None)


@router.get("/dashboard")
def dashboard(request: Request, user: User = Depends(require_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    tasks = db.scalars(select(Task).where(Task.user_id == user.id).order_by(Task.created_at.desc())).all()
    counts: dict[str, int] = {}
    tokens = {"input_tokens": 0, "output_tokens": 0, "cache_read_tokens": 0, "cache_write_tokens": 0}
    for task in tasks:
        counts[task.status] = counts.get(task.status, 0) + 1
        usage = task.agent_usage or {}
        for key in tokens:
            tokens[key] += int(usage.get(key) or 0)
    prompt_plus_cache = tokens["input_tokens"] + tokens["cache_read_tokens"]
    active = sum(counts.get(status, 0) for status in TaskStatus.ACTIVE)
    s = get_settings()
    has_key = db.scalar(select(func.count()).select_from(ApiKey).where(
        ApiKey.user_id == user.id, ApiKey.revoked_at.is_(None)
    ))
    return _envelope(
        request,
        counts=counts,
        active=active,
        total=len(tasks),
        recent=[_task_summary(task) for task in tasks[:8]],
        usage={
            **tokens,
            "tokens": sum(tokens.values()),
            "cache_rate": round(tokens["cache_read_tokens"] / prompt_plus_cache * 100, 1) if prompt_plus_cache else 0,
        },
        heatmap=_heatmap(tasks),
        sandbox={
            "memory": s.sandbox_memory,
            "cpus": s.sandbox_cpus,
            "capacity": max(1, s.sandbox_max_concurrent),
            "active": active,
            "uid": 10001,
        },
        has_key=bool(has_key),
        options=_options_view(user),
    )


@router.get("/tasks")
def list_tasks(
    request: Request, status: str = "", limit: int = Query(100, ge=1, le=200),
    user: User = Depends(require_user), db: Session = Depends(get_db),
) -> dict[str, Any]:
    query = select(Task).where(Task.user_id == user.id)
    if status:
        query = query.where(Task.status == status)
    rows = db.scalars(query.order_by(Task.created_at.desc()).limit(limit)).all()
    return _envelope(request, tasks=[_task_summary(task) for task in rows])


@router.post("/tasks", status_code=201, dependencies=[Depends(verify_csrf)])
def submit_task(request: Request, body: TaskIn, user: User = Depends(require_user), db: Session = Depends(get_db)):
    prefs = SettingsIn(agent=body.agent, model=body.model, sandbox=body.sandbox, harness=body.harness, timeout_min=body.timeout_min)
    if any(value is not None for value in (body.agent, body.model, body.sandbox, body.harness, body.timeout_min)):
        before = _apply_settings(user, prefs)
        audit.record(
            db, "settings.update", actor=f"user:{user.id}", user_id=user.id, request=request,
            before=before,
            after={"agent": user.pref_agent, "model": user.pref_model, "sandbox": user.pref_sandbox,
                   "harness": user.pref_harness, "timeout": user.pref_timeout_s},
        )
    try:
        task = create_task(
            db, user, TaskInput(task=body.task, title=body.title, repo_url=body.repo_url, repo_ref=body.repo_ref),
            source="web", client_info={"ip": audit.client_ip(request), "client": "console"}, request=request,
        )
    except TaskInputError as exc:
        raise HTTPException(422, str(exc)) from exc
    return _envelope(request, **_task_detail(db, user, task))


@router.get("/tasks/{task_id}")
def task_detail(request: Request, task_id: str, user: User = Depends(require_user), db: Session = Depends(get_db)):
    return _envelope(request, **_task_detail(db, user, _owned(db, user, task_id)))


@router.get("/tasks/{task_id}/events")
def task_events(
    task_id: str, after: int = Query(0, ge=0), user: User = Depends(require_user), db: Session = Depends(get_db),
) -> dict[str, Any]:
    task = _owned(db, user, task_id)
    detail = _task_detail(db, user, task, events_after=after)
    return {
        "status": task.status,
        "status_reason": task.status_reason,
        "finished": task.status in TaskStatus.TERMINAL,
        "duration_s": detail["duration_s"],
        "result_text": task.result_text,
        "agent_usage": task.agent_usage or {},
        "patch_stats": task.patch_stats or {},
        "outputs": detail["outputs"],
        "raw_patch": detail["raw_patch"] if task.status in TaskStatus.TERMINAL else None,
        "events": detail["events"],
    }


@router.post("/tasks/{task_id}/cancel", dependencies=[Depends(verify_csrf)])
def cancel(request: Request, task_id: str, user: User = Depends(require_user), db: Session = Depends(get_db)):
    task = _owned(db, user, task_id)
    actor = f"admin:{user.id}" if task.user_id != user.id else f"user:{user.id}"
    request_cancel(db, task, actor=actor, request=request)
    return _envelope(request, id=task.id, status=task.status, cancel_requested=task.cancel_requested,
                     status_reason=task.status_reason)


@router.post("/settings", dependencies=[Depends(verify_csrf)])
def save_settings(request: Request, body: SettingsIn, user: User = Depends(require_user), db: Session = Depends(get_db)):
    before = _apply_settings(user, body)
    audit.record(
        db, "settings.update", actor=f"user:{user.id}", user_id=user.id, request=request,
        before=before,
        after={"agent": user.pref_agent, "model": user.pref_model, "sandbox": user.pref_sandbox,
               "harness": user.pref_harness, "timeout": user.pref_timeout_s},
    )
    return _envelope(request, options=_options_view(user), user=_user_view(user))


@router.get("/keys")
def list_keys(request: Request, user: User = Depends(require_user), db: Session = Depends(get_db)):
    keys = db.scalars(select(ApiKey).where(ApiKey.user_id == user.id).order_by(ApiKey.created_at.desc())).all()
    return _envelope(request, keys=[_key_view(key) for key in keys])


def _key_view(key: ApiKey) -> dict[str, Any]:
    return {
        "id": key.id,
        "name": key.name,
        "prefix": key.prefix,
        "created_at": _iso(key.created_at),
        "last_used_at": _iso(key.last_used_at),
        "last_used_ip": key.last_used_ip,
        "active": key.revoked_at is None,
    }


@router.post("/keys", status_code=201, dependencies=[Depends(verify_csrf)])
def create_key(request: Request, body: KeyIn, user: User = Depends(require_user), db: Session = Depends(get_db)):
    plaintext, prefix, digest = generate_api_key()
    key = ApiKey(user_id=user.id, name=body.name.strip()[:100] or "default", prefix=prefix, key_hash=digest)
    db.add(key)
    db.flush()
    audit.record(db, "apikey.create", actor=f"user:{user.id}", user_id=user.id,
                 target=f"apikey:{key.id}", request=request, name=key.name, prefix=key.prefix)
    return _envelope(request, token=plaintext, key=_key_view(key))


@router.post("/keys/{key_id}/revoke", dependencies=[Depends(verify_csrf)])
def revoke_key(request: Request, key_id: int, user: User = Depends(require_user), db: Session = Depends(get_db)):
    key = db.get(ApiKey, key_id)
    if key is None or key.user_id != user.id:
        raise HTTPException(404, "密钥不存在")
    if key.revoked_at is None:
        key.revoked_at = utcnow()
        audit.record(db, "apikey.revoke", actor=f"user:{user.id}", user_id=user.id,
                     target=f"apikey:{key.id}", request=request, prefix=key.prefix)
    return _envelope(request, key=_key_view(key))


@router.get("/providers")
def providers(request: Request, user: User = Depends(require_user), db: Session = Depends(get_db)):
    return _envelope(request, providers=_provider_rows(db), can_edit=user.is_admin)


@router.post("/providers/{provider}", dependencies=[Depends(verify_csrf)])
def save_provider(
    request: Request, provider: str, body: ProviderIn,
    user: User = Depends(require_admin), db: Session = Depends(get_db),
):
    if provider not in SUPPORTED_PROVIDERS:
        raise HTTPException(404, "未知提供商")
    base_url = body.base_url.strip().rstrip("/")
    if base_url and (urlsplit(base_url).scheme not in ("http", "https") or not urlsplit(base_url).hostname):
        raise HTTPException(422, "Base URL 必须是有效的 http(s) 地址")
    config = db.get(ProviderConfig, provider) or ProviderConfig(provider=provider, enabled=True)
    config.base_url = base_url
    if body.enabled is not None:
        config.enabled = body.enabled
    if body.clear_api_key:
        config.api_key_enc = None
    elif body.api_key.strip():
        config.api_key_enc = encrypt(body.api_key.strip())
    db.add(config)
    audit.record(db, "admin.provider_update", actor=f"admin:{user.id}", user_id=user.id, request=request,
                 provider=provider, base_url=base_url, enabled=config.enabled,
                 api_key_updated=bool(body.api_key.strip()), api_key_cleared=body.clear_api_key)
    return _envelope(request, providers=_provider_rows(db))


@router.post("/providers/{provider}/check", dependencies=[Depends(verify_csrf)])
def check_provider(provider: str, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    rows = {row["id"]: row for row in _provider_rows(db)}
    row = rows.get(provider)
    if row is None:
        raise HTTPException(404, "未知提供商")
    if not row["configured"]:
        return {"ok": False, "message": f"{row['name']} 未配置 API Key"}
    if not row["enabled"]:
        return {"ok": False, "message": f"{row['name']} 已停用"}
    return {"ok": True, "message": f"{row['name']} 密钥已配置（{row['key_source']}），未向供应商发起外呼"}


@router.get("/audit")
def audit_page(
    request: Request, page: int = 1, action: str = "",
    user: User = Depends(require_user), db: Session = Depends(get_db),
):
    page = max(1, page)
    page_size = 100
    query = select(AuditLog).where(AuditLog.user_id == user.id)
    if user.is_admin and action == "*":
        query = select(AuditLog)
    elif action:
        query = query.where(AuditLog.action.like(f"{action}%"))
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = db.scalars(query.order_by(AuditLog.ts.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    return _envelope(
        request,
        page=page,
        pages=max(1, -(-total // page_size)),
        logs=[{
            "id": str(row.id),
            "ts": _iso(row.ts),
            "action": row.action,
            "actor": row.actor,
            "ip": row.ip or "",
            "target": row.target,
            "detail": row.detail or {},
        } for row in rows],
    )
