"""File transfer between the delegating side and the sandbox without going through the LLM.

Uploads: the caller asks for an upload slot and gets a one-time URL; it then pushes a file or an
archive (tar / tar.gz / zip) with curl. Archives are extracted inside the sandbox, never on the host.

Downloads: patch and output files are served through short-lived signed URLs, so the delegating
agent can fetch them with curl without ever handling the account's API key.
"""

from __future__ import annotations

import hashlib
import os
import secrets
import shutil
from collections.abc import AsyncIterator
from datetime import timedelta
from pathlib import Path
from typing import Any
from urllib.parse import quote

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy.orm import Session

from . import audit
from .config import get_settings
from .models import Upload, UploadStatus, User, utcnow

DOWNLOAD_SALT = "delegate-download"


class TransferError(ValueError):
    pass


# --------------------------------------------------------------------------- uploads
def upload_path(upload_id: str) -> Path:
    return get_settings().uploads_dir / upload_id


def upload_url(token: str) -> str:
    return f"{get_settings().public_url}/api/v1/uploads/{token}"


def create_upload(
    session: Session, user: User, dest: str, *, api_key_id: int | None, actor: str, request: Any = None
) -> tuple[Upload, str]:
    from .tasks import TaskInputError, normalise_path  # local import: tasks imports this module

    dest = (dest or ".").strip() or "."
    if dest not in (".", "./"):
        try:
            dest = normalise_path(dest)
        except TaskInputError as exc:
            raise TransferError(str(exc)) from exc
    else:
        dest = "."
    token = "upl_" + secrets.token_urlsafe(32)
    upload = Upload(
        id="u_" + secrets.token_hex(8),
        user_id=user.id,
        api_key_id=api_key_id,
        token_hash=hashlib.sha256(token.encode()).hexdigest(),
        dest=dest,
        expires_at=utcnow() + timedelta(seconds=get_settings().upload_ttl_s),
    )
    session.add(upload)
    audit.record(session, "upload.create", actor=actor, user_id=user.id, target=upload.id, request=request, dest=dest)
    return upload, token


def find_upload_by_token(session: Session, token: str) -> Upload | None:
    return session.query(Upload).filter_by(token_hash=hashlib.sha256(token.encode()).hexdigest()).one_or_none()


def detect_kind(path: Path) -> str:
    with path.open("rb") as fh:
        head = fh.read(512)
    if head[:2] == b"\x1f\x8b":
        return "tgz"
    if head[:4] in (b"PK\x03\x04", b"PK\x05\x06"):
        return "zip"
    if len(head) >= 262 and head[257:262] == b"ustar":
        return "tar"
    return "file"


async def receive_upload(upload: Upload, chunks: AsyncIterator[bytes]) -> None:
    """Stream the request body to disk, enforcing the size limit. Mutates ``upload``."""
    limit = get_settings().max_upload_bytes
    dest = upload_path(upload.id)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".part")
    digest = hashlib.sha256()
    size = 0
    try:
        with tmp.open("wb") as fh:
            async for chunk in chunks:
                size += len(chunk)
                if size > limit:
                    raise TransferError(f"upload exceeds the limit of {limit} bytes")
                digest.update(chunk)
                fh.write(chunk)
        if size == 0:
            raise TransferError("empty upload")
        os.replace(tmp, dest)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    kind = detect_kind(dest)
    if kind == "file" and upload.dest == ".":
        dest.unlink(missing_ok=True)
        raise TransferError(
            "a single (non-archive) file needs a destination file name: create the upload with dest='path/name.ext', "
            "or upload a tar/tar.gz/zip archive"
        )
    upload.kind = kind
    upload.size = size
    upload.sha256 = digest.hexdigest()
    upload.status = UploadStatus.READY
    upload.uploaded_at = utcnow()


def attach_to_task(upload: Upload, task_dir: Path) -> dict[str, Any]:
    """Archive the upload with the task (inputs stay auditable after the upload slot expires)."""
    target = task_dir / "uploads" / upload.id
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        try:
            os.link(upload_path(upload.id), target)
        except OSError:
            shutil.copyfile(upload_path(upload.id), target)
    return {"id": upload.id, "dest": upload.dest, "kind": upload.kind, "size": upload.size, "sha256": upload.sha256}


def purge_expired_uploads(session: Session) -> int:
    expired = session.query(Upload).filter(Upload.expires_at < utcnow(), Upload.status != UploadStatus.EXPIRED).all()
    for upload in expired:
        upload_path(upload.id).unlink(missing_ok=True)  # tasks keep their own copy (attach_to_task)
        upload.status = UploadStatus.EXPIRED
    return len(expired)


# --------------------------------------------------------------------------- downloads
def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(get_settings().secret_key, salt=DOWNLOAD_SALT)


def download_url(task_id: str, artifact: str, filename: str) -> str:
    """artifact: 'patch' | 'outputs' | 'output:<relative path>'."""
    token = _serializer().dumps({"t": task_id, "a": artifact})
    return f"{get_settings().public_url}/api/v1/downloads/{token}/{quote(filename)}"


def verify_download(token: str) -> dict[str, str]:
    try:
        data = _serializer().loads(token, max_age=get_settings().download_ttl_s)
    except SignatureExpired as exc:
        raise TransferError("download link expired; call wait_task again for fresh links") from exc
    except BadSignature as exc:
        raise TransferError("invalid download link") from exc
    return data
