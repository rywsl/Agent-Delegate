from __future__ import annotations

import io
import re
import tarfile


def csrf_of(client, path="/login") -> str:
    html = client.get(path).text
    return re.search(r'name="csrf-token" content="([^"]+)"', html).group(1)


def register(client, email="admin@example.com", password="password123"):
    token = csrf_of(client, "/register")
    resp = client.post("/register", data={"csrf": token, "email": email, "password": password, "display_name": "x"},
                       follow_redirects=False)
    assert resp.status_code == 303, resp.text


def make_key(client) -> str:
    token = csrf_of(client, "/keys")
    page = client.post("/keys", data={"csrf": token, "name": "laptop"}).text
    return re.search(r"(dlg_[A-Za-z0-9_\-]{20,})", page).group(1)


def tgz(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def test_full_user_flow(client, env):
    register(client)
    assert "控制台" in client.get("/dashboard").text
    key = make_key(client)
    api = {"Authorization": f"Bearer {key}"}
    assert client.get("/api/v1/me", headers=api).json() == {"email": "admin@example.com"}

    token = csrf_of(client, "/admin/providers")
    resp = client.post("/admin/providers/anthropic", data={
        "csrf": token, "base_url": "https://anthropic.example.com", "api_key": "secret-from-admin", "enabled": "on",
    }, follow_redirects=False)
    assert resp.status_code == 303
    page = client.get("/admin/providers").text
    assert "https://anthropic.example.com" in page and "secret-from-admin" not in page

    token = csrf_of(client, "/settings")
    client.post("/settings", data={"csrf": token, "agent": "anthropic", "model": "claude-sonnet-4-5",
                                   "sandbox": "docker", "harness": "codex", "timeout_min": "30"})
    assert "codex" in client.get("/settings").text

    slot = client.post("/api/v1/uploads", json={"dest": "."}, headers=api).json()
    upload_path = slot["upload_url"].replace("http://testserver", "")
    resp = client.put(upload_path, content=tgz({"src/app.py": b"print('hi')\n"}))
    assert resp.status_code == 200 and resp.json()["status"] == "ready"
    assert client.put(upload_path, content=b"again").status_code == 409

    resp = client.post("/api/v1/tasks", json={
        "task": "Fix the bug\nmore details", "upload_ids": [slot["upload_id"]],
        "files": [{"path": "notes/readme.txt", "content": "hello"}],
    }, headers={**api, "X-Delegate-Client": "claude-code/9.9"})
    assert resp.status_code == 201, resp.text
    view = resp.json()
    assert view["status"] == "queued" and view["title"] == "Fix the bug"
    task_id = view["id"]
    assert client.get(f"/api/v1/tasks/{task_id}/wait?timeout=0", headers=api).json()["status"] == "queued"

    detail = client.get(f"/tasks/{task_id}").text
    assert "Fix the bug" in detail and "claude-code/9.9" in detail and "codex" in detail
    for path in ["/tasks", "/settings", "/audit", "/keys", "/admin", "/admin/providers", "/admin/users",
                 "/admin/users/1", "/admin/tasks", "/admin/audit", "/tasks/new", f"/tasks/{task_id}/events",
                 f"/tasks/{task_id}/artifacts/upload?path={slot['upload_id']}"]:
        assert client.get(path).status_code == 200, path

    resp = client.post(f"/api/v1/tasks/{task_id}/cancel", headers=api).json()
    assert resp["status"] == "cancelled"
    final = client.get(f"/api/v1/tasks/{task_id}", headers=api).json()
    assert final["status"] == "cancelled" and "result" in final and "billing" not in final

    actions = [a for a in re.findall(r'<td class="mono small">([a-z_.]+)</td>', client.get("/audit").text)]
    for expected in ("auth.register", "apikey.create", "settings.update", "upload.create", "task.create", "task.cancel"):
        assert expected in actions, expected


def test_isolation_and_validation(client, env):
    register(client)
    key = make_key(client)
    task_id = client.post("/api/v1/tasks", json={"task": "x"}, headers={"Authorization": f"Bearer {key}"}).json()["id"]
    client.post("/logout", data={"csrf": csrf_of(client, "/dashboard")})
    register(client, "user2@example.com")
    other_key = make_key(client)
    other = {"Authorization": f"Bearer {other_key}"}
    assert client.get(f"/api/v1/tasks/{task_id}", headers=other).status_code == 404
    assert client.get(f"/tasks/{task_id}").status_code == 404
    assert client.get("/admin").status_code == 403
    assert client.get("/admin/providers").status_code == 403
    assert client.get("/api/v1/tasks", headers={"Authorization": "Bearer dlg_nope"}).status_code == 401

    bad = client.post("/api/v1/tasks", json={"task": "x", "files": [{"path": "../etc/passwd", "content": "x"}]},
                      headers={"Authorization": f"Bearer {key}"})
    assert bad.status_code == 422
    assert client.post("/api/v1/uploads", json={"dest": "/abs"}, headers=other).status_code == 422
    slot = client.post("/api/v1/uploads", json={"dest": "data.bin"}, headers=other).json()
    client.put(slot["upload_url"].replace("http://testserver", ""), content=b"\x00\x01binary")
    resp = client.post("/api/v1/tasks", json={"task": "x", "upload_ids": [slot["upload_id"]]},
                       headers={"Authorization": f"Bearer {key}"})
    assert resp.status_code == 422
    assert client.get("/api/v1/downloads/forged/x.patch").status_code == 403


def test_provider_credentials_are_encrypted(client, env):
    from delegate.db import session_scope
    from delegate.models import ProviderConfig
    from delegate.security import decrypt

    register(client)
    token = csrf_of(client, "/admin/providers")
    client.post("/admin/providers/openai", data={"csrf": token, "base_url": "https://openai.example.com/v1",
                                                "api_key": "sk-private", "enabled": "on"})
    with session_scope() as db:
        row = db.get(ProviderConfig, "openai")
        assert row.api_key_enc != "sk-private" and decrypt(row.api_key_enc) == "sk-private"
        assert row.base_url == "https://openai.example.com/v1" and row.enabled


def test_raw_file_upload_needs_destination(client, env):
    register(client)
    key = make_key(client)
    slot = client.post("/api/v1/uploads", json={"dest": "."}, headers={"Authorization": f"Bearer {key}"}).json()
    resp = client.put(slot["upload_url"].replace("http://testserver", ""), content=b"just text")
    assert resp.status_code == 400 and "destination" in resp.json()["error"]


def test_console_api_matches_site_flow(client, env):
    session = client.get("/api/console/session")
    assert session.status_code == 200
    csrf = session.json()["csrf"]
    assert session.json()["user"] is None
    assert client.get("/api/console/dashboard").status_code == 401

    created = client.post("/api/console/register", headers={"X-CSRF-Token": csrf}, json={
        "email": "console@example.com", "password": "password123", "display_name": "Console User",
    })
    assert created.status_code == 200, created.text
    body = created.json()
    assert body["user"]["is_admin"] is True and body["user"]["display_name"] == "Console User"
    csrf = body["csrf"]

    dash = client.get("/api/console/dashboard").json()
    assert dash["total"] == 0 and dash["sandbox"]["capacity"] >= 1

    task = client.post("/api/console/tasks", headers={"X-CSRF-Token": csrf}, json={
        "task": "Fix the failing test\nmore", "harness": "codex",
    })
    assert task.status_code == 201, task.text
    task_id = task.json()["id"]
    assert task.json()["status"] == "queued"
    assert task.json()["harness"] == "codex"
    assert task.json()["prompt"].startswith("Fix the failing test")
    assert task.json()["events"] == []

    listed = client.get("/api/console/tasks").json()["tasks"]
    assert listed[0]["id"] == task_id
    detail = client.get(f"/api/console/tasks/{task_id}").json()
    assert detail["model"]
    events = client.get(f"/api/console/tasks/{task_id}/events").json()
    assert events["finished"] is False and events["events"] == []

    cancelled = client.post(f"/api/console/tasks/{task_id}/cancel", headers={"X-CSRF-Token": csrf})
    assert cancelled.status_code == 200
    assert client.get(f"/api/console/tasks/{task_id}").json()["status"] == "cancelled"

    key = client.post("/api/console/keys", headers={"X-CSRF-Token": csrf}, json={"name": "laptop"})
    assert key.status_code == 201 and key.json()["token"].startswith("dlg_")
    visible = client.get("/api/console/keys").json()["keys"]
    assert visible[0]["name"] == "laptop" and "token" not in visible[0]
    revoked = client.post(f"/api/console/keys/{visible[0]['id']}/revoke", headers={"X-CSRF-Token": csrf})
    assert revoked.json()["key"]["active"] is False

    providers = client.get("/api/console/providers").json()
    assert {row["id"] for row in providers["providers"]} == {"anthropic", "openai", "gemini"}
    saved = client.post("/api/console/providers/openai", headers={"X-CSRF-Token": csrf}, json={
        "base_url": "https://openai.example.com/v1", "api_key": "sk-private", "enabled": True,
    })
    assert saved.status_code == 200
    openai = next(row for row in saved.json()["providers"] if row["id"] == "openai")
    assert openai["base_url"] == "https://openai.example.com/v1" and openai["configured"]
    assert "sk-private" not in saved.text
    check = client.post("/api/console/providers/openai/check", headers={"X-CSRF-Token": csrf})
    assert check.json()["ok"] is True

    actions = [row["action"] for row in client.get("/api/console/audit").json()["logs"]]
    for expected in ("auth.register", "task.create", "task.cancel", "apikey.create", "apikey.revoke", "admin.provider_update"):
        assert expected in actions, expected

    client.post("/api/console/logout", headers={"X-CSRF-Token": csrf})
    assert client.get("/api/console/tasks").status_code == 401


def test_csrf_required(client, env):
    resp = client.post("/login", data={"email": "a@b.c", "password": "x"})
    assert resp.status_code == 403
