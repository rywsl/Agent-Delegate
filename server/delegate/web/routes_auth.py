from __future__ import annotations

import logging
import re

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import audit, billing
from ..config import get_settings
from ..models import User, utcnow
from ..security import hash_password, verify_password
from .deps import current_user, flash, get_db, login_session, render, verify_csrf

log = logging.getLogger(__name__)
router = APIRouter()
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@router.get("/")
def index(user: User | None = Depends(current_user)):
    return RedirectResponse("/dashboard" if user else "/login", status_code=303)


@router.get("/login")
def login_page(request: Request, user: User | None = Depends(current_user)):
    if user:
        return RedirectResponse("/dashboard", status_code=303)
    return render(request, "login.html")


@router.post("/login", dependencies=[Depends(verify_csrf)])
def login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    user = db.scalar(select(User).where(func.lower(User.email) == email.strip().lower()))
    if user is None or not verify_password(password, user.password_hash):
        audit.record(db, "auth.login_failed", actor="anonymous", user_id=user.id if user else None,
                     request=request, email=email.strip()[:200])
        return render(request, "login.html", error="邮箱或密码错误", email=email, status_code=401)
    if not user.is_active:
        return render(request, "login.html", error="账户已被停用", email=email, status_code=403)
    user.last_login_at = utcnow()
    login_session(request, user)
    audit.record(db, "auth.login", actor=f"user:{user.id}", user_id=user.id, request=request)
    return RedirectResponse("/dashboard", status_code=303)


@router.post("/logout", dependencies=[Depends(verify_csrf)])
def logout(request: Request, user: User | None = Depends(current_user), db: Session = Depends(get_db)):
    if user:
        audit.record(db, "auth.logout", actor=f"user:{user.id}", user_id=user.id, request=request)
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


@router.get("/register")
def register_page(request: Request):
    if not get_settings().allow_registration:
        return render(request, "login.html", error="当前未开放注册")
    return render(request, "register.html")


@router.post("/register", dependencies=[Depends(verify_csrf)])
def register(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    display_name: str = Form(""),
    db: Session = Depends(get_db),
):
    s = get_settings()
    if not s.allow_registration:
        return render(request, "login.html", error="当前未开放注册", status_code=403)
    email = email.strip().lower()
    error = None
    if not EMAIL_RE.match(email):
        error = "邮箱格式不正确"
    elif len(password) < 8:
        error = "密码至少 8 位"
    elif db.scalar(select(User).where(func.lower(User.email) == email)):
        error = "该邮箱已注册"
    if error:
        return render(request, "register.html", error=error, email=email, display_name=display_name, status_code=400)

    first_user = db.scalar(select(func.count()).select_from(User)) == 0
    user = User(
        email=email,
        display_name=display_name.strip()[:100] or email.split("@")[0],
        password_hash=hash_password(password),
        is_admin=first_user,  # the very first account administers the site
    )
    db.add(user)
    db.flush()
    audit.record(db, "auth.register", actor=f"user:{user.id}", user_id=user.id, request=request, admin=first_user)
    db.commit()

    # Create the mirror account in new-api right away; if the sidecar is down it is retried lazily.
    try:
        billing.ensure_mirror(db, user)
        if s.signup_credit_usd > 0:
            billing.adjust(db, user, s.usd_to_quota(s.signup_credit_usd), kind="signup_credit", actor="system",
                          note="注册赠送")
        db.commit()
    except billing.BillingError as exc:
        db.rollback()
        log.warning("mirror account for %s not created yet: %s", user.email, exc)

    login_session(request, user)
    flash(request, "注册成功" + ("，你是第一个用户，已获得管理员权限" if first_user else ""), "success")
    return RedirectResponse("/dashboard", status_code=303)
