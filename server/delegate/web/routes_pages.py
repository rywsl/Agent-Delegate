"""Signed-in user pages: dashboard, tasks with the full audit trail, keys and settings."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, RedirectResponse, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import audit, transfer
from ..config import get_settings
from ..models import ApiKey, AuditLog, Task, TaskEvent, TaskStatus, Upload, User, utcnow
from ..security import generate_api_key, hash_password, verify_password
from ..tasks import (
    TaskInput, TaskInputError, create_task, get_user_task, raw_log_path,
    request_cancel, resolve_options, task_dir,
)
from .deps import flash, get_db, login_session, render, require_user, verify_csrf
from .routes_api import artifact_response

router = APIRouter()
PAGE_SIZE = 25


def _page(page: int) -> tuple[int, int]:
    page = max(1, page)
    return page, (page - 1) * PAGE_SIZE


@router.get("/dashboard")
def dashboard(request: Request, user: User = Depends(require_user), db: Session = Depends(get_db)):
    counts = dict(db.execute(select(Task.status, func.count()).where(Task.user_id == user.id).group_by(Task.status)).all())
    recent = db.scalars(select(Task).where(Task.user_id == user.id).order_by(Task.created_at.desc()).limit(8)).all()
    has_key = db.scalar(select(func.count()).select_from(ApiKey).where(
        ApiKey.user_id == user.id, ApiKey.revoked_at.is_(None)
    ))
    return render(request, "dashboard.html", user, counts=counts,
                  active=sum(counts.get(s, 0) for s in TaskStatus.ACTIVE), total=sum(counts.values()),
                  recent=recent, has_key=bool(has_key), options=resolve_options(user))


@router.get("/tasks")
def task_list(request: Request, status: str = "", page: int = 1,
              user: User = Depends(require_user), db: Session = Depends(get_db)):
    page, offset = _page(page)
    query = select(Task).where(Task.user_id == user.id)
    if status:
        query = query.where(Task.status == status)
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    tasks = db.scalars(query.order_by(Task.created_at.desc()).offset(offset).limit(PAGE_SIZE)).all()
    return render(request, "tasks.html", user, tasks=tasks, status=status, page=page, total=total,
                  pages=max(1, -(-total // PAGE_SIZE)))


@router.get("/tasks/new")
def task_new_page(request: Request, user: User = Depends(require_user)):
    return render(request, "task_new.html", user, options=resolve_options(user))


@router.post("/tasks/new", dependencies=[Depends(verify_csrf)])
async def task_new(
    request: Request, task: str = Form(...), title: str = Form(""), repo_url: str = Form(""),
    repo_ref: str = Form(""), archive: UploadFile | None = None,
    user: User = Depends(require_user), db: Session = Depends(get_db),
):
    upload_ids: list[str] = []
    try:
        if archive is not None and archive.filename:
            name = archive.filename.replace("\\", "/").rsplit("/", 1)[-1]
            dest = "." if name.endswith((".zip", ".tar", ".tar.gz", ".tgz")) else name
            upload, _ = transfer.create_upload(db, user, dest, api_key_id=None, actor=f"user:{user.id}", request=request)

            async def chunks():
                while chunk := await archive.read(1024 * 1024):
                    yield chunk

            await transfer.receive_upload(upload, chunks())
            db.flush()
            upload_ids.append(upload.id)
        created = create_task(db, user, TaskInput(
            task=task, title=title or None, repo_url=repo_url or None, repo_ref=repo_ref or None,
            upload_ids=upload_ids,
        ), source="web", client_info={"ip": audit.client_ip(request), "client": "web"}, request=request)
    except (TaskInputError, transfer.TransferError) as exc:
        db.rollback()
        return render(request, "task_new.html", user, options=resolve_options(user), error=str(exc), form={
            "task": task, "title": title, "repo_url": repo_url, "repo_ref": repo_ref}, status_code=400)
    flash(request, "任务已提交", "success")
    return RedirectResponse(f"/tasks/{created.id}", status_code=303)


def _task_or_404(db: Session, user: User, task_id: str) -> Task:
    task = get_user_task(db, user, task_id)
    if task is None:
        raise HTTPException(404, "任务不存在")
    return task


@router.get("/tasks/{task_id}")
def task_detail(request: Request, task_id: str, user: User = Depends(require_user), db: Session = Depends(get_db)):
    task = _task_or_404(db, user, task_id)
    patch_file = task_dir(task.id) / "changes.patch"
    patch_text = None
    if patch_file.exists() and patch_file.stat().st_size <= 512 * 1024:
        patch_text = patch_file.read_bytes().decode("utf-8", errors="replace")
    api_key = db.get(ApiKey, task.api_key_id) if task.api_key_id else None
    trail = db.scalars(select(AuditLog).where(AuditLog.target == task.id).order_by(AuditLog.ts)).all()
    upload_trail = {u.id: u for u in db.scalars(select(Upload).where(
        Upload.id.in_([x["id"] for x in task.uploads or []])
    ))}
    return render(request, "task_detail.html", user, task=task, owner=db.get(User, task.user_id),
                  api_key=api_key, patch_text=patch_text,
                  patch_exists=patch_file.exists() and patch_file.stat().st_size > 0,
                  raw_log_exists=raw_log_path(task.id).exists(), trail=trail, upload_trail=upload_trail)


@router.get("/tasks/{task_id}/events")
def task_events(task_id: str, after: int = Query(0, ge=0), limit: int = Query(500, ge=1, le=2000),
                user: User = Depends(require_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    task = _task_or_404(db, user, task_id)
    rows = db.scalars(select(TaskEvent).where(
        TaskEvent.task_id == task.id, TaskEvent.seq > after
    ).order_by(TaskEvent.seq).limit(limit)).all()
    return {"status": task.status, "status_reason": task.status_reason, "finished": task.status in TaskStatus.TERMINAL,
            "events": [{"seq": e.seq, "ts": e.ts.isoformat(), "kind": e.kind, "summary": e.summary, "data": e.data}
                       for e in rows]}


@router.post("/tasks/{task_id}/cancel", dependencies=[Depends(verify_csrf)])
def task_cancel(request: Request, task_id: str, user: User = Depends(require_user), db: Session = Depends(get_db)):
    task = _task_or_404(db, user, task_id)
    actor = f"admin:{user.id}" if task.user_id != user.id else f"user:{user.id}"
    if request_cancel(db, task, actor=actor, request=request):
        flash(request, "已请求取消，正在停止沙箱并收集已有结果", "info")
    return RedirectResponse(f"/tasks/{task.id}", status_code=303)


@router.get("/tasks/{task_id}/artifacts/{artifact}")
def task_artifact(task_id: str, artifact: str, path: str = "",
                  user: User = Depends(require_user), db: Session = Depends(get_db)) -> Response:
    task = _task_or_404(db, user, task_id)
    if artifact == "log":
        log_file = raw_log_path(task.id)
        if not log_file.exists():
            raise HTTPException(404)
        return FileResponse(log_file, media_type="text/plain; charset=utf-8", filename=f"{task.id}-events.log")
    if artifact == "upload":
        meta = next((u for u in task.uploads or [] if u["id"] == path), None)
        file = task_dir(task.id) / "uploads" / path
        if meta is None or not file.exists():
            raise HTTPException(404)
        return FileResponse(file, media_type="application/octet-stream", filename=f"{task.id}-{path}.{meta['kind']}")
    if artifact == "file":
        meta = next((a for a in task.attachments or [] if a["path"] == path), None)
        if meta is None:
            raise HTTPException(404)
        return FileResponse(task_dir(task.id) / "files" / path, media_type="application/octet-stream",
                            filename=path.rsplit("/", 1)[-1])
    if artifact == "patch":
        return artifact_response(task, "patch", f"{task.id}.patch")
    if artifact == "outputs":
        return artifact_response(task, "outputs", f"{task.id}-outputs.tar.gz")
    if artifact == "output":
        return artifact_response(task, f"output:{path}", path.rsplit("/", 1)[-1] or "output")
    raise HTTPException(404)


@router.get("/keys")
def keys_page(request: Request, user: User = Depends(require_user), db: Session = Depends(get_db)):
    keys = db.scalars(select(ApiKey).where(ApiKey.user_id == user.id).order_by(ApiKey.created_at.desc())).all()
    return render(request, "keys.html", user, keys=keys, new_key=request.session.pop("new_key", None))


@router.post("/keys", dependencies=[Depends(verify_csrf)])
def keys_create(request: Request, name: str = Form("default"),
                user: User = Depends(require_user), db: Session = Depends(get_db)):
    plaintext, prefix, digest = generate_api_key()
    key = ApiKey(user_id=user.id, name=name.strip()[:100] or "default", prefix=prefix, key_hash=digest)
    db.add(key)
    db.flush()
    audit.record(db, "apikey.create", actor=f"user:{user.id}", user_id=user.id,
                 target=f"apikey:{key.id}", request=request, name=key.name, prefix=key.prefix)
    request.session["new_key"] = plaintext
    return RedirectResponse("/keys", status_code=303)


@router.post("/keys/{key_id}/revoke", dependencies=[Depends(verify_csrf)])
def keys_revoke(request: Request, key_id: int, user: User = Depends(require_user), db: Session = Depends(get_db)):
    key = db.get(ApiKey, key_id)
    if key is None or key.user_id != user.id:
        raise HTTPException(404)
    if key.revoked_at is None:
        key.revoked_at = utcnow()
        audit.record(db, "apikey.revoke", actor=f"user:{user.id}", user_id=user.id,
                     target=f"apikey:{key.id}", request=request, prefix=key.prefix)
        flash(request, f"密钥 {key.prefix}… 已吊销", "success")
    return RedirectResponse("/keys", status_code=303)


@router.get("/settings")
def settings_page(request: Request, user: User = Depends(require_user)):
    return render(request, "settings.html", user, options=resolve_options(user))


@router.post("/settings", dependencies=[Depends(verify_csrf)])
def settings_save(
    request: Request, agent: str = Form(...), model: str = Form(...), sandbox: str = Form(...),
    harness: str = Form(...), timeout_min: int = Form(...), display_name: str = Form(""),
    user: User = Depends(require_user), db: Session = Depends(get_db),
):
    s = get_settings()
    if agent not in s.agents or sandbox not in s.sandboxes or harness not in s.harnesses:
        flash(request, "不支持的执行配置", "error")
        return RedirectResponse("/settings", status_code=303)
    if model not in s.models_for(agent):
        model = s.models_for(agent)[0]
    before = {"agent": user.pref_agent, "model": user.pref_model, "sandbox": user.pref_sandbox,
              "harness": user.pref_harness, "timeout": user.pref_timeout_s}
    user.pref_agent = agent
    user.pref_model = model
    user.pref_sandbox = sandbox
    user.pref_harness = harness
    user.pref_timeout_s = max(60, min(timeout_min * 60, s.max_timeout_s))
    if display_name.strip():
        user.display_name = display_name.strip()[:100]
    audit.record(db, "settings.update", actor=f"user:{user.id}", user_id=user.id, request=request, before=before,
                 after={"agent": agent, "model": model, "sandbox": sandbox, "harness": harness,
                        "timeout": user.pref_timeout_s})
    flash(request, "设置已保存", "success")
    return RedirectResponse("/settings", status_code=303)


@router.post("/settings/password", dependencies=[Depends(verify_csrf)])
def settings_password(request: Request, current: str = Form(...), new: str = Form(...),
                      user: User = Depends(require_user), db: Session = Depends(get_db)):
    if not verify_password(current, user.password_hash):
        flash(request, "当前密码不正确", "error")
    elif len(new) < 8:
        flash(request, "新密码至少 8 位", "error")
    else:
        user.password_hash = hash_password(new)
        audit.record(db, "auth.password_change", actor=f"user:{user.id}", request=request)
        login_session(request, user)
        flash(request, "密码已修改，其他设备上的登录已失效", "success")
    return RedirectResponse("/settings", status_code=303)


@router.get("/audit")
def audit_page(request: Request, page: int = 1, user: User = Depends(require_user), db: Session = Depends(get_db)):
    page, offset = _page(page)
    query = select(AuditLog).where(AuditLog.user_id == user.id)
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    rows = db.scalars(query.order_by(AuditLog.ts.desc()).offset(offset).limit(PAGE_SIZE)).all()
    return render(request, "audit.html", user, rows=rows, page=page, pages=max(1, -(-total // PAGE_SIZE)),
                  base_url="/audit")
