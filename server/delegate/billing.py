"""Token billing through the new-api sidecar.

The web site wraps new-api completely; users never see it:
  * the site performs new-api's first-run setup and keeps a scoped root PAT;
  * every site user gets a mirror account in new-api; the site keeps that account's scoped PAT;
  * every task gets its own relay API key (new-api "token") whose quota is the task budget, so
    new-api enforces the spending limit and its logs give exact per-request, per-task billing;
  * balance changes use new-api's atomic ``add_quota`` (no read-modify-write race with consumption);
    top-up codes are issued and checked by the site itself.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import secrets
import threading
import time
from datetime import timedelta
from pathlib import Path
from typing import Any, Callable, TypeVar

from sqlalchemy import update
from sqlalchemy.orm import Session

from . import audit
from .config import get_settings
from .models import LedgerEntry, RedeemCode, Task, User, utcnow
from .newapi import LOG_TYPE_ALL, LOG_TYPE_CONSUME, MIRROR_PAT_SCOPES, ROOT_PAT_SCOPES, NewApi, NewApiError
from .security import decrypt, encrypt, random_password

log = logging.getLogger(__name__)

PAT_NAME = "delegate-site"
T = TypeVar("T")

_root_lock = threading.Lock()
_root_client: NewApi | None = None
_transport = None  # httpx transport override (tests)


class BillingError(RuntimeError):
    def __init__(self, message: str, status_code: int = 503) -> None:
        super().__init__(message)
        self.status_code = status_code


def _base() -> NewApi:
    return NewApi(get_settings().newapi_base_url, transport=_transport)


def _root_file() -> Path:
    # Kept in the shared data directory (not the database) so it can be rewritten from anywhere,
    # including while a request holds a database write transaction.
    return get_settings().data_dir / "newapi-root.json"


def _stored_root() -> dict[str, Any]:
    try:
        return json.loads(_root_file().read_text())
    except (FileNotFoundError, ValueError):
        return {}


def _save_root(value: dict[str, Any]) -> None:
    path = _root_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(value))
    os.replace(tmp, path)


# --------------------------------------------------------------------------- root credentials
def bootstrap(rejected_token: str | None = None) -> NewApi:
    """Ensure the site holds a working root PAT (runs new-api's first-time setup if needed).

    ``rejected_token``: the PAT that new-api just refused; a different stored PAT (e.g. minted by
    another process meanwhile) is tried before minting a new one.
    """
    global _root_client
    s = get_settings()
    with _root_lock:
        stored = _stored_root()
        if stored.get("pat_enc") and decrypt(stored["pat_enc"]) != rejected_token:
            client = _base().with_token(decrypt(stored["pat_enc"]))
            try:
                client.self_info()
                _root_client = client
                return client
            except NewApiError as exc:
                if not exc.is_auth_error:
                    raise
                log.warning("stored new-api root PAT rejected (%s); minting a new one", exc)

        api = _base()
        password = s.newapi_root_password or (decrypt(stored["password_enc"]) if stored.get("password_enc") else None)
        if not api.setup_status().get("status"):
            password = password or random_password(24)
            log.info("running new-api first-time setup (root user %s)", s.newapi_root_username)
            # Persist the password before setup so a crash in between cannot lose it.
            _save_root({**stored, "username": s.newapi_root_username, "password_enc": encrypt(password)})
            api.run_setup(s.newapi_root_username, password)
        if not password:
            raise BillingError("NEWAPI_ROOT_PASSWORD is not set and no stored root password exists")
        user_id, pat = api.mint_pat(s.newapi_root_username, password, PAT_NAME, ROOT_PAT_SCOPES)
        _save_root({
            "user_id": user_id,
            "username": s.newapi_root_username,
            "password_enc": encrypt(password),
            "pat_enc": encrypt(pat),
            "install_id": stored.get("install_id") or secrets.token_hex(2),
        })
        client = api.with_token(pat)
        _harden(client)
        _root_client = client
        return client


def _harden(root: NewApi) -> None:
    """Users only reach new-api through the site: no self-service sign-up on the sidecar."""
    for key, value in (("RegisterEnabled", "false"), ("PasswordRegisterEnabled", "false"),
                       ("PasswordLoginEnabled", "true"), ("TurnstileCheckEnabled", "false")):
        try:
            root.update_option(key, value)
        except NewApiError as exc:
            log.warning("could not set new-api option %s: %s", key, exc)


def root() -> NewApi:
    if _root_client is not None:
        return _root_client
    try:
        return bootstrap()
    except NewApiError as exc:
        raise BillingError(f"billing gateway unavailable: {exc}") from exc


def _root_call(fn: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    """Call a root API method; re-mint the PAT once if new-api rejects it."""
    client = root()
    try:
        return fn(client, *args, **kwargs)
    except NewApiError as exc:
        if not exc.is_auth_error:
            raise BillingError(str(exc)) from exc
    try:
        return fn(bootstrap(rejected_token=client.token), *args, **kwargs)
    except NewApiError as exc:
        raise BillingError(str(exc)) from exc


def _root_password() -> str:
    stored = _stored_root()
    if not stored.get("password_enc"):
        raise BillingError("root credentials not initialised")
    return decrypt(stored["password_enc"])


def health() -> tuple[bool, str]:
    try:
        status = _base().status()
        _root_call(NewApi.self_info)
        return True, f"ok (new-api {status.get('version', '?')})"
    except (NewApiError, BillingError) as exc:
        return False, str(exc)


# --------------------------------------------------------------------------- mirror accounts
def mirror_username(user: User) -> str:
    install = _stored_root().get("install_id") or "0000"
    return f"dlg{install}u{user.id}"[:20]


def mirror_password(username: str) -> str:
    """Derived from the site secret: provisioning is idempotent and nothing extra is stored."""
    digest = hmac.new(get_settings().secret_key.encode(), f"newapi-mirror:{username}".encode(), hashlib.sha256)
    return "M" + digest.hexdigest()[:23]


def ensure_mirror(db: Session, user: User) -> NewApi:
    """Return a client acting as the user's mirror account, creating the account on first use."""
    if user.newapi_user_id and user.newapi_pat_enc:
        return _base().with_token(decrypt(user.newapi_pat_enc))
    root()  # make sure setup ran and install_id exists
    s = get_settings()
    username = user.newapi_username or mirror_username(user)
    password = mirror_password(username)
    create_error: BillingError | None = None
    try:
        _root_call(NewApi.create_user, username, password, f"delegate-{user.id}")
    except BillingError as exc:
        create_error = exc  # most likely the account exists from an earlier, interrupted attempt
    created = create_error is None
    try:
        try:
            user_id, pat = _base().mint_pat(username, password, PAT_NAME, MIRROR_PAT_SCOPES)
        except NewApiError as exc:
            raise BillingError(f"cannot provision billing account: {create_error or exc}") from exc
        info = _root_call(NewApi.get_user, user_id)
        if info.get("group") != s.newapi_user_group:
            _root_call(NewApi.set_user_group, info, s.newapi_user_group, f"delegate user {user.id} <{user.email}>")
        if created and int(info.get("quota") or 0) != 0:
            _root_call(NewApi.adjust_quota, user_id, "override", 0)  # balances only change through the site
    except NewApiError as exc:
        raise BillingError(f"cannot provision billing account: {exc}") from exc
    user.newapi_username = username
    user.newapi_user_id = user_id
    user.newapi_pat_enc = encrypt(pat)
    user.newapi_synced_at = utcnow()
    audit.record(db, "billing.mirror_created", actor="system", user_id=user.id, target=f"newapi:{user_id}",
                 username=username, created=created)
    db.flush()
    return _base().with_token(pat)


def _mirror_call(db: Session, user: User, fn: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    client = ensure_mirror(db, user)
    try:
        return fn(client, *args, **kwargs)
    except NewApiError as exc:
        if not exc.is_auth_error:
            raise BillingError(str(exc)) from exc
    try:
        db.refresh(user, ["newapi_pat_enc"])  # another process may have rotated it already
        if user.newapi_pat_enc and decrypt(user.newapi_pat_enc) != client.token:
            try:
                return fn(_base().with_token(decrypt(user.newapi_pat_enc)), *args, **kwargs)
            except NewApiError as exc:
                if not exc.is_auth_error:
                    raise
        # PAT revoked: mint a new one and retry once
        _, pat = _base().mint_pat(user.newapi_username, mirror_password(user.newapi_username), PAT_NAME,
                                  MIRROR_PAT_SCOPES)
        user.newapi_pat_enc = encrypt(pat)
        return fn(_base().with_token(pat), *args, **kwargs)
    except NewApiError as exc:
        raise BillingError(str(exc)) from exc


def mirror_info(user: User) -> dict[str, Any] | None:
    if not user.newapi_user_id:
        return None
    return _root_call(NewApi.get_user, user.newapi_user_id)


def set_mirror_enabled(user: User, enabled: bool) -> None:
    if user.newapi_user_id:
        _root_call(NewApi.set_user_status, _root_password(), user.newapi_user_id, enabled)


def balance_quota(user: User) -> int | None:
    try:
        info = mirror_info(user)
    except BillingError:
        return None
    return int(info.get("quota", 0)) if info else None


def check_can_start(db: Session, user: User) -> None:
    ensure_mirror(db, user)
    balance = balance_quota(user)
    if balance is None:
        raise BillingError("billing gateway unavailable, try again later")
    s = get_settings()
    if balance < s.usd_to_quota(s.min_balance_usd):
        raise BillingError(f"insufficient balance ({s.quota_to_usd(balance):.2f} USD); top up on the web site", 402)


# --------------------------------------------------------------------------- per-task relay keys
def task_token_name(task: Task) -> str:
    return f"task-{task.id}"


def open_task_token(db: Session, user: User, task: Task) -> str:
    """Create the task's own relay key (quota = task budget) and return it for the sandbox."""
    check_can_start(db, user)
    name = task_token_name(task)
    expires = int(time.time()) + task.timeout_s + 3600
    _mirror_call(db, user, NewApi.create_token, name, task.budget_quota, expires,
                 get_settings().sandbox_allowed_ips or None)
    token = _mirror_call(db, user, NewApi.find_token, name)
    if token is None:
        raise BillingError("gateway key was not created")
    key = _mirror_call(db, user, NewApi.reveal_token_key, int(token["id"]))
    task.newapi_token_id = int(token["id"])
    task.newapi_token_name = name
    audit.record(db, "billing.key_open", actor="system", user_id=user.id, target=task.id,
                 token_id=task.newapi_token_id, budget_quota=task.budget_quota)
    return key if key.startswith("sk-") else f"sk-{key}"


def close_task_token(db: Session, task: Task) -> None:
    """Delete the task's relay key so the sandbox's copy is useless once the task has ended."""
    if not task.newapi_token_id:
        return
    user = db.get(User, task.user_id)
    try:
        _mirror_call(db, user, NewApi.delete_token, task.newapi_token_id)
        audit.record(db, "billing.key_close", actor="system", user_id=task.user_id, target=task.id,
                     token_id=task.newapi_token_id)
    except BillingError as exc:
        log.error("could not delete gateway key %s of task %s: %s", task.newapi_token_id, task.id, exc)
        audit.record(db, "billing.key_close_failed", actor="system", user_id=task.user_id, target=task.id,
                     token_id=task.newapi_token_id, error=str(exc))


def task_logs(task: Task) -> list[dict[str, Any]]:
    """Every gateway log entry of the task's key (consumption, errors, refunds), oldest first."""
    if not task.newapi_token_name:
        return []
    username = task.user.newapi_username
    created = task.created_at
    rows: list[dict[str, Any]] = []
    page = 1
    while True:
        items, total = _root_call(
            NewApi.logs, p=page, page_size=100, type=LOG_TYPE_ALL, username=username,
            token_name=task.newapi_token_name, start_timestamp=int(created.timestamp()) - 60,
            end_timestamp=int(time.time()) + 60,
        )
        rows.extend(i for i in items if i.get("token_name") == task.newapi_token_name)
        if not items or page * 100 >= total:
            break
        page += 1
    return sorted(rows, key=lambda r: (r.get("created_at", 0), r.get("id", 0)))


def reconcile_task(db: Session, task: Task) -> None:
    consumed = [r for r in task_logs(task) if r.get("type") == LOG_TYPE_CONSUME]
    task.billed_quota = sum(int(r.get("quota") or 0) for r in consumed)
    task.billed_prompt_tokens = sum(int(r.get("prompt_tokens") or 0) for r in consumed)
    task.billed_completion_tokens = sum(int(r.get("completion_tokens") or 0) for r in consumed)
    task.billed_requests = len(consumed)
    task.billing_reconciled_at = utcnow()
    near_budget = task.billed_quota >= task.budget_quota * 0.98
    if task.status != "succeeded" and near_budget and not (task.status_reason or "").startswith("budget exhausted"):
        budget = get_settings().quota_to_usd(task.budget_quota)
        task.status_reason = f"budget exhausted ({budget:.2f} USD)" + (f": {task.status_reason}" if task.status_reason else "")


def user_logs(user: User, page: int, page_size: int) -> tuple[list[dict[str, Any]], int]:
    if not user.newapi_username:
        return [], 0
    return _root_call(NewApi.logs, p=page, page_size=page_size, type=LOG_TYPE_ALL, username=user.newapi_username)


# --------------------------------------------------------------------------- balance changes
def adjust(db: Session, user: User, quota: int, *, kind: str, actor: str, note: str = "", request: Any = None) -> None:
    """Credit (quota > 0) or debit (quota < 0) a balance atomically in new-api, with a ledger entry."""
    if quota == 0:
        raise BillingError("amount must not be zero", 400)
    ensure_mirror(db, user)
    entry = LedgerEntry(user_id=user.id, kind=kind, quota_delta=quota, actor=actor, note=note)
    db.add(entry)
    db.flush()
    try:
        _root_call(NewApi.adjust_quota, user.newapi_user_id, "add" if quota > 0 else "subtract", abs(quota))
    except BillingError as exc:
        entry.status, entry.error = "failed", str(exc)
        audit.record(db, "billing.adjust_failed", actor=actor, user_id=user.id, target=f"ledger:{entry.id}",
                     request=request, quota=quota, kind=kind, error=str(exc))
        db.commit()
        raise
    entry.status = "applied"
    audit.record(db, "billing.adjust", actor=actor, user_id=user.id, target=f"ledger:{entry.id}", request=request,
                 quota=quota, kind=kind, note=note)


def create_codes(db: Session, quota: int, count: int, *, actor: str, note: str = "",
                 valid_days: int | None = None) -> list[str]:
    if quota <= 0:
        raise BillingError("amount must be positive", 400)
    codes = []
    expires = utcnow() + timedelta(days=valid_days) if valid_days else None
    for _ in range(count):
        code = "DLG-" + "-".join(secrets.token_hex(3).upper() for _ in range(4))
        db.add(RedeemCode(code_hash=hashlib.sha256(code.encode()).hexdigest(), hint=code[-4:], quota=quota,
                          note=note, created_by=actor, expires_at=expires))
        codes.append(code)
    return codes


def redeem(db: Session, user: User, code: str, *, actor: str, request: Any = None) -> int:
    row = db.query(RedeemCode).filter_by(code_hash=hashlib.sha256(code.strip().upper().encode()).hexdigest()).one_or_none()
    now = utcnow()
    if row is None:
        raise BillingError("invalid code", 400)
    expires = row.expires_at
    if expires is not None and (expires if expires.tzinfo else expires.replace(tzinfo=now.tzinfo)) < now:
        raise BillingError("code expired", 400)
    claimed = db.execute(
        update(RedeemCode).where(RedeemCode.id == row.id, RedeemCode.redeemed_by.is_(None))
        .values(redeemed_by=user.id, redeemed_at=now)
    ).rowcount
    if not claimed:
        raise BillingError("code already used", 400)
    try:
        adjust(db, user, row.quota, kind="redeem_code", actor=actor, note=f"code …{row.hint}", request=request)
    except BillingError:
        db.execute(update(RedeemCode).where(RedeemCode.id == row.id).values(redeemed_by=None, redeemed_at=None))
        db.commit()
        raise
    return row.quota
