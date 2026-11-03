"""Administration: model providers, users, all tasks, global audit and system health."""

from __future__ import annotations

from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from .. import audit, providers, sandbox
from ..config import get_settings
from ..models import AuditLog, ProviderConfig, Task, TaskStatus, User
from ..security import encrypt
from .deps import flash, get_db, render, require_admin, verify_csrf

router = APIRouter(prefix="/admin")
PAGE_SIZE = 50


@router.get("")
def admin_home(request: Request, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    docker_ok, docker_msg = sandbox.ping()
    counts = dict(db.execute(select(Task.status, func.count()).group_by(Task.status)).all())
    configured = db.scalar(select(func.count()).select_from(ProviderConfig).where(ProviderConfig.api_key_enc.is_not(None)))
    env_configured = sum(bool(get_settings().provider_api_key(p)) for p in providers.SUPPORTED_PROVIDERS)
    return render(request, "admin/index.html", user, docker_ok=docker_ok, docker_msg=docker_msg,
                  counts=counts, users=db.scalar(select(func.count()).select_from(User)),
                  configured_providers=(configured or 0) + env_configured)


@router.get("/providers")
def provider_page(request: Request, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    settings = get_settings()
    rows = []
    for name in providers.SUPPORTED_PROVIDERS:
        config = db.get(ProviderConfig, name)
        rows.append({
            "name": name,
            "config": config,
            "configured": bool(config and config.api_key_enc) or bool(settings.provider_api_key(name)),
            "key_source": "后台" if config and config.api_key_enc else ("环境变量" if settings.provider_api_key(name) else "未配置"),
            "base_url": (config.base_url if config else "") or settings.provider_base_url(name) or "官方默认地址",
        })
    return render(request, "admin/providers.html", user, rows=rows)


@router.post("/providers/{provider}", dependencies=[Depends(verify_csrf)])
def provider_save(
    request: Request, provider: str, base_url: str = Form(""), api_key: str = Form(""),
    clear_api_key: str | None = Form(None), enabled: str | None = Form(None),
    user: User = Depends(require_admin), db: Session = Depends(get_db),
):
    if provider not in providers.SUPPORTED_PROVIDERS:
        raise HTTPException(404)
    base_url = base_url.strip().rstrip("/")
    if base_url and (urlsplit(base_url).scheme not in ("http", "https") or not urlsplit(base_url).hostname):
        flash(request, "Base URL 必须是有效的 http(s) 地址", "error")
        return RedirectResponse("/admin/providers", status_code=303)
    config = db.get(ProviderConfig, provider) or ProviderConfig(provider=provider)
    config.base_url = base_url
    config.enabled = enabled == "on"
    if clear_api_key:
        config.api_key_enc = None
    elif api_key.strip():
        config.api_key_enc = encrypt(api_key.strip())
    db.add(config)
    audit.record(db, "admin.provider_update", actor=f"admin:{user.id}", request=request,
                 provider=provider, base_url=base_url, enabled=config.enabled,
                 api_key_updated=bool(api_key.strip()), api_key_cleared=bool(clear_api_key))
    flash(request, f"{provider} 配置已保存", "success")
    return RedirectResponse("/admin/providers", status_code=303)


@router.get("/users")
def users(request: Request, q: str = "", user: User = Depends(require_admin), db: Session = Depends(get_db)):
    query = select(User)
    if q:
        query = query.where(or_(User.email.ilike(f"%{q}%"), User.display_name.ilike(f"%{q}%")))
    rows = db.scalars(query.order_by(User.id.desc()).limit(200)).all()
    stats = dict(db.execute(select(Task.user_id, func.count()).group_by(Task.user_id)).all())
    return render(request, "admin/users.html", user, rows=rows, stats=stats, q=q)


def _target(db: Session, user_id: int) -> User:
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(404, "用户不存在")
    return target


@router.get("/users/{user_id}")
def user_detail(request: Request, user_id: int, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    target = _target(db, user_id)
    return render(request, "admin/user.html", user, target=target,
                  tasks=db.scalars(select(Task).where(Task.user_id == target.id).order_by(Task.created_at.desc()).limit(20)).all(),
                  trail=db.scalars(select(AuditLog).where(AuditLog.user_id == target.id).order_by(AuditLog.ts.desc()).limit(50)).all())


@router.post("/users/{user_id}/toggle", dependencies=[Depends(verify_csrf)])
def user_toggle(request: Request, user_id: int, field: str = Form(...), user: User = Depends(require_admin),
                db: Session = Depends(get_db)):
    target = _target(db, user_id)
    if target.id == user.id:
        flash(request, "不能修改自己的状态", "error")
        return RedirectResponse(f"/admin/users/{user_id}", status_code=303)
    if field == "active":
        target.is_active = not target.is_active
        if not target.is_active:
            for task in db.scalars(select(Task).where(Task.user_id == target.id, Task.status.in_(TaskStatus.ACTIVE))):
                task.cancel_requested = True
                if task.status == TaskStatus.QUEUED:
                    task.status, task.status_reason = TaskStatus.CANCELLED, "account disabled"
    elif field == "admin":
        target.is_admin = not target.is_admin
    else:
        raise HTTPException(400)
    audit.record(db, f"admin.user_{field}", actor=f"admin:{user.id}", user_id=target.id, request=request,
                 active=target.is_active, admin=target.is_admin)
    flash(request, "已更新", "success")
    return RedirectResponse(f"/admin/users/{user_id}", status_code=303)


@router.get("/tasks")
def all_tasks(request: Request, status: str = "", page: int = 1, user: User = Depends(require_admin),
              db: Session = Depends(get_db)):
    page = max(1, page)
    query = select(Task)
    if status:
        query = query.where(Task.status == status)
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    rows = db.scalars(query.order_by(Task.created_at.desc()).offset((page - 1) * PAGE_SIZE).limit(PAGE_SIZE)).all()
    owners = {u.id: u for u in db.scalars(select(User).where(User.id.in_({t.user_id for t in rows})))}
    return render(request, "admin/tasks.html", user, rows=rows, owners=owners, status=status, page=page,
                  pages=max(1, -(-total // PAGE_SIZE)))


@router.get("/audit")
def global_audit(request: Request, page: int = 1, action: str = "", user: User = Depends(require_admin),
                 db: Session = Depends(get_db)):
    page = max(1, page)
    query = select(AuditLog)
    if action:
        query = query.where(AuditLog.action.like(f"{action}%"))
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    rows = db.scalars(query.order_by(AuditLog.ts.desc()).offset((page - 1) * PAGE_SIZE).limit(PAGE_SIZE)).all()
    return render(request, "audit.html", user, rows=rows, page=page, pages=max(1, -(-total // PAGE_SIZE)),
                  base_url="/admin/audit", admin_view=True, action=action)
