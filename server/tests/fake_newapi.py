"""In-memory stand-in for the new-api management API, mirroring the semantics verified in its source:

* setup required on a fresh instance; login returns a dashboard JWT;
* PATs are minted with JWT + a single-use step-up proof bound to scope/context;
* /api/token/* acts on the caller; keys are masked in listings and revealed via POST /:id/key;
* business errors are HTTP 200 with success=false; auth errors 401;
* add_quota adjusts balances atomically and writes a top-up log.
"""

from __future__ import annotations

import json
import re
import secrets
import time
from typing import Any

import httpx


class FakeNewApi:
    def __init__(self) -> None:
        self.setup_done = False
        self.users: dict[int, dict[str, Any]] = {}
        self.jwts: dict[str, int] = {}
        self.pats: dict[str, dict[str, Any]] = {}
        self.proofs: dict[str, dict[str, Any]] = {}
        self.tokens: dict[int, dict[str, Any]] = {}
        self.logs: list[dict[str, Any]] = []
        self.options: dict[str, str] = {}
        self.next_user = 1
        self.next_token = 1
        self.next_pat = 1
        self.calls: list[tuple[str, str]] = []

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def ok(data: Any = None) -> httpx.Response:
        body = {"success": True, "message": ""}
        if data is not None:
            body["data"] = data
        return httpx.Response(200, json=body)

    @staticmethod
    def fail(message: str, status: int = 200, code: str | None = None) -> httpx.Response:
        body: dict[str, Any] = {"success": False, "message": message}
        if code:
            body["code"] = code
        return httpx.Response(status, json=body)

    def _identity(self, request: httpx.Request) -> tuple[int | None, str | None, list[str]]:
        auth = request.headers.get("authorization", "")
        token = auth.split(" ", 1)[1] if auth.lower().startswith("bearer ") else auth
        if token in self.jwts:
            return self.jwts[token], "jwt", []
        if token in self.pats:
            pat = self.pats[token]
            return pat["user_id"], "pat", pat["scopes"]
        return None, None, []

    def add_user(self, username: str, password: str, role: int = 1, quota: int = 0) -> dict[str, Any]:
        uid = self.next_user
        self.next_user += 1
        user = {"id": uid, "username": username, "password": password, "display_name": username, "role": role,
                "status": 1, "quota": quota, "used_quota": 0, "request_count": 0, "group": "default", "remark": ""}
        self.users[uid] = user
        return user

    def consume(self, key: str, quota: int, prompt: int, completion: int, model: str = "claude-sonnet-5-5",
                other: dict[str, Any] | None = None) -> None:
        """Simulate one relayed model call billed to the token with this key."""
        raw = key[3:] if key.startswith("sk-") else key
        token = next(t for t in self.tokens.values() if t["key"] == raw)
        user = self.users[token["user_id"]]
        token["remain_quota"] -= quota
        token["used_quota"] += quota
        user["quota"] -= quota
        user["used_quota"] += quota
        user["request_count"] += 1
        self.logs.append({
            "id": len(self.logs) + 1, "user_id": user["id"], "created_at": int(time.time()), "type": 2,
            "content": "", "username": user["username"], "token_name": token["name"], "model_name": model,
            "quota": quota, "prompt_tokens": prompt, "completion_tokens": completion, "use_time": 3,
            "is_stream": True, "token_id": token["id"], "request_id": secrets.token_hex(8),
            "other": json.dumps(other or {}),
        })

    # ------------------------------------------------------------------ dispatcher
    def handle(self, request: httpx.Request) -> httpx.Response:
        method, path = request.method, request.url.path
        self.calls.append((method, path))
        body = json.loads(request.content) if request.content else {}
        params = dict(request.url.params)

        if path == "/api/status":
            return self.ok({"version": "fake-rc", "quota_per_unit": 500000})
        if path == "/api/setup":
            if method == "GET":
                return self.ok({"status": self.setup_done, "root_init": self.setup_done})
            if self.setup_done:
                return self.fail("The system is already initialized")
            self.add_user(body["username"], body["password"], role=100, quota=100000000)
            self.setup_done = True
            return self.ok()
        if path == "/api/user/login":
            user = next((u for u in self.users.values() if u["username"] == body.get("username")), None)
            if not user or user["password"] != body.get("password"):
                return self.fail("Invalid username or password")
            jwt = "jwt." + secrets.token_hex(8)
            self.jwts[jwt] = user["id"]
            return self.ok({"access_token": jwt, "token_type": "Bearer", "user": {"id": user["id"]}})

        uid, kind, scopes = self._identity(request)
        if uid is None:
            return self.fail("unauthorized", 401, "AUTH_UNAUTHORIZED")
        me = self.users[uid]

        def need(scope: str) -> httpx.Response | None:
            if kind == "pat" and scope not in scopes:
                return self.fail("scope denied", 403, "ACCESS_TOKEN_SCOPE_DENIED")
            return None

        def need_admin(scope: str) -> httpx.Response | None:
            if me["role"] < 10:
                return self.fail("insufficient privilege", 403, "AUTH_INSUFFICIENT_PRIVILEGE")
            return need(scope)

        def consume_proof(scope: str, context: dict[str, Any]) -> bool:
            proof = self.proofs.pop(request.headers.get("x-security-proof", ""), None)
            return bool(proof and proof["user_id"] == uid and proof["scope"] == scope and proof["context"] == context)

        if path == "/api/verify":
            if body.get("method") != "password" or body.get("password") != me["password"]:
                return self.fail("verification failed")
            if body["scope"].startswith("access_token.") and kind != "jwt":
                return self.fail("session required", 403, "AUTH_SESSION_REQUIRED")
            proof = "proof." + secrets.token_hex(8)
            self.proofs[proof] = {"user_id": uid, "scope": body["scope"], "context": body.get("context")}
            return self.ok({"proof_token": proof, "scope": body["scope"], "method": "password"})

        if path.startswith("/api/user/access_tokens"):
            if kind != "jwt":
                return self.fail("session required", 403, "AUTH_SESSION_REQUIRED")
            if method == "GET":
                items = [{"id": p["id"], "name": p["name"], "scopes": p["scopes"]}
                         for p in self.pats.values() if p["user_id"] == uid]
                return self.ok({"items": items, "legacy": None})
            if method == "POST":
                ctx = {"scopes": sorted(set(body["scopes"])), "expires_at": body["expires_at"]}
                if not consume_proof("access_token.generate", ctx):
                    return self.fail("proof required", 403, "SECURITY_PROOF_REQUIRED")
                raw = "nap_" + secrets.token_hex(20)
                self.pats[raw] = {"id": self.next_pat, "user_id": uid, "name": body["name"], "scopes": ctx["scopes"]}
                self.next_pat += 1
                return self.ok({"token": raw, "item": {"id": self.pats[raw]["id"], "name": body["name"]}})
            if method == "DELETE":
                pat_id = int(path.rsplit("/", 1)[1])
                if not consume_proof("access_token.revoke", {"token_id": pat_id}):
                    return self.fail("proof required", 403, "SECURITY_PROOF_REQUIRED")
                for raw, p in list(self.pats.items()):
                    if p["id"] == pat_id and p["user_id"] == uid:
                        del self.pats[raw]
                return self.ok()

        if path == "/api/user/self":
            return need("profile:read") or self.ok({k: v for k, v in me.items() if k != "password"})
        if path == "/api/option/":
            if me["role"] < 100:
                return self.fail("root only", 403, "AUTH_INSUFFICIENT_PRIVILEGE")
            denied = need("option:write")
            if denied:
                return denied
            self.options[body["key"]] = body["value"]
            return self.ok()

        if path == "/api/user/" and method == "POST":
            denied = need_admin("user:write")
            if denied:
                return denied
            if any(u["username"] == body["username"] for u in self.users.values()):
                return self.fail("UNIQUE constraint failed: users.username")
            self.add_user(body["username"], body["password"])
            return self.ok()
        if path == "/api/user/" and method == "PUT":
            denied = need_admin("user:write")
            if denied:
                return denied
            user = self.users[body["id"]]
            for key in ("username", "display_name", "group", "remark"):
                user[key] = body.get(key, "")
            return self.ok()
        if path == "/api/user/manage":
            denied = need_admin("user:write")
            if denied:
                return denied
            user = self.users[body["id"]]
            if body["action"] == "add_quota":
                value, mode = int(body.get("value", 0)), body.get("mode")
                if mode in ("add", "subtract") and value <= 0:
                    return self.fail("Quota change amount cannot be zero")
                user["quota"] = {"add": user["quota"] + value, "subtract": user["quota"] - value,
                                 "override": value}[mode]
                self.logs.append({"id": len(self.logs) + 1, "user_id": user["id"], "created_at": int(time.time()),
                                  "type": 1, "content": f"admin {mode} {value}", "username": user["username"],
                                  "token_name": "", "model_name": "", "quota": value, "prompt_tokens": 0,
                                  "completion_tokens": 0})
                return self.ok()
            if not consume_proof("admin.user.manage", {"user_id": user["id"], "action": body["action"]}):
                return self.fail("proof required", 403, "SECURITY_PROOF_REQUIRED")
            user["status"] = 1 if body["action"] == "enable" else 2
            return self.ok({"role": user["role"], "status": user["status"]})
        m = re.fullmatch(r"/api/user/(\d+)", path)
        if m and method == "GET":
            denied = need_admin("user:read")
            if denied:
                return denied
            user = self.users.get(int(m.group(1)))
            return self.ok({k: v for k, v in user.items() if k != "password"}) if user else self.fail("not found")

        if path == "/api/log/":
            denied = need_admin("log:read")
            if denied:
                return denied
            rows = [l for l in self.logs
                    if (not params.get("username") or l["username"] == params["username"])
                    and (not params.get("token_name") or l["token_name"] == params["token_name"])
                    and (params.get("type", "0") == "0" or str(l["type"]) == params["type"])]
            rows.sort(key=lambda l: (-l["created_at"], -l["id"]))
            page, size = int(params.get("p", 1)), min(int(params.get("page_size", 10)), 100)
            return self.ok({"page": page, "page_size": size, "total": len(rows),
                            "items": rows[(page - 1) * size: page * size]})

        if path == "/api/token/" and method == "POST":
            denied = need("api_key:write")
            if denied:
                return denied
            tid = self.next_token
            self.next_token += 1
            self.tokens[tid] = {"id": tid, "user_id": uid, "name": body["name"], "key": secrets.token_hex(24),
                                "remain_quota": body["remain_quota"], "used_quota": 0, "status": 1,
                                "expired_time": body["expired_time"], "allow_ips": body.get("allow_ips")}
            return self.ok()
        if path == "/api/token/" and method == "GET":
            denied = need("api_key:read")
            if denied:
                return denied
            mine = sorted((t for t in self.tokens.values() if t["user_id"] == uid), key=lambda t: -t["id"])
            items = [{**t, "key": t["key"][:4] + "**********" + t["key"][-4:]} for t in mine]
            return self.ok({"page": 1, "page_size": 100, "total": len(items), "items": items[:100]})
        m = re.fullmatch(r"/api/token/(\d+)/key", path)
        if m:
            denied = need("api_key:reveal")
            if denied:
                return denied
            token = self.tokens.get(int(m.group(1)))
            return self.ok({"key": token["key"]}) if token and token["user_id"] == uid else self.fail("not found")
        m = re.fullmatch(r"/api/token/(\d+)", path)
        if m and method == "DELETE":
            denied = need("api_key:write")
            if denied:
                return denied
            token = self.tokens.get(int(m.group(1)))
            if not token or token["user_id"] != uid:
                return self.fail("not found")
            del self.tokens[token["id"]]
            return self.ok()
        return self.fail(f"fake: unhandled {method} {path}", 404)

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)
