from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from .models import AuditLog


def client_ip(request: Any) -> str | None:
    if request is None:
        return None
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()[:64]
    return request.client.host if request.client else None


def record(
    session: Session,
    action: str,
    *,
    actor: str,
    user_id: int | None = None,
    target: str | None = None,
    request: Any = None,
    **detail: Any,
) -> AuditLog:
    entry = AuditLog(
        action=action,
        actor=actor,
        user_id=user_id,
        target=target,
        ip=client_ip(request),
        user_agent=(request.headers.get("user-agent") or "")[:300] if request is not None else None,
        detail=detail,
    )
    session.add(entry)
    return entry
