"""Task submission, lookup and the deliberately small view exposed to delegating agents."""

from __future__ import annotations

import base64
import binascii
import hashlib
import posixpath
import tarfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import audit, transfer
from . import billing
from .config import get_settings
from .models import Task, TaskStatus, Upload, UploadStatus, User, new_task_id, utcnow
from .site import ensure_free_seconds, offered_models, points_per_usd, queue_limits
from .security import encrypt

MAX_PROMPT_CHARS = 100_000
MAX_FILES = 200
MAX_UPLOADS = 20
MAX_LISTED_OUTPUTS = 200

SYSTEM_PROMPT = """\
You are a cloud agent executing a task that was delegated to you by another agent.

Operating rules:
- You run fully autonomously inside an isolated sandbox. Nobody can answer questions during the run:
  never ask for clarification or confirmation; make reasonable assumptions and state them in your report.
- Your working directory is /workspace (a git repository holding the inputs you were given). Every change
  you leave in /workspace is returned to the delegating agent as a patch, so do not leave scratch files there.
- Deliverables that are not part of the workspace (reports, generated data, build artifacts, binaries)
  go into /outputs; every file in /outputs is returned to the delegating agent as a downloadable file.
- Work until the task is complete or you are certain it cannot be completed.
- Never print, store or transmit credentials or environment variables.
- Finish with a concise final report (plain text/markdown): what you did, the outcome, files changed or
  produced, how you verified it, assumptions, and anything left undone. This report, the patch and the
  files in /outputs are the only things the delegating agent receives."""


class TaskInputError(ValueError):
    pass


class QueueFull(TaskInputError):
    """The queue is deep enough that accepting another task would crowd out everyone else."""


@dataclass
class TaskInput:
    task: str
    title: str | None = None
    repo_url: str | None = None
    repo_ref: str | None = None
    files: list[dict[str, Any]] | None = None
    upload_ids: list[str] = field(default_factory=list)


def task_dir(task_id: str) -> Path:
    return get_settings().artifacts_dir / task_id


def patch_path(task_id: str) -> Path:
    return task_dir(task_id) / "changes.patch"


def outputs_path(task_id: str) -> Path:
    return task_dir(task_id) / "outputs.tar.gz"


def raw_log_path(task_id: str) -> Path:
    return task_dir(task_id) / "events.log"


def normalise_path(raw: str) -> str:
    path = (raw or "").replace("\\", "/").strip()
    norm = posixpath.normpath(path)
    if not path or norm in (".", "") or norm.startswith("../") or norm == ".." or posixpath.isabs(norm):
        raise TaskInputError(f"invalid path: {raw!r} (must be relative to the workspace)")
    if norm.split("/")[0] == ".git":
        raise TaskInputError(f"invalid path: {raw!r}")
    return norm


def _decode_files(files: list[dict[str, Any]] | None) -> dict[str, bytes]:
    if not files:
        return {}
    if len(files) > MAX_FILES:
        raise TaskInputError(f"too many inline files (max {MAX_FILES}); upload an archive instead")
    out: dict[str, bytes] = {}
    total = 0
    for item in files:
        path = normalise_path(str(item.get("path", "")))
        content = item.get("content", "")
        if not isinstance(content, str):
            raise TaskInputError(f"file {path}: content must be a string")
        if item.get("encoding") == "base64":
            try:
                data = base64.b64decode(content, validate=True)
            except (binascii.Error, ValueError) as exc:
                raise TaskInputError(f"file {path}: invalid base64") from exc
        else:
            data = content.encode("utf-8")
        total += len(data)
        out[path] = data
    limit = get_settings().max_attachment_bytes
    if total > limit:
        raise TaskInputError(f"inline files exceed {limit} bytes in total; use create_upload for larger inputs")
    return out


def _resolve_uploads(session: Session, user: User, upload_ids: list[str]) -> list[Upload]:
    if len(upload_ids) > MAX_UPLOADS:
        raise TaskInputError(f"too many uploads (max {MAX_UPLOADS})")
    uploads = []
    now = utcnow()
    for upload_id in dict.fromkeys(upload_ids):
        upload = session.get(Upload, upload_id)
        if upload is None or upload.user_id != user.id:
            raise TaskInputError(f"unknown upload {upload_id}")
        expires = upload.expires_at if upload.expires_at.tzinfo else upload.expires_at.replace(tzinfo=now.tzinfo)
        if upload.status != UploadStatus.READY or expires < now:
            state = "expired" if expires < now else upload.status
            raise TaskInputError(f"upload {upload_id} is not usable ({state}); upload the data first")
        uploads.append(upload)
    return uploads


def _split_repo_url(url: str | None) -> tuple[str | None, str | None]:
    """Return (display URL without credentials, full URL)."""
    if not url:
        return None, None
    url = url.strip()
    parts = urlsplit(url)
    if parts.scheme not in ("https", "http") or not parts.hostname:
        raise TaskInputError("repo_url must be an http(s) git URL")
    host = parts.hostname + (f":{parts.port}" if parts.port else "")
    display = urlunsplit((parts.scheme, host, parts.path, parts.query, ""))
    return display, url


def resolve_options(user: User, db: Session | None = None) -> dict[str, Any]:
    """Execution options come from the user's settings on the web site, never from the caller."""
    s = get_settings()
    agent = user.pref_agent if user.pref_agent in s.agents else s.default_agent
    models = offered_models(db, agent) if db is not None else s.models_for(agent)
    model = user.pref_model if user.pref_model in models else models[0]
    budget = min(user.pref_budget_usd or s.default_budget_usd, s.max_budget_usd)
    timeout = min(user.pref_timeout_s or s.default_timeout_s, s.max_timeout_s)
    return {
        "agent": agent,
        "model": model,
        "budget_quota": s.usd_to_quota(budget),
        "timeout_s": int(timeout),
        "max_turns": s.default_max_turns,
    }


def enforce_queue(db: Session, user: User) -> None:
    global_max, per_user = queue_limits(db)
    queued = Task.status == TaskStatus.QUEUED
    total = int(db.scalar(select(func.count()).select_from(Task).where(queued)) or 0)
    if total >= global_max:
        raise QueueFull(f"the task queue is full ({global_max}); try again once a task starts")
    mine = int(db.scalar(select(func.count()).select_from(Task).where(queued, Task.user_id == user.id)) or 0)
    if mine >= per_user:
        raise QueueFull(f"you already have {per_user} task(s) waiting; wait for one to start")


def create_task(
    session: Session,
    user: User,
    data: TaskInput,
    *,
    source: str,
    api_key_id: int | None = None,
    client_info: dict[str, Any] | None = None,
    request: Any = None,
) -> Task:
    prompt = (data.task or "").strip()
    if not prompt:
        raise TaskInputError("task must not be empty")
    if len(prompt) > MAX_PROMPT_CHARS:
        raise TaskInputError(f"task is too long (max {MAX_PROMPT_CHARS} characters)")
    files = _decode_files(data.files)
    uploads = _resolve_uploads(session, user, data.upload_ids or [])
    repo_display, repo_full = _split_repo_url(data.repo_url)
    title = (data.title or prompt.splitlines()[0]).strip()[:120] or "untitled"

    task_id = new_task_id()
    tdir = task_dir(task_id)
    for rel, content in files.items():
        dest = tdir / "files" / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(content)
    upload_meta = [transfer.attach_to_task(upload, tdir) for upload in uploads]

    options = resolve_options(user, session)
    mode = billing.assert_can_submit(session, user, options["agent"])
    if mode == "byok":
        affordable = billing.affordable_sandbox_seconds(session, user)
        options["timeout_s"] = max(60, min(options["timeout_s"], affordable))
    ensure_free_seconds(session, user)
    enforce_queue(session, user)
    task = Task(
        id=task_id,
        user_id=user.id,
        api_key_id=api_key_id,
        source=source,
        client_info=client_info or {},
        title=title,
        prompt=prompt,
        repo_url=repo_display,
        repo_url_enc=encrypt(repo_full) if repo_full and repo_full != repo_display else None,
        repo_ref=(data.repo_ref or "").strip() or None,
        attachments=[
            {"path": rel, "size": len(content), "sha256": hashlib.sha256(content).hexdigest()}
            for rel, content in files.items()
        ],
        uploads=upload_meta,
        status=TaskStatus.QUEUED,
        billing_mode=mode,
        **options,
    )
    session.add(task)
    actor = f"apikey:{api_key_id}" if api_key_id else f"user:{user.id}"
    audit.record(
        session,
        "task.create",
        actor=actor,
        user_id=user.id,
        target=task_id,
        request=request,
        source=source,
        agent=task.agent,
        model=task.model,
        budget_quota=task.budget_quota,
        billing_mode=task.billing_mode,
        inline_files=len(files),
        uploads=[u["id"] for u in upload_meta],
        repo=repo_display,
    )
    session.flush()
    return task


def get_user_task(session: Session, user: User, task_id: str) -> Task | None:
    task = session.get(Task, task_id)
    if task is None or (task.user_id != user.id and not user.is_admin):
        return None
    return task


def request_cancel(session: Session, task: Task, *, actor: str, request: Any = None) -> bool:
    if task.status not in TaskStatus.ACTIVE:
        return False
    if task.status == TaskStatus.QUEUED:
        task.status = TaskStatus.CANCELLED
        task.status_reason = "cancelled before start"
        task.finished_at = utcnow()
    else:
        task.cancel_requested = True
    audit.record(session, "task.cancel", actor=actor, user_id=task.user_id, target=task.id, request=request)
    return True


def queue_position(session: Session, task: Task) -> int | None:
    if task.status != TaskStatus.QUEUED:
        return None
    ahead = session.scalar(
        select(func.count()).select_from(Task).where(Task.status == TaskStatus.QUEUED, Task.created_at < task.created_at)
    )
    return int(ahead or 0) + 1


def read_output_file(task: Task, rel_path: str) -> bytes | None:
    """Read one regular file from the task's outputs archive (never extracted to disk)."""
    archive = outputs_path(task.id)
    if not archive.exists():
        return None
    with tarfile.open(archive, "r:gz") as tar:
        for member in tar:
            name = member.name[2:] if member.name.startswith("./") else member.name
            if member.isfile() and posixpath.normpath(name) == rel_path:
                fh = tar.extractfile(member)
                return fh.read() if fh else None
    return None


def audit_url(task: Task) -> str:
    return f"{get_settings().public_url}/tasks/{task.id}"


def public_view(session: Session, task: Task, *, include_patch: bool = True) -> dict[str, Any]:
    """What a delegating agent may see: the outcome and its deliverables, no process details."""
    s = get_settings()
    view: dict[str, Any] = {
        "id": task.id,
        "title": task.title,
        "status": task.status,
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "finished_at": task.finished_at.isoformat() if task.finished_at else None,
        "duration_s": round(task.duration_s, 1) if task.duration_s is not None else None,
        "audit_url": audit_url(task),
    }
    if task.status == TaskStatus.QUEUED:
        view["queue_position"] = queue_position(session, task)
    if task.status not in TaskStatus.TERMINAL:
        return view

    view["result"] = task.result_text or ""
    if task.status != TaskStatus.SUCCEEDED:
        view["error"] = task.status_reason or task.status
    stats = task.patch_stats or {}
    patch: dict[str, Any] = {
        "files": stats.get("files", 0),
        "insertions": stats.get("insertions", 0),
        "deletions": stats.get("deletions", 0),
        "paths": (stats.get("paths") or [])[:100],
    }
    path = patch_path(task.id)
    if path.exists() and path.stat().st_size:
        size = path.stat().st_size
        patch["bytes"] = size
        patch["url"] = transfer.download_url(task.id, "patch", f"{task.id}.patch")
        if include_patch and size <= s.max_patch_inline_bytes:
            patch["inline"] = path.read_bytes().decode("utf-8", errors="replace")  # keep CRLFs intact
    view["patch"] = patch

    outputs = task.outputs or []
    if outputs and outputs_path(task.id).exists():
        view["outputs"] = {
            "count": len(outputs),
            "bytes": sum(int(o.get("size", 0)) for o in outputs),
            "bundle_url": transfer.download_url(task.id, "outputs", f"{task.id}-outputs.tar.gz"),
            "files": [
                {
                    "path": o["path"],
                    "size": o.get("size", 0),
                    "url": transfer.download_url(task.id, f"output:{o['path']}", posixpath.basename(o["path"])),
                }
                for o in outputs[:MAX_LISTED_OUTPUTS]
            ],
        }
    model_cost = s.quota_to_usd(task.billed_quota)
    ratio = points_per_usd(session)
    sandbox_points = int(task.sandbox_billed_points or 0)
    if sandbox_points:
        sandbox_cost = sandbox_points / ratio if ratio else 0
    else:
        sandbox_cost = s.quota_to_usd(task.sandbox_billed_quota)
    total = model_cost + sandbox_cost
    view["billing"] = {
        "mode": task.billing_mode or "platform",
        "model_cost_usd": round(model_cost, 4),
        "sandbox_seconds": int(task.sandbox_billed_seconds or 0),
        "sandbox_free_seconds": int(task.sandbox_free_seconds_used or 0),
        "sandbox_points": sandbox_points,
        "points_per_usd": ratio,
        "sandbox_cost_usd": round(sandbox_cost, 4),
        "cost_usd": round(total, 4),
        "total_cost_usd": round(total, 4),
        "tokens": task.billed_prompt_tokens + task.billed_completion_tokens,
        "prompt_tokens": task.billed_prompt_tokens,
        "completion_tokens": task.billed_completion_tokens,
        "final": task.billing_reconciled_at is not None or task.billing_mode == "byok",
    }
    return view
