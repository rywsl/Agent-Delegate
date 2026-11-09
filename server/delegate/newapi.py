"""Thin client for the new-api management API (QuantumNous/new-api >= v1.0.0-rc.41).

Authentication model of current new-api:
  * ``POST /api/user/login`` returns a short-lived dashboard JWT (15 min);
  * long-lived automation uses scoped personal access tokens (``nap_...``), minted with the JWT plus a
    one-time step-up proof from ``POST /api/verify`` (password method);
  * ``/api/token/*`` (relay API keys) always acts on the caller, so each mirror account needs its own PAT.

Every response is ``{"success": bool, "message": str, "data": ...}``; business errors use HTTP 200
with ``success: false``, so ``success`` is always checked.
"""

from __future__ import annotations

from typing import Any

import httpx

ROOT_PAT_SCOPES = ["log:read", "option:read", "option:write", "profile:read", "user:read", "user:write"]
MIRROR_PAT_SCOPES = ["api_key:read", "api_key:reveal", "api_key:write", "profile:read", "usage:read"]

LOG_TYPE_ALL = 0
LOG_TYPE_TOPUP = 1
LOG_TYPE_CONSUME = 2
LOG_TYPE_ERROR = 5
LOG_TYPE_REFUND = 6


class NewApiError(RuntimeError):
    def __init__(self, message: str, status: int | None = None, code: str | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.code = code

    @property
    def is_auth_error(self) -> bool:
        return self.status in (401, 403) or (self.code or "").startswith(("AUTH_", "ACCESS_TOKEN_"))


def _unwrap(resp: httpx.Response) -> Any:
    try:
        body = resp.json()
    except ValueError as exc:
        raise NewApiError(f"HTTP {resp.status_code}: {resp.text[:200] or resp.reason_phrase}", resp.status_code) from exc
    if resp.status_code >= 400 or not body.get("success", False):
        raise NewApiError(body.get("message") or f"HTTP {resp.status_code}", resp.status_code, body.get("code"))
    return body.get("data")


def _items(data: Any) -> tuple[list[dict[str, Any]], int]:
    """Paged endpoints return {page, page_size, total, items}."""
    if data is None:
        return [], 0
    if isinstance(data, list):
        return data, len(data)
    items = data.get("items") or []
    return items, int(data.get("total") or len(items))


class NewApi:
    def __init__(self, base_url: str, token: str | None = None, *, timeout: float = 20.0,
                 transport: httpx.BaseTransport | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout
        self.transport = transport
        self.actor_id: int | None = None

    def with_token(self, token: str) -> NewApi:
        client = NewApi(self.base_url, token, timeout=self.timeout, transport=self.transport)
        client.actor_id = self.actor_id
        return client

    def call(self, method: str, path: str, *, headers: dict[str, str] | None = None, **kwargs: Any) -> Any:
        all_headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
        if self.actor_id is not None:
            all_headers["New-Api-User"] = str(self.actor_id)
        all_headers.update(headers or {})
        try:
            with httpx.Client(base_url=self.base_url, timeout=self.timeout, transport=self.transport) as client:
                resp = client.request(method, path, headers=all_headers, **kwargs)
        except httpx.HTTPError as exc:
            raise NewApiError(f"new-api unreachable: {exc}") from exc
        return _unwrap(resp)

    # ------------------------------------------------------------------ public
    def status(self) -> dict[str, Any]:
        return self.call("GET", "/api/status") or {}

    def setup_status(self) -> dict[str, Any]:
        return self.call("GET", "/api/setup") or {}

    def run_setup(self, username: str, password: str) -> None:
        self.call("POST", "/api/setup", json={
            "username": username, "password": password, "confirmPassword": password,
            "SelfUseModeEnabled": False, "DemoSiteEnabled": False,
        })

    def login(self, username: str, password: str) -> tuple[int, NewApi]:
        """Password login. Returns (user id, client authenticated with the dashboard JWT)."""
        data = self.call("POST", "/api/user/login", json={"username": username, "password": password})
        if not isinstance(data, dict) or data.get("require_verification"):
            raise NewApiError("login requires 2FA/passkey verification; disable it for this account")
        return int(data["user"]["id"]), self.with_token(data["access_token"])

    # ------------------------------------------------------------------ step-up + personal access tokens
    def security_proof(self, password: str, scope: str, context: dict[str, Any]) -> str:
        data = self.call("POST", "/api/verify", json={
            "method": "password", "scope": scope, "context": context, "password": password,
        })
        return data["proof_token"]

    def create_access_token(self, password: str, name: str, scopes: list[str]) -> str:
        """Mint a non-expiring scoped PAT (requires a JWT session, not a PAT)."""
        scopes = sorted(set(scopes))
        proof = self.security_proof(password, "access_token.generate", {"scopes": scopes, "expires_at": 0})
        data = self.call("POST", "/api/user/access_tokens", headers={"X-Security-Proof": proof},
                         json={"name": name, "scopes": scopes, "expires_at": 0})
        return data["token"]

    def list_access_tokens(self) -> list[dict[str, Any]]:
        return (self.call("GET", "/api/user/access_tokens") or {}).get("items") or []

    def revoke_access_token(self, password: str, token_id: int) -> None:
        proof = self.security_proof(password, "access_token.revoke", {"token_id": token_id})
        self.call("DELETE", f"/api/user/access_tokens/{token_id}", headers={"X-Security-Proof": proof})

    def mint_pat(self, username: str, password: str, name: str, scopes: list[str]) -> tuple[int, str]:
        """Log in and replace any previous PAT called ``name`` with a fresh one. Returns (user id, PAT)."""
        user_id, session = self.login(username, password)
        for item in session.list_access_tokens():
            if item.get("name") == name:
                session.revoke_access_token(password, int(item["id"]))
        return user_id, session.create_access_token(password, name, scopes)

    # ------------------------------------------------------------------ admin (root PAT)
    def self_info(self) -> dict[str, Any]:
        return self.call("GET", "/api/user/self")

    def update_option(self, key: str, value: str) -> None:
        self.call("PUT", "/api/option/", json={"key": key, "value": value})

    def create_user(self, username: str, password: str, display_name: str) -> None:
        self.call("POST", "/api/user/", json={"username": username, "password": password,
                                              "display_name": display_name[:20], "role": 1})

    def get_user(self, user_id: int) -> dict[str, Any]:
        return self.call("GET", f"/api/user/{user_id}")

    def set_user_group(self, user: dict[str, Any], group: str, remark: str) -> None:
        # PUT writes username/display_name/group/remark as a map: always send all four.
        self.call("PUT", "/api/user/", json={"id": user["id"], "username": user["username"],
                                             "display_name": user.get("display_name") or user["username"],
                                             "group": group, "remark": remark})

    def adjust_quota(self, user_id: int, mode: str, value: int) -> None:
        """Atomic balance change ('add' | 'subtract' | 'override'); new-api records a top-up log."""
        self.call("POST", "/api/user/manage", json={"id": user_id, "action": "add_quota", "mode": mode,
                                                    "value": int(value)})

    def set_user_status(self, password: str, user_id: int, enabled: bool) -> None:
        action = "enable" if enabled else "disable"
        proof = self.security_proof(password, "admin.user.manage", {"user_id": user_id, "action": action})
        self.call("POST", "/api/user/manage", headers={"X-Security-Proof": proof},
                  json={"id": user_id, "action": action})

    def logs(self, **params: Any) -> tuple[list[dict[str, Any]], int]:
        return _items(self.call("GET", "/api/log/", params=params))

    # ------------------------------------------------------------------ mirror account (mirror PAT)
    def create_token(self, name: str, remain_quota: int, expired_time: int, allow_ips: str | None = None) -> None:
        body: dict[str, Any] = {
            "name": name,
            "remain_quota": int(remain_quota),
            "unlimited_quota": False,
            "expired_time": int(expired_time),
            "model_limits_enabled": False,
            "model_limits": "",
            "group": "",
        }
        if allow_ips:
            body["allow_ips"] = allow_ips
        self.call("POST", "/api/token/", json=body)

    def find_token(self, name: str) -> dict[str, Any] | None:
        items, _ = _items(self.call("GET", "/api/token/", params={"p": 1, "page_size": 100}))
        return next((t for t in items if t.get("name") == name), None)

    def reveal_token_key(self, token_id: int) -> str:
        return self.call("POST", f"/api/token/{token_id}/key")["key"]

    def delete_token(self, token_id: int) -> None:
        self.call("DELETE", f"/api/token/{token_id}")

    # ------------------------------------------------------------------ channels (root dashboard session)
    def list_channels(self) -> list[dict[str, Any]]:
        items, _ = _items(self.call("GET", "/api/channel/", params={"p": 1, "page_size": 100}))
        return items

    def create_channel(self, channel: dict[str, Any]) -> None:
        self.call("POST", "/api/channel/", json={"mode": "single", "channel": channel})

    def update_channel(self, channel: dict[str, Any]) -> None:
        self.call("PUT", "/api/channel/", json=channel)

    def delete_channel(self, channel_id: int) -> None:
        self.call("DELETE", f"/api/channel/{channel_id}/")

    def test_channel(self, channel_id: int, model: str = "") -> Any:
        params = {"model": model} if model else None
        return self.call("GET", f"/api/channel/test/{channel_id}", params=params)
