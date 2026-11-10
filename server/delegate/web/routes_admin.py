"""Administration: users and their mirror accounts, balances, all tasks, global audit, system health."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from .. import audit, billing, sandbox
from ..config import get_settings
from ..models import AuditLog, LedgerEntry, RedeemCode, Task, TaskStatus, User
from .deps import flash, get_db, render, require_admin, verify_csrf

router = APIRouter(prefix="/admin")
PAGE_SIZE = 50


@router.get("")
def admin_home(request: Request, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    newapi_ok, newapi_msg = billing.health()
    docker_ok, docker_msg = sandbox.ping()
    counts = dict(db.execute(select(Task.status, func.count()).group_by(Task.status)).all())
    return render(
        request,
        "admin/index.html",
        user,
        newapi_ok=newapi_ok,
        newapi_msg=newapi_msg,
        docker_ok=docker_ok,
        docker_msg=docker_msg,
        counts=counts,
        users=db.scalar(select(func.count()).select_from(User)),
        billed_total=db.scalar(select(func.coalesce(func.sum(Task.billed_quota), 0))),
        unmirrored=db.scalar(select(func.count()).select_from(User).where(User.newapi_user_id.is_(None))),
    )


@router.post("/sync-mirrors", dependencies=[Depends(verify_csrf)])
def sync_mirrors(request: Request, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    created, failed = 0, []
    for target in db.scalars(select(User).where(User.newapi_user_id.is_(None))).all():
        try:
            billing.ensure_mirror(db, target)
            created += 1
        except billing.BillingError as exc:
            failed.append(f"{target.email}: {exc}")
    audit.record(db, "admin.sync_mirrors", actor=f"admin:{user.id}", request=request, created=created, failed=failed)
    flash(request, f"已创建 {created} 个镜像账户" + (f"，失败 {len(failed)} 个：{'; '.join(failed)}" if failed else ""),
          "error" if failed else "success")
    return RedirectResponse("/admin", status_code=303)


@router.get("/users")
def users(request: Request, q: str = "", user: User = Depends(require_admin), db: Session = Depends(get_db)):
    query = select(User)
    if q:
        query = query.where(or_(User.email.ilike(f"%{q}%"), User.display_name.ilike(f"%{q}%")))
    rows = db.scalars(query.order_by(User.id.desc()).limit(200)).all()
    stats = dict(
        (uid, (n, spent))
        for uid, n, spent in db.execute(
            select(Task.user_id, func.count(), func.coalesce(func.sum(Task.billed_quota), 0)).group_by(Task.user_id)
        ).all()
    )
    return render(request, "admin/users.html", user, rows=rows, stats=stats, q=q)


def _target(db: Session, user_id: int) -> User:
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(404, "用户不存在")
    return target


@router.get("/users/{user_id}")
def user_detail(request: Request, user_id: int, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    target = _target(db, user_id)
    mirror = None
    try:
        mirror = billing.mirror_info(target)
    except billing.BillingError as exc:
        flash(request, f"读取镜像账户失败：{exc}", "error")
    return render(
        request,
        "admin/user.html",
        user,
        target=target,
        mirror=mirror,
        tasks=db.scalars(select(Task).where(Task.user_id == target.id).order_by(Task.created_at.desc()).limit(20)).all(),
        ledger=db.scalars(
            select(LedgerEntry).where(LedgerEntry.user_id == target.id).order_by(LedgerEntry.ts.desc()).limit(50)
        ).all(),
        trail=db.scalars(
            select(AuditLog).where(AuditLog.user_id == target.id).order_by(AuditLog.ts.desc()).limit(50)
        ).all(),
    )


@router.post("/users/{user_id}/adjust", dependencies=[Depends(verify_csrf)])
def user_adjust(
    request: Request,
    user_id: int,
    amount_usd: float = Form(...),
    direction: str = Form("add"),
    note: str = Form(""),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    target = _target(db, user_id)
    if amount_usd <= 0:
        flash(request, "金额必须大于 0", "error")
    else:
        quota = get_settings().usd_to_quota(amount_usd) * (-1 if direction == "subtract" else 1)
        try:
            billing.adjust(db, target, quota, kind="admin_grant" if quota > 0 else "admin_deduct",
                           actor=f"admin:{user.id}", note=note.strip()[:500], request=request)
            signed_usd = amount_usd if quota > 0 else -amount_usd
            points = billing.grant_recharge_points(
                db, target, signed_usd, kind="admin_grant" if quota > 0 else "admin_deduct",
                actor=f"admin:{user.id}", note=note.strip()[:500], request=request,
            )
            verb = "扣减" if quota < 0 else "充值"
            flash(request, f"已为 {target.email} {verb} {amount_usd:.2f} USD，沙箱积分现为 {points}", "success")
        except billing.BillingError as exc:
            flash(request, f"操作失败：{exc}", "error")
    return RedirectResponse(f"/admin/users/{user_id}", status_code=303)


@router.post("/users/{user_id}/toggle", dependencies=[Depends(verify_csrf)])
def user_toggle(request: Request, user_id: int, field: str = Form(...), user: User = Depends(require_admin),
                db: Session = Depends(get_db)):
    target = _target(db, user_id)
    if target.id == user.id:
        flash(request, "不能修改自己的状态", "error")
        return RedirectResponse(f"/admin/users/{user_id}", status_code=303)
    if field == "active":
        target.is_active = not target.is_active
        try:
            billing.set_mirror_enabled(target, target.is_active)
        except billing.BillingError as exc:
            flash(request, f"同步网关账户状态失败：{exc}", "error")
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


@router.post("/codes", dependencies=[Depends(verify_csrf)])
def create_codes(
    request: Request,
    amount_usd: float = Form(...),
    count: int = Form(1),
    valid_days: int = Form(0),
    note: str = Form(""),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    count = max(1, min(count, 100))
    try:
        codes = billing.create_codes(db, get_settings().usd_to_quota(amount_usd), count, actor=f"admin:{user.id}",
                                     note=note.strip()[:200], valid_days=valid_days or None)
    except billing.BillingError as exc:
        flash(request, f"生成失败：{exc}", "error")
        return RedirectResponse("/admin", status_code=303)
    audit.record(db, "admin.codes_create", actor=f"admin:{user.id}", request=request,
                 amount_usd=amount_usd, count=count, valid_days=valid_days, note=note)
    request.session["codes"] = codes  # shown exactly once
    return RedirectResponse("/admin/codes", status_code=303)


@router.get("/codes")
def show_codes(request: Request, user: User = Depends(require_admin), db: Session = Depends(get_db)):
    rows = db.scalars(select(RedeemCode).order_by(RedeemCode.id.desc()).limit(200)).all()
    redeemers = {u.id: u for u in db.scalars(select(User).where(User.id.in_({r.redeemed_by for r in rows if r.redeemed_by})))}
    return render(request, "admin/codes.html", user, codes=request.session.pop("codes", []), rows=rows,
                  redeemers=redeemers)


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
