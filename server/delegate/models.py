from __future__ import annotations

import secrets
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_task_id() -> str:
    return "t_" + secrets.token_hex(8)


class TaskStatus:
    QUEUED = "queued"
    PREPARING = "preparing"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"

    ACTIVE = (QUEUED, PREPARING, RUNNING)
    TERMINAL = (SUCCEEDED, FAILED, CANCELLED, TIMEOUT)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(100), default="")
    password_hash: Mapped[str] = mapped_column(String(255))
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Mirror account in the new-api sidecar. The user never sees it; the site holds its scoped PAT.
    # The mirror password is derived from the site secret (see billing.mirror_password).
    newapi_user_id: Mapped[int | None] = mapped_column(Integer, unique=True)
    newapi_username: Mapped[str | None] = mapped_column(String(32), unique=True)
    newapi_pat_enc: Mapped[str | None] = mapped_column(Text)
    newapi_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Task defaults chosen on the web site (the local agent cannot override them).
    pref_agent: Mapped[str | None] = mapped_column(String(32))
    pref_model: Mapped[str | None] = mapped_column(String(100))
    pref_budget_usd: Mapped[float | None]
    pref_timeout_s: Mapped[int | None]

    api_keys: Mapped[list[ApiKey]] = relationship(back_populates="user")


class ApiKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    prefix: Mapped[str] = mapped_column(String(20))
    key_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_used_ip: Mapped[str | None] = mapped_column(String(64))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship(back_populates="api_keys")

    @property
    def active(self) -> bool:
        return self.revoked_at is None


class Task(Base):
    __tablename__ = "tasks"
    __table_args__ = (Index("ix_tasks_user_created", "user_id", "created_at"), Index("ix_tasks_status", "status"))

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_task_id)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    api_key_id: Mapped[int | None] = mapped_column(ForeignKey("api_keys.id"))
    source: Mapped[str] = mapped_column(String(16), default="mcp")  # mcp | api | web
    client_info: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    title: Mapped[str] = mapped_column(String(200))
    prompt: Mapped[str] = mapped_column(Text)
    repo_url: Mapped[str | None] = mapped_column(String(1000))  # credentials stripped, safe to display
    repo_url_enc: Mapped[str | None] = mapped_column(Text)  # full clone URL (may embed a token), encrypted
    repo_ref: Mapped[str | None] = mapped_column(String(200))
    attachments: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)  # inline files [{path,size,sha256}]
    uploads: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)  # [{id,dest,kind,size,sha256}]
    outputs: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)  # files from /outputs [{path,size}]

    agent: Mapped[str] = mapped_column(String(32))
    model: Mapped[str] = mapped_column(String(100))
    budget_quota: Mapped[int] = mapped_column(Integer)
    timeout_s: Mapped[int] = mapped_column(Integer)
    max_turns: Mapped[int] = mapped_column(Integer)

    status: Mapped[str] = mapped_column(String(16), default=TaskStatus.QUEUED)
    status_reason: Mapped[str | None] = mapped_column(Text)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    worker_id: Mapped[str | None] = mapped_column(String(64))

    container_id: Mapped[str | None] = mapped_column(String(80))
    container_name: Mapped[str | None] = mapped_column(String(100))
    sandbox_image: Mapped[str | None] = mapped_column(String(200))
    sandbox_limits: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    exit_code: Mapped[int | None] = mapped_column(Integer)

    result_text: Mapped[str | None] = mapped_column(Text)
    patch_stats: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)  # {files, insertions, deletions, bytes}
    agent_usage: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)  # usage as reported by the agent CLI
    event_count: Mapped[int] = mapped_column(Integer, default=0)

    # Billing, authoritative numbers come from new-api logs of the per-task token.
    newapi_token_id: Mapped[int | None] = mapped_column(Integer)
    newapi_token_name: Mapped[str | None] = mapped_column(String(64))
    billed_quota: Mapped[int] = mapped_column(Integer, default=0)
    billed_prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    billed_completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    billed_requests: Mapped[int] = mapped_column(Integer, default=0)
    billing_reconciled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship()

    @property
    def is_active(self) -> bool:
        return self.status in TaskStatus.ACTIVE

    @property
    def duration_s(self) -> float | None:
        if not self.started_at:
            return None
        end = self.finished_at or utcnow()
        start = self.started_at
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        if end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)
        return (end - start).total_seconds()


class UploadStatus:
    PENDING = "pending"  # slot created, waiting for the bytes
    RECEIVING = "receiving"
    READY = "ready"
    FAILED = "failed"
    EXPIRED = "expired"


class Upload(Base):
    """A file or archive pushed by the delegating side through a one-time upload URL."""

    __tablename__ = "uploads"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    api_key_id: Mapped[int | None] = mapped_column(ForeignKey("api_keys.id"))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    dest: Mapped[str] = mapped_column(String(500), default=".")
    status: Mapped[str] = mapped_column(String(16), default=UploadStatus.PENDING)
    kind: Mapped[str | None] = mapped_column(String(16))  # tar | tgz | zip | file
    size: Mapped[int] = mapped_column(Integer, default=0)
    sha256: Mapped[str | None] = mapped_column(String(64))
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    uploaded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class TaskEvent(Base):
    __tablename__ = "task_events"
    __table_args__ = (UniqueConstraint("task_id", "seq"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    kind: Mapped[str] = mapped_column(String(32))
    summary: Mapped[str] = mapped_column(Text, default="")
    data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    __table_args__ = (Index("ix_audit_user_ts", "user_id", "ts"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))  # whose account this concerns
    actor: Mapped[str] = mapped_column(String(100))  # "user:3", "admin:1", "apikey:7", "system"
    action: Mapped[str] = mapped_column(String(64))
    target: Mapped[str | None] = mapped_column(String(100))
    ip: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(300))
    detail: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class LedgerEntry(Base):
    """Balance changes initiated by the web site (top-ups, grants). Usage is read from new-api."""

    __tablename__ = "ledger"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    kind: Mapped[str] = mapped_column(String(32))  # signup_credit | admin_grant | redeem_code
    quota_delta: Mapped[int] = mapped_column(Integer)
    actor: Mapped[str] = mapped_column(String(100))
    note: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending | applied | failed
    error: Mapped[str | None] = mapped_column(Text)


class RedeemCode(Base):
    """Top-up codes issued by the site (applied to new-api with an atomic add_quota)."""

    __tablename__ = "redeem_codes"

    id: Mapped[int] = mapped_column(primary_key=True)
    code_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    hint: Mapped[str] = mapped_column(String(16))
    quota: Mapped[int] = mapped_column(Integer)
    note: Mapped[str] = mapped_column(String(200), default="")
    created_by: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    redeemed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    redeemed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
