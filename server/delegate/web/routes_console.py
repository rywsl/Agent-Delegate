"""JSON API for the React console. The Jinja site stays available beside it."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import audit, billing, harness, harness_update
from ..config import get_settings
from ..models import ApiKey, AuditLog, RedeemCode, Task, TaskEvent, TaskStatus, User, UserProviderKey, utcnow
from ..security import decrypt, encrypt, generate_api_key, hash_password, verify_password
from ..site import (
    ensure_free_seconds,
    model_map,
    offered_models,
    points_per_usd,
    put,
    queue_limits,
    sandbox_points_per_minute,
    sandbox_usd_per_minute,
    snapshot,
    usd_to_points,
)
from ..tasks import (
    QueueFull,
    TaskInput,
    TaskInputError,
    create_task,
    get_user_task,
    public_view,
    queue_position,
    request_cancel,
    resolve_options,
)
from .deps import csrf_token, current_user, get_db, login_session, require_admin, require_user, verify_csrf

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/console")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class AuthIn(BaseModel):
    email: str
    password: str
    display_name: str = ""


class SettingsIn(BaseModel):
    display_name: str = ""
    agent: str
    model: str = ""
    budget_usd: float | None = None
    timeout_min: int | None = None


class TaskIn(BaseModel):
    task: str = Field(..., max_length=100_000)
    title: str | None = None


class KeyIn(BaseModel):
    name: str = "default"


class ProviderKeyIn(BaseModel):
    api_key: str = ""
    base_url: str = ""
    enabled: bool = True


class PlatformIn(BaseModel):
    sandbox_usd_per_minute: float | None = None
    sandbox_points_per_minute: float | None = None
    points_per_usd: float | None = None
    free_sandbox_minutes: float
    max_queued_tasks: int
    max_queued_per_user: int
    models: dict[str, list[str]] = {}


class ChannelIn(BaseModel):
    name: str
    type: int
    key: str = ""
    base_url: str = ""
    models: str = ""
    group: str = "default"


class CodeIn(BaseModel):
    amount_usd: float
    count: int = 1
    valid_days: int = 0
    note: str = ""


class QuotaIn(BaseModel):
    usd: float
    direction: str = "add"
    note: str = ""


class FreeSecondsIn(BaseModel):
    seconds: int


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _user_view(db: Session, user: User) -> dict[str, Any]:
    balance = billing.balance_quota(user)
    agent = user.pref_agent if user.pref_agent in get_settings().agents else get_settings().default_agent
    return {
        "id": user.id,
        "email": user.email,
        "display_name": user.display_name,
        "is_admin": user.is_admin,
        "balance_usd": round(get_settings().quota_to_usd(balance), 4) if balance is not None else None,
        "points": int(user.points or 0),
        "sandbox_free_seconds": ensure_free_seconds(db, user),
        "billing_mode": billing.mode_for(db, user, agent),
    }


def _envelope(request: Request, db: Session, user: User | None, **payload: Any) -> dict[str, Any]:
    return {"csrf": csrf_token(request), "user": _user_view(db, user) if user else None, **payload}


def _task_row(db: Session, task: Task) -> dict[str, Any]:
    stats = task.patch_stats or {}
    return {
        "id": task.id,
        "title": task.title,
        "status": task.status,
        "agent": task.agent,
        "harness": task.agent,
        "model": task.model,
        "source": task.source,
        "billing_mode": task.billing_mode,
        "created_at": _iso(task.created_at),
        "started_at": _iso(task.started_at),
        "finished_at": _iso(task.finished_at),
        "duration_s": _duration(task),
        "timeout_s": task.timeout_s,
        "max_turns": task.max_turns,
        "container_name": task.container_name,
        "sandbox_limits": task.sandbox_limits or {},
        "patch_stats": {
            "files": stats.get("files", 0),
            "insertions": stats.get("insertions", 0),
            "deletions": stats.get("deletions", 0),
            "bytes": stats.get("bytes", 0),
            "paths": (stats.get("paths") or [])[:100],
        },
        "agent_usage": task.agent_usage or {},
        "queue_position": queue_position(db, task),
        "sandbox_points": int(task.sandbox_billed_points or 0),
        "cost_usd": round(get_settings().quota_to_usd((task.billed_quota or 0) + (task.sandbox_billed_quota or 0)), 4),
    }


def _duration(task: Task) -> float | None:
    if task.duration_s:
        return round(float(task.duration_s), 1)
    if task.started_at is None:
        return None
    end = task.finished_at or utcnow()
    start = task.started_at
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    return round((end - start).total_seconds(), 1)


def _event_view(row: TaskEvent) -> dict[str, Any]:
    data = row.data or {}
    tool_args = data.get("input")
    tool_result = data.get("content") if row.kind == "tool_result" else None
    stamp = row.ts.astimezone(timezone.utc).strftime("%H:%M:%S") if row.ts else ""
    return {
        "id": f"ev-{row.id}",
        "seq": row.seq,
        "ts": stamp,
        "kind": row.kind,
        "summary": row.summary,
        "tool_name": data.get("name") or data.get("tool_name"),
        "tool_args": tool_args if isinstance(tool_args, (dict, str)) else None,
        "tool_result": tool_result if isinstance(tool_result, str) else None,
    }


def _console_task(db: Session, task: Task, *, detail: bool = False) -> dict[str, Any]:
    row = _task_row(db, task)
    row["prompt"] = task.prompt if detail else ""
    row["status_reason"] = task.status_reason
    row["result_text"] = task.result_text or ""
    if not detail:
        return row
    view = public_view(db, task)
    patch = view.get("patch") or {}
    outputs = (view.get("outputs") or {}).get("files") or []
    row["raw_patch"] = patch.get("inline")
    row["outputs"] = [{"path": item["path"], "size": item.get("size", 0), "downloadUrl": item.get("url")} for item in outputs]
    if view.get("billing"):
        row["billing"] = view["billing"]
    events = db.scalars(select(TaskEvent).where(TaskEvent.task_id == task.id).order_by(TaskEvent.seq).limit(500)).all()
    row["events"] = [_event_view(item) for item in events]
    return row


def _heatmap(tasks: list[Task]) -> dict[str, Any]:
    today = datetime.now(timezone.utc).date()
    start = today - timedelta(days=52 * 7 - 1)
    buckets = [0] * (52 * 7)
    lines = 0
    month_lines: dict[str, int] = {}
    peak_value = 0
    peak_date = ""
    for task in tasks:
        created = task.created_at
        if created is None:
            continue
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        day = created.astimezone(timezone.utc).date()
        stats = task.patch_stats or {}
        changed = int(stats.get("insertions") or 0) + int(stats.get("deletions") or 0)
        lines += changed
        index = (day - start).days
        if 0 <= index < len(buckets):
            buckets[index] += changed or (1 if task.status == TaskStatus.SUCCEEDED else 0)
            if buckets[index] > peak_value:
                peak_value = buckets[index]
                peak_date = day.strftime("%b %d, %Y")
        label = day.strftime("%B")
        month_lines[label] = month_lines.get(label, 0) + changed
    peak_level = max(buckets) or 1
    cells = [0 if value == 0 else min(4, max(1, round(value / peak_level * 4))) for value in buckets]
    months: list[str] = []
    seen: set[str] = set()
    cursor = start
    while cursor <= today:
        label = cursor.strftime("%b")
        if label not in seen:
            months.append(label)
            seen.add(label)
        cursor += timedelta(days=1)
    active = max(month_lines, key=month_lines.get) if month_lines else ""
    return {
        "cells": cells,
        "months": months,
        "patch_lines": lines,
        "active_month": active or "—",
        "peak_date": peak_date or "—",
    }


@router.get("/session")
def session(request: Request, user: User | None = Depends(current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    options = resolve_options(user, db) if user else None
    s = get_settings()
    return _envelope(
        request, db, user,
        allow_registration=s.allow_registration,
        agents=[{"id": item.id, "label": item.label, "provider": item.provider} for item in harness.HARNESSES if item.id in s.agents],
        models=model_map(db, s.agents) if user else {},
        options=options,
        sandbox_usd_per_minute=sandbox_usd_per_minute(db) if user else None,
        sandbox_points_per_minute=sandbox_points_per_minute(db) if user else None,
        points_per_usd=points_per_usd(db) if user else None,
    )


@router.post("/login", dependencies=[Depends(verify_csrf)])
def login(request: Request, body: AuthIn, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(func.lower(User.email) == body.email.strip().lower()))
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(401, "邮箱或密码错误")
    if not user.is_active:
        raise HTTPException(403, "账户已被停用")
    user.last_login_at = utcnow()
    login_session(request, user)
    audit.record(db, "auth.login", actor=f"user:{user.id}", user_id=user.id, request=request, client="console")
    return _envelope(request, db, user)


@router.post("/register", dependencies=[Depends(verify_csrf)])
def register(request: Request, body: AuthIn, db: Session = Depends(get_db)):
    s = get_settings()
    if not s.allow_registration:
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
    ensure_free_seconds(db, user)
    audit.record(db, "auth.register", actor=f"user:{user.id}", user_id=user.id, request=request, admin=first_user)
    db.commit()
    try:
        billing.ensure_mirror(db, user)
        if s.signup_credit_usd > 0:
            billing.adjust(db, user, s.usd_to_quota(s.signup_credit_usd), kind="signup_credit", actor="system", note="注册赠送")
            billing.grant_recharge_points(db, user, s.signup_credit_usd, kind="signup_credit", actor="system", note="注册赠送")
        db.commit()
    except billing.BillingError as exc:
        db.rollback()
        log.warning("mirror account for %s not created yet: %s", user.email, exc)
    login_session(request, user)
    return _envelope(request, db, user)


@router.post("/logout", dependencies=[Depends(verify_csrf)])
def logout(request: Request, user: User | None = Depends(current_user), db: Session = Depends(get_db)):
    if user:
        audit.record(db, "auth.logout", actor=f"user:{user.id}", user_id=user.id, request=request)
    request.session.clear()
    return {"ok": True, "csrf": csrf_token(request)}


@router.get("/dashboard")
def dashboard(user: User = Depends(require_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    counts = dict(db.execute(select(Task.status, func.count()).where(Task.user_id == user.id).group_by(Task.status)).all())
    recent = db.scalars(select(Task).where(Task.user_id == user.id).order_by(Task.created_at.desc()).limit(8)).all()
    global_max, per_user = queue_limits(db)
    waiting = int(db.scalar(select(func.count()).select_from(Task).where(Task.status == TaskStatus.QUEUED)) or 0)
    owned = db.scalars(select(Task).where(Task.user_id == user.id)).all()
    tokens = {"input_tokens": 0, "output_tokens": 0, "cache_read_tokens": 0, "cache_write_tokens": 0}
    for task in owned:
        usage = task.agent_usage or {}
        if usage:
            for key in tokens:
                tokens[key] += int(usage.get(key) or 0)
        else:
            tokens["input_tokens"] += int(task.billed_prompt_tokens or 0)
            tokens["output_tokens"] += int(task.billed_completion_tokens or 0)
    prompt_plus_cache = tokens["input_tokens"] + tokens["cache_read_tokens"]
    settings = get_settings()
    active = sum(1 for task in owned if task.status in (TaskStatus.PREPARING, TaskStatus.RUNNING))
    return {
        "counts": counts,
        "tasks": [_task_row(db, task) for task in recent],
        "queue": {"waiting": waiting, "max": global_max, "per_user": per_user},
        "sandbox_usd_per_minute": sandbox_usd_per_minute(db),
        "usage": {**tokens, "tokens": sum(tokens.values()), "cache_rate": round(tokens["cache_read_tokens"] / prompt_plus_cache * 100, 1) if prompt_plus_cache else 0},
        "heatmap": _heatmap(owned),
        "sandbox": {
            "memory": settings.sandbox_memory,
            "cpus": settings.sandbox_cpus,
            "capacity": max(1, settings.sandbox_max_concurrent),
            "active": active,
            "uid": 10001,
        },
    }


@router.get("/tasks")
def list_tasks(user: User = Depends(require_user), db: Session = Depends(get_db), status: str = "") -> dict[str, Any]:
    query = select(Task).where(Task.user_id == user.id)
    if status:
        query = query.where(Task.status == status)
    rows = db.scalars(query.order_by(Task.created_at.desc()).limit(100)).all()
    return {"tasks": [_console_task(db, task) for task in rows]}


@router.post("/tasks", status_code=201, dependencies=[Depends(verify_csrf)])
def submit_task(request: Request, body: TaskIn, user: User = Depends(require_user), db: Session = Depends(get_db)):
    try:
        task = create_task(db, user, TaskInput(task=body.task, title=body.title), source="web",
                           client_info={"ip": audit.client_ip(request), "client": "console"}, request=request)
    except QueueFull as exc:
        raise HTTPException(429, str(exc)) from exc
    except TaskInputError as exc:
        raise HTTPException(422, str(exc)) from exc
    return public_view(db, task)


@router.get("/tasks/{task_id}")
def task_detail(task_id: str, user: User = Depends(require_user), db: Session = Depends(get_db)):
    task = get_user_task(db, user, task_id)
    if task is None:
        raise HTTPException(404, "任务不存在")
    return _console_task(db, task, detail=True)


@router.get("/tasks/{task_id}/events")
def task_events(task_id: str, after: int = Query(0, ge=0), user: User = Depends(require_user),
                db: Session = Depends(get_db)):
    task = get_user_task(db, user, task_id)
    if task is None:
        raise HTTPException(404, "任务不存在")
    rows = db.scalars(
        select(TaskEvent).where(TaskEvent.task_id == task.id, TaskEvent.seq > after).order_by(TaskEvent.seq).limit(500)
    ).all()
    detail = _console_task(db, task, detail=True)
    return {
        "events": [_event_view(row) for row in rows],
        "finished": task.status in TaskStatus.TERMINAL,
        "status": task.status,
        "status_reason": task.status_reason,
        "duration_s": detail["duration_s"],
        "result_text": detail["result_text"],
        "agent_usage": detail["agent_usage"],
        "patch_stats": detail["patch_stats"],
        "sandbox_points": detail["sandbox_points"],
        "raw_patch": detail["raw_patch"],
        "outputs": detail["outputs"],
    }


@router.post("/tasks/{task_id}/cancel", dependencies=[Depends(verify_csrf)])
def cancel(request: Request, task_id: str, user: User = Depends(require_user), db: Session = Depends(get_db)):
    task = get_user_task(db, user, task_id)
    if task is None:
        raise HTTPException(404, "任务不存在")
    request_cancel(db, task, actor=f"user:{user.id}", request=request)
    return {"ok": True, "status": task.status}


@router.post("/settings", dependencies=[Depends(verify_csrf)])
def save_settings(request: Request, body: SettingsIn, user: User = Depends(require_user), db: Session = Depends(get_db)):
    s = get_settings()
    if body.agent not in s.agents:
        raise HTTPException(400, "不支持的 agent")
    models = offered_models(db, body.agent)
    model = body.model if body.model in models else (models[0] if models else user.pref_model)
    user.pref_agent = body.agent
    user.pref_model = model
    if body.budget_usd is not None:
        user.pref_budget_usd = max(0.01, min(body.budget_usd, s.max_budget_usd))
    if body.timeout_min is not None:
        user.pref_timeout_s = max(60, min(body.timeout_min * 60, s.max_timeout_s))
    if body.display_name.strip():
        user.display_name = body.display_name.strip()[:100]
    audit.record(db, "settings.update", actor=f"user:{user.id}", user_id=user.id, request=request, client="console")
    return {"options": resolve_options(user, db)}


@router.get("/keys")
def list_keys(user: User = Depends(require_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(ApiKey).where(ApiKey.user_id == user.id).order_by(ApiKey.id.desc())).all()
    return {"keys": [{
        "id": row.id, "name": row.name, "prefix": row.prefix, "active": row.active,
        "created_at": _iso(row.created_at), "last_used_at": _iso(row.last_used_at), "last_used_ip": row.last_used_ip,
    } for row in rows]}


@router.post("/keys", status_code=201, dependencies=[Depends(verify_csrf)])
def create_key(request: Request, body: KeyIn, user: User = Depends(require_user), db: Session = Depends(get_db)):
    full, prefix, digest = generate_api_key()
    row = ApiKey(user_id=user.id, name=body.name.strip()[:100] or "default", prefix=prefix, key_hash=digest)
    db.add(row)
    db.flush()
    audit.record(db, "apikey.create", actor=f"user:{user.id}", user_id=user.id, target=str(row.id), request=request)
    return {"id": row.id, "prefix": prefix, "token": full}


@router.post("/keys/{key_id}/revoke", dependencies=[Depends(verify_csrf)])
def revoke_key(request: Request, key_id: int, user: User = Depends(require_user), db: Session = Depends(get_db)):
    row = db.get(ApiKey, key_id)
    if row is None or row.user_id != user.id:
        raise HTTPException(404, "密钥不存在")
    row.revoked_at = utcnow()
    audit.record(db, "apikey.revoke", actor=f"user:{user.id}", user_id=user.id, target=str(row.id), request=request)
    return {"ok": True}


def _provider_views(db: Session, user: User) -> list[dict[str, Any]]:
    rows = {row.provider: row for row in db.scalars(select(UserProviderKey).where(UserProviderKey.user_id == user.id))}
    seen: set[str] = set()
    result = []
    for item in harness.HARNESSES:
        if item.provider in seen or item.id not in get_settings().agents:
            continue
        seen.add(item.provider)
        row = rows.get(item.provider)
        hint = ""
        if row and row.api_key_enc:
            try:
                hint = decrypt(row.api_key_enc)[-4:]
            except Exception:  # noqa: BLE001 - a rotated secret leaves the stored key unreadable
                hint = "????"
        result.append({
            "provider": item.provider,
            "label": item.label,
            "harness": item.id,
            "configured": bool(row and row.api_key_enc),
            "enabled": bool(row and row.enabled),
            "hint": hint,
            "base_url": row.base_url if row else "",
            "default_base_url": item.default_base_url,
        })
    return result


@router.get("/provider-keys")
def provider_keys(user: User = Depends(require_user), db: Session = Depends(get_db)):
    return {"providers": _provider_views(db, user)}


@router.post("/provider-keys/{provider}", dependencies=[Depends(verify_csrf)])
def save_provider_key(provider: str, body: ProviderKeyIn, user: User = Depends(require_user),
                      db: Session = Depends(get_db)):
    known = {item.provider for item in harness.HARNESSES}
    if provider not in known:
        raise HTTPException(400, "未知的提供商")
    row = db.scalar(select(UserProviderKey).where(UserProviderKey.user_id == user.id, UserProviderKey.provider == provider))
    if row is None:
        row = UserProviderKey(user_id=user.id, provider=provider)
        db.add(row)
    if body.api_key.strip():
        row.api_key_enc = encrypt(body.api_key.strip())
    elif not row.api_key_enc:
        raise HTTPException(400, "需要填写 API key")
    row.base_url = body.base_url.strip()
    row.enabled = body.enabled
    row.updated_at = utcnow()
    audit.record(db, "provider_key.save", actor=f"user:{user.id}", user_id=user.id, target=provider, enabled=body.enabled)
    return {"providers": _provider_views(db, user)}


@router.delete("/provider-keys/{provider}", dependencies=[Depends(verify_csrf)])
def delete_provider_key(provider: str, user: User = Depends(require_user), db: Session = Depends(get_db)):
    row = db.scalar(select(UserProviderKey).where(UserProviderKey.user_id == user.id, UserProviderKey.provider == provider))
    if row is not None:
        db.delete(row)
    audit.record(db, "provider_key.delete", actor=f"user:{user.id}", user_id=user.id, target=provider)
    return {"providers": _provider_views(db, user)}


@router.get("/billing")
def billing_page(user: User = Depends(require_user), db: Session = Depends(get_db), page: int = 1):
    page = max(1, page)
    usage, total = [], 0
    error = None
    try:
        usage, total = billing.user_logs(user, page=page, page_size=20)
    except billing.BillingError as exc:
        error = str(exc)
    s = get_settings()
    rows = []
    for log_row in usage:
        parsed = billing.parse_log(log_row)
        rows.append({
            "time": log_row.get("created_at"),
            "type": log_row.get("type"),
            "model": log_row.get("model_name"),
            "input_tokens": parsed.input_tokens,
            "output_tokens": parsed.output_tokens,
            "quota": log_row.get("quota", 0),
            "cost_usd": round(s.quota_to_usd(log_row.get("quota", 0)), 6),
            "content": (log_row.get("content") or "")[:200],
        })
    return {"logs": rows, "page": page, "total": total, "error": error}


class RedeemIn(BaseModel):
    code: str


@router.post("/billing/redeem", dependencies=[Depends(verify_csrf)])
def redeem_code(request: Request, body: RedeemIn, user: User = Depends(require_user), db: Session = Depends(get_db)):
    quota = billing.redeem(db, user, body.code.strip(), actor=f"user:{user.id}", request=request)
    usd = get_settings().quota_to_usd(quota)
    return {
        "credited_usd": round(usd, 4),
        "credited_points": usd_to_points(db, usd),
        "points": int(user.points or 0),
        "points_per_usd": points_per_usd(db),
    }


@router.get("/audit")
def audit_page(user: User = Depends(require_user), db: Session = Depends(get_db), page: int = 1):
    page = max(1, page)
    query = select(AuditLog).where(AuditLog.user_id == user.id)
    total = int(db.scalar(select(func.count()).select_from(query.subquery())) or 0)
    rows = db.scalars(query.order_by(AuditLog.ts.desc()).offset((page - 1) * 30).limit(30)).all()
    payload = [{
        "id": str(row.id), "ts": _iso(row.ts), "action": row.action, "actor": row.actor,
        "target": row.target, "ip": row.ip or "", "detail": row.detail or {},
    } for row in rows]
    return {"total": total, "page": page, "rows": payload, "logs": payload}


# --------------------------------------------------------------------------- admin
@router.get("/admin/overview")
def admin_overview(user: User = Depends(require_admin), db: Session = Depends(get_db)):
    ok, message = billing.health()
    counts = dict(db.execute(select(Task.status, func.count()).group_by(Task.status)).all())
    return {
        "newapi_ok": ok,
        "newapi_message": message,
        "counts": counts,
        "users": int(db.scalar(select(func.count()).select_from(User)) or 0),
        "settings": snapshot(db),
    }


@router.get("/admin/settings")
def admin_settings(user: User = Depends(require_admin), db: Session = Depends(get_db)):
    return snapshot(db)


@router.post("/admin/settings", dependencies=[Depends(verify_csrf)])
def save_admin_settings(body: PlatformIn, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    from ..site import (
        FREE_MINUTES_KEY,
        MAX_QUEUED_KEY,
        MAX_QUEUED_USER_KEY,
        POINTS_PER_USD_KEY,
        SANDBOX_POINTS_KEY,
        SANDBOX_PRICE_KEY,
        save_model_map,
    )

    if body.points_per_usd is None or body.points_per_usd <= 0:
        raise HTTPException(400, "充值比例必须大于 0")
    if body.sandbox_points_per_minute is None or body.sandbox_points_per_minute < 0 or body.free_sandbox_minutes < 0:
        raise HTTPException(400, "沙箱积分单价和免费额度不能为负")
    if body.max_queued_tasks < 1 or body.max_queued_per_user < 1:
        raise HTTPException(400, "队列上限至少为 1")
    put(db, POINTS_PER_USD_KEY, str(body.points_per_usd))
    put(db, SANDBOX_POINTS_KEY, str(body.sandbox_points_per_minute))
    if body.sandbox_usd_per_minute is not None:
        if body.sandbox_usd_per_minute < 0:
            raise HTTPException(400, "价格不能为负")
        put(db, SANDBOX_PRICE_KEY, str(body.sandbox_usd_per_minute))
    put(db, FREE_MINUTES_KEY, str(body.free_sandbox_minutes))
    put(db, MAX_QUEUED_KEY, str(int(body.max_queued_tasks)))
    put(db, MAX_QUEUED_USER_KEY, str(int(body.max_queued_per_user)))
    if body.models:
        save_model_map(db, body.models)
    audit.record(db, "admin.settings", actor=f"admin:{user.id}", user_id=user.id)
    return snapshot(db)


@router.get("/admin/users")
def admin_users(user: User = Depends(require_admin), db: Session = Depends(get_db), q: str = ""):
    query = select(User)
    if q:
        query = query.where(User.email.ilike(f"%{q}%"))
    rows = db.scalars(query.order_by(User.id.desc()).limit(200)).all()
    return {"users": [{
        "id": row.id, "email": row.email, "display_name": row.display_name,
        "is_admin": row.is_admin, "is_active": row.is_active,
        "points": int(row.points or 0),
        "sandbox_free_seconds": row.sandbox_free_seconds,
        "newapi_user_id": row.newapi_user_id,
    } for row in rows]}


@router.post("/admin/users/{user_id}/quota", dependencies=[Depends(verify_csrf)])
def admin_quota(user_id: int, body: QuotaIn, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(404, "用户不存在")
    signed_usd = abs(body.usd) * (1 if body.direction != "subtract" else -1)
    signed = get_settings().usd_to_quota(abs(body.usd)) * (1 if signed_usd > 0 else -1)
    before = int(target.points or 0)
    billing.adjust(db, target, signed, kind="admin_grant" if signed > 0 else "admin_deduct",
                   actor=f"admin:{user.id}", note=body.note[:200])
    billing.grant_recharge_points(
        db, target, signed_usd, kind="admin_grant" if signed_usd > 0 else "admin_deduct",
        actor=f"admin:{user.id}", note=body.note[:200],
    )
    return {
        "balance_usd": round(get_settings().quota_to_usd(billing.balance_quota(target) or 0), 4),
        "points": int(target.points or 0),
        "points_delta": int(target.points or 0) - before,
    }


@router.post("/admin/users/{user_id}/free-seconds", dependencies=[Depends(verify_csrf)])
def admin_free(user_id: int, body: FreeSecondsIn, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(404, "用户不存在")
    target.sandbox_free_seconds = max(0, int(body.seconds))
    audit.record(db, "admin.free_seconds", actor=f"admin:{user.id}", user_id=target.id, seconds=target.sandbox_free_seconds)
    return {"sandbox_free_seconds": target.sandbox_free_seconds}


@router.post("/admin/users/{user_id}/toggle", dependencies=[Depends(verify_csrf)])
def admin_toggle(user_id: int, user: User = Depends(require_admin), db: Session = Depends(get_db), field: str = "active"):
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(404, "用户不存在")
    if field == "active":
        target.is_active = not target.is_active
    elif field == "admin":
        target.is_admin = not target.is_admin
    else:
        raise HTTPException(400, "未知字段")
    return {"is_active": target.is_active, "is_admin": target.is_admin}


@router.post("/admin/codes", dependencies=[Depends(verify_csrf)])
def admin_codes(body: CodeIn, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    count = max(1, min(body.count, 100))
    codes = billing.create_codes(
        db, get_settings().usd_to_quota(body.amount_usd), count, actor=f"admin:{user.id}",
        note=body.note.strip()[:200], valid_days=body.valid_days or None,
    )
    audit.record(db, "admin.codes_create", actor=f"admin:{user.id}", count=count, amount_usd=body.amount_usd)
    return {"codes": codes}


@router.get("/admin/codes")
def admin_code_list(user: User = Depends(require_admin), db: Session = Depends(get_db)):
    rows = db.scalars(select(RedeemCode).order_by(RedeemCode.id.desc()).limit(100)).all()
    return {"codes": [{
        "id": row.id, "hint": row.hint,
        "quota_usd": round(get_settings().quota_to_usd(row.quota), 4),
        "points": usd_to_points(db, get_settings().quota_to_usd(row.quota)),
        "note": row.note, "created_at": _iso(row.created_at), "redeemed_by": row.redeemed_by,
        "redeemed_at": _iso(row.redeemed_at),
    } for row in rows]}


@router.get("/admin/tasks")
def admin_tasks(user: User = Depends(require_admin), db: Session = Depends(get_db), status: str = ""):
    query = select(Task)
    if status:
        query = query.where(Task.status == status)
    rows = db.scalars(query.order_by(Task.created_at.desc()).limit(100)).all()
    owners = {u.id: u.email for u in db.scalars(select(User).where(User.id.in_({t.user_id for t in rows})))}
    return {"tasks": [{**_task_row(db, task), "email": owners.get(task.user_id, "")} for task in rows]}


@router.get("/admin/channels")
def admin_channels(user: User = Depends(require_admin)):
    rows = billing.admin_call(billing.NewApi.list_channels)
    public = []
    for row in rows:
        item = {key: value for key, value in row.items() if key != "key"}
        item["has_key"] = bool(row.get("key"))
        public.append(item)
    return {"channels": public, "types": [{"id": type_id, "label": label} for type_id, label in harness.CHANNEL_TYPES]}


@router.post("/admin/channels", dependencies=[Depends(verify_csrf)])
def admin_channel_create(body: ChannelIn, user: User = Depends(require_admin)):
    if not body.key.strip():
        raise HTTPException(400, "需要上游密钥")
    billing.admin_call(billing.NewApi.create_channel, {
        "name": body.name.strip()[:100],
        "type": int(body.type),
        "key": body.key.strip(),
        "base_url": body.base_url.strip(),
        "models": body.models.strip(),
        "groups": [body.group.strip() or "default"],
    })
    return {"ok": True}


@router.delete("/admin/channels/{channel_id}", dependencies=[Depends(verify_csrf)])
def admin_channel_delete(channel_id: int, user: User = Depends(require_admin)):
    billing.admin_call(billing.NewApi.delete_channel, channel_id)
    return {"ok": True}


@router.post("/admin/channels/{channel_id}/test", dependencies=[Depends(verify_csrf)])
def admin_channel_test(channel_id: int, user: User = Depends(require_admin), model: str = ""):
    return {"result": billing.admin_call(billing.NewApi.test_channel, channel_id, model)}


@router.post("/admin/harnesses/update", dependencies=[Depends(verify_csrf)])
def admin_harness_update(user: User = Depends(require_admin), db: Session = Depends(get_db)):
    from ..site import HARNESS_UPDATED_KEY

    try:
        output = harness_update.update_clis()
    except Exception as exc:  # noqa: BLE001 - docker and npm failures are shown to the admin
        raise HTTPException(502, f"更新 CLI 失败：{exc}") from exc
    put(db, HARNESS_UPDATED_KEY, utcnow().isoformat())
    audit.record(db, "admin.harness_update", actor=f"admin:{user.id}", user_id=user.id)
    return {"ok": True, "output": output[-4000:]}
