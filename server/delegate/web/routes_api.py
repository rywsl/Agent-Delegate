"""Public REST API (/api/v1), authenticated with per-user API keys. Used by the MCP gateway.

Responses carry outcomes only; the execution trail is visible exclusively on the web site.
"""

from __future__ import annotations

import asyncio
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit, billing, transfer
from ..config import get_settings
from ..db import new_session
from ..models import ApiKey, Task, TaskStatus, Upload, UploadStatus, User, utcnow
from ..tasks import (
    QueueFull,
    TaskInput,
    TaskInputError,
    create_task,
    get_user_task,
    outputs_path,
    patch_path,
    public_view,
    read_output_file,
    request_cancel,
)
from .deps import api_principal, get_db

router = APIRouter(prefix="/api/v1")


class FileIn(BaseModel):
    path: str
    content: str
    encoding: str = "utf-8"


class TaskIn(BaseModel):
    task: str = Field(..., max_length=100_000)
    title: str | None = None
    repo_url: str | None = None
    repo_ref: str | None = None
    files: list[FileIn] = []
    upload_ids: list[str] = []


class UploadIn(BaseModel):
    dest: str = "."


def _actor(api_key: ApiKey) -> str:
    return f"apikey:{api_key.id}"


@router.get("/me")
def me(principal: tuple[User, ApiKey] = Depends(api_principal), db: Session = Depends(get_db)) -> dict[str, Any]:
    user, _ = principal
    from ..site import ensure_free_seconds

    balance = billing.balance_quota(user)
    agent = user.pref_agent if user.pref_agent in get_settings().agents else get_settings().default_agent
    return {
        "email": user.email,
        "balance_usd": round(get_settings().quota_to_usd(balance), 4) if balance is not None else None,
        "sandbox_free_seconds": ensure_free_seconds(db, user),
        "billing_mode": billing.mode_for(db, user, agent),
    }


@router.post("/tasks", status_code=201)
def submit_task(
    body: TaskIn,
    request: Request,
    principal: tuple[User, ApiKey] = Depends(api_principal),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    user, api_key = principal
    client = {
        "ip": audit.client_ip(request),
        "client": request.headers.get("x-delegate-client") or request.headers.get("user-agent"),
    }
    try:
        task = create_task(
            db,
            user,
            TaskInput(
                task=body.task,
                title=body.title,
                repo_url=body.repo_url,
                repo_ref=body.repo_ref,
                files=[f.model_dump() for f in body.files],
                upload_ids=body.upload_ids,
            ),
            source="mcp" if request.headers.get("x-delegate-client") is not None else "api",
            api_key_id=api_key.id,
            client_info=client,
            request=request,
        )
    except QueueFull as exc:
        raise HTTPException(429, str(exc)) from exc
    except TaskInputError as exc:
        raise HTTPException(422, str(exc)) from exc
    return public_view(db, task)


@router.get("/tasks")
def list_tasks(
    limit: int = Query(10, ge=1, le=100),
    principal: tuple[User, ApiKey] = Depends(api_principal),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    user, _ = principal
    rows = db.scalars(select(Task).where(Task.user_id == user.id).order_by(Task.created_at.desc()).limit(limit)).all()
    return {
        "tasks": [
            {"id": t.id, "title": t.title, "status": t.status, "created_at": t.created_at.isoformat()} for t in rows
        ]
    }


def _owned_task(db: Session, user: User, task_id: str) -> Task:
    task = db.get(Task, task_id)
    if task is None or task.user_id != user.id:
        raise HTTPException(404, "task not found")
    return task


@router.get("/tasks/{task_id}")
def get_task(
    task_id: str, principal: tuple[User, ApiKey] = Depends(api_principal), db: Session = Depends(get_db)
) -> dict[str, Any]:
    return public_view(db, _owned_task(db, principal[0], task_id))


@router.get("/tasks/{task_id}/wait")
async def wait_task(
    task_id: str,
    timeout: int = Query(25, ge=0, le=60),
    principal: tuple[User, ApiKey] = Depends(api_principal),
) -> dict[str, Any]:
    """Long-poll until the task reaches a terminal state or ``timeout`` seconds pass."""
    user = principal[0]

    def snapshot() -> tuple[str, dict[str, Any] | None]:
        with new_session() as db:
            task = db.get(Task, task_id)
            if task is None or task.user_id != user.id:
                raise HTTPException(404, "task not found")
            if task.status in TaskStatus.TERMINAL:
                return task.status, public_view(db, task)
            return task.status, None

    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while True:
        status, view = await asyncio.to_thread(snapshot)
        if view is not None:
            return view
        if loop.time() >= deadline:
            break
        await asyncio.sleep(1.0)
    with new_session() as db:
        return public_view(db, db.get(Task, task_id))


@router.post("/tasks/{task_id}/cancel")
def cancel_task(
    task_id: str,
    request: Request,
    principal: tuple[User, ApiKey] = Depends(api_principal),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    user, api_key = principal
    task = _owned_task(db, user, task_id)
    request_cancel(db, task, actor=_actor(api_key), request=request)
    return {"id": task.id, "status": task.status, "cancel_requested": task.cancel_requested}


# --------------------------------------------------------------------------- uploads
@router.post("/uploads", status_code=201)
def create_upload(
    body: UploadIn,
    request: Request,
    principal: tuple[User, ApiKey] = Depends(api_principal),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    user, api_key = principal
    try:
        upload, token = transfer.create_upload(
            db, user, body.dest, api_key_id=api_key.id, actor=_actor(api_key), request=request
        )
    except transfer.TransferError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {
        "upload_id": upload.id,
        "upload_url": transfer.upload_url(token),
        "dest": upload.dest,
        "expires_at": upload.expires_at.isoformat(),
        "max_bytes": get_settings().max_upload_bytes,
    }


async def _body_chunks(request: Request):
    content_type = request.headers.get("content-type", "")
    if content_type.startswith("multipart/form-data"):
        # curl -F file=@... : take the first file part (spooled by Starlette)
        form = await request.form()
        part = next((v for v in form.values() if hasattr(v, "read")), None)
        if part is None:
            raise transfer.TransferError("multipart upload without a file part")
        while chunk := await part.read(1024 * 1024):
            yield chunk
        return
    async for chunk in request.stream():
        yield chunk


@router.api_route("/uploads/{token}", methods=["PUT", "POST"])
async def receive_upload(token: str, request: Request) -> JSONResponse:
    """Upload target for curl. The URL itself is the credential (single use, short-lived)."""
    with new_session() as db:
        upload = transfer.find_upload_by_token(db, token)
        if upload is None:
            raise HTTPException(404, "unknown upload URL")
        if upload.status != UploadStatus.PENDING:
            raise HTTPException(409, f"upload already {upload.status}")
        expires = upload.expires_at
        now = utcnow()
        if (expires if expires.tzinfo else expires.replace(tzinfo=now.tzinfo)) < now:
            raise HTTPException(410, "upload URL expired")
        upload.status = UploadStatus.RECEIVING
        db.commit()
        upload_id = upload.id

    with new_session() as db:
        upload = db.get(Upload, upload_id)
        try:
            await transfer.receive_upload(upload, _body_chunks(request))
        except transfer.TransferError as exc:
            upload.status, upload.error = UploadStatus.FAILED, str(exc)
            db.commit()
            return JSONResponse({"upload_id": upload_id, "status": "failed", "error": str(exc)}, status_code=400)
        except Exception:
            upload.status, upload.error = UploadStatus.FAILED, "interrupted"
            db.commit()
            raise
        audit.record(
            db,
            "upload.receive",
            actor=f"apikey:{upload.api_key_id}" if upload.api_key_id else f"user:{upload.user_id}",
            user_id=upload.user_id,
            target=upload.id,
            request=request,
            size=upload.size,
            kind=upload.kind,
            sha256=upload.sha256,
        )
        db.commit()
        return JSONResponse(
            {"upload_id": upload.id, "status": upload.status, "kind": upload.kind, "size": upload.size,
             "sha256": upload.sha256, "dest": upload.dest}
        )


# --------------------------------------------------------------------------- downloads
@router.get("/downloads/{token}/{filename}")
def download(token: str, filename: str, db: Session = Depends(get_db)) -> Response:
    """Signed, expiring links for the patch and output files (the link itself is the credential)."""
    try:
        data = transfer.verify_download(token)
    except transfer.TransferError as exc:
        raise HTTPException(403, str(exc)) from exc
    task = db.get(Task, data["t"])
    if task is None:
        raise HTTPException(404, "task not found")
    return artifact_response(task, data["a"], filename)


def artifact_response(task: Task, artifact: str, filename: str) -> Response:
    if artifact == "patch":
        path = patch_path(task.id)
        if not path.exists():
            raise HTTPException(404, "no patch")
        return FileResponse(path, media_type="text/x-diff", filename=filename)
    if artifact == "outputs":
        path = outputs_path(task.id)
        if not path.exists():
            raise HTTPException(404, "no outputs")
        return FileResponse(path, media_type="application/gzip", filename=filename)
    if artifact.startswith("output:"):
        content = read_output_file(task, artifact[len("output:"):])
        if content is None:
            raise HTTPException(404, "no such output file")
        return Response(
            content,
            media_type="application/octet-stream",
            headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"},
        )
    raise HTTPException(404, "unknown artifact")
