from __future__ import annotations

import hmac
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import Depends, HTTPException, Request
from fastapi.templating import Jinja2Templates
from markdown_it import MarkdownIt
from markupsafe import Markup
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import new_session
from ..models import ApiKey, User, utcnow
from ..security import hash_api_key, new_csrf_token

TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
_md = MarkdownIt("commonmark", {"html": False, "linkify": False}).enable("table")


class LoginRequired(Exception):
    pass


def get_db() -> Iterator[Session]:
    session = new_session()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


# --------------------------------------------------------------------------- sessions
def session_stamp(user: User) -> str:
    # Changing the password (or disabling the account) invalidates existing sessions.
    return user.password_hash[-16:] + ("1" if user.is_active else "0")


def login_session(request: Request, user: User) -> None:
    request.session.clear()
    request.session["uid"] = user.id
    request.session["stamp"] = session_stamp(user)
    request.session["csrf"] = new_csrf_token()


def current_user(request: Request, db: Session = Depends(get_db)) -> User | None:
    uid = request.session.get("uid")
    if not uid:
        return None
    user = db.get(User, uid)
    if user is None or not user.is_active or request.session.get("stamp") != session_stamp(user):
        request.session.clear()
        return None
    return user


def require_user(user: User | None = Depends(current_user)) -> User:
    if user is None:
        raise LoginRequired()
    return user


def require_admin(user: User = Depends(require_user)) -> User:
    if not user.is_admin:
        raise HTTPException(403, "需要管理员权限")
    return user


def csrf_token(request: Request) -> str:
    token = request.session.get("csrf")
    if not token:
        token = request.session["csrf"] = new_csrf_token()
    return token


async def verify_csrf(request: Request) -> None:
    expected = request.session.get("csrf") or ""
    supplied = request.headers.get("x-csrf-token")
    if not supplied:
        form = await request.form()
        supplied = str(form.get("csrf") or "")
    if not expected or not hmac.compare_digest(expected, supplied):
        raise HTTPException(403, "CSRF 校验失败，请刷新页面后重试")


def flash(request: Request, message: str, level: str = "info") -> None:
    request.session.setdefault("flash", []).append({"msg": message, "level": level})


def pop_flashes(request: Request) -> list[dict[str, str]]:
    return request.session.pop("flash", [])


# --------------------------------------------------------------------------- API keys
def api_principal(request: Request, db: Session = Depends(get_db)) -> tuple[User, ApiKey]:
    auth = request.headers.get("authorization", "")
    key = auth[7:].strip() if auth.lower().startswith("bearer ") else request.headers.get("x-api-key", "").strip()
    if not key:
        raise HTTPException(401, "missing API key (Authorization: Bearer <key>)")
    api_key = db.query(ApiKey).filter_by(key_hash=hash_api_key(key)).one_or_none()
    if api_key is None or api_key.revoked_at is not None:
        raise HTTPException(401, "invalid or revoked API key")
    user = db.get(User, api_key.user_id)
    if user is None or not user.is_active:
        raise HTTPException(403, "account disabled")
    api_key.last_used_at = utcnow()
    forwarded = request.headers.get("x-forwarded-for")
    api_key.last_used_ip = (forwarded.split(",")[0].strip() if forwarded else (request.client.host if request.client else None))
    return user, api_key


# --------------------------------------------------------------------------- template helpers
def fmt_usd(quota: int | float | None) -> str:
    return f"${get_settings().quota_to_usd(quota):,.4f}"


def fmt_int(value: int | float | None) -> str:
    return f"{int(value or 0):,}"


def fmt_dt(value: datetime | int | float | None) -> str:
    if value is None or value == 0:
        return "-"
    if isinstance(value, (int, float)):
        value = datetime.fromtimestamp(value, tz=timezone.utc)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone().strftime("%Y-%m-%d %H:%M:%S")


def fmt_duration(seconds: float | None) -> str:
    if seconds is None:
        return "-"
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}h{m:02d}m{s:02d}s" if h else (f"{m}m{s:02d}s" if m else f"{s}s")


def fmt_bytes(n: int | float | None) -> str:
    n = float(n or 0)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"


def render_markdown(text: str | None) -> Markup:
    return Markup(_md.render(text or ""))


STATUS_LABELS = {
    "queued": "排队中",
    "preparing": "准备中",
    "running": "运行中",
    "succeeded": "成功",
    "failed": "失败",
    "cancelled": "已取消",
    "timeout": "超时",
}

templates.env.globals.update(
    fmt_usd=fmt_usd,
    fmt_int=fmt_int,
    fmt_dt=fmt_dt,
    fmt_duration=fmt_duration,
    fmt_bytes=fmt_bytes,
    markdown=render_markdown,
    status_label=lambda s: STATUS_LABELS.get(s, s),
)


def render(request: Request, template: str, user: User | None = None, status_code: int = 200, **ctx: Any):
    s = get_settings()
    ctx.update(
        request=request,
        user=user,
        csrf=csrf_token(request),
        flashes=pop_flashes(request),
        settings=s,
    )
    return templates.TemplateResponse(request, template, ctx, status_code=status_code)
