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
    return resp


def make_key(client) -> str:
    token = csrf_of(client, "/keys")
    page = client.post("/keys", data={"csrf": token, "name": "laptop"}).text  # shown once, after the redirect
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

    # no balance yet -> 402 from the billing gateway check
    resp = client.post("/api/v1/tasks", json={"task": "do something"}, headers=api)
    assert resp.status_code == 402, resp.text

    # first user is admin: credit 10 USD through the admin page
    token = csrf_of(client, "/admin/users/1")
    client.post("/admin/users/1/adjust", data={"csrf": token, "amount_usd": "10", "direction": "add"})
    assert client.get("/api/v1/me", headers=api).json()["balance_usd"] == 10.0

    # upload a project archive through a one-time URL
    slot = client.post("/api/v1/uploads", json={"dest": "."}, headers=api).json()
    upload_path = slot["upload_url"].replace("http://testserver", "")
    resp = client.put(upload_path, content=tgz({"src/app.py": b"print('hi')\n"}))
    assert resp.status_code == 200 and resp.json()["status"] == "ready" and resp.json()["kind"] == "tgz"
    assert client.put(upload_path, content=b"again").status_code == 409

    resp = client.post(
        "/api/v1/tasks",
        json={"task": "Fix the bug\nmore details", "upload_ids": [slot["upload_id"]],
              "files": [{"path": "notes/readme.txt", "content": "hello"}]},
        headers={**api, "X-Delegate-Client": "claude-code/9.9"},
    )
    assert resp.status_code == 201, resp.text
    view = resp.json()
    assert view["status"] == "queued" and view["title"] == "Fix the bug" and view["queue_position"] == 1
    assert set(view) <= {"id", "title", "status", "created_at", "finished_at", "duration_s", "audit_url",
                         "queue_position"}  # no execution details leak to the delegating side
    task_id = view["id"]
    assert client.get(f"/api/v1/tasks/{task_id}/wait?timeout=0", headers=api).json()["status"] == "queued"
    assert client.get("/api/v1/tasks", headers=api).json()["tasks"][0]["id"] == task_id

    # the web site shows everything
    detail = client.get(f"/tasks/{task_id}").text
    assert "Fix the bug" in detail and "claude-code/9.9" in detail and slot["upload_id"] in detail
    for path in ["/tasks", "/billing", "/settings", "/audit", "/keys", "/admin", "/admin/users", "/admin/users/1",
                 "/admin/tasks", "/admin/codes", "/admin/audit", "/tasks/new", f"/tasks/{task_id}/events",
                 f"/tasks/{task_id}/billing", f"/tasks/{task_id}/artifacts/upload?path={slot['upload_id']}"]:
        assert client.get(path).status_code == 200, path

    resp = client.post(f"/api/v1/tasks/{task_id}/cancel", headers=api).json()
    assert resp["status"] == "cancelled"
    final = client.get(f"/api/v1/tasks/{task_id}", headers=api).json()
    assert final["status"] == "cancelled" and "result" in final

    actions = [a for a in re.findall(r'<td class="mono small">([a-z_.]+)</td>', client.get("/audit").text)]
    for expected in ("auth.register", "apikey.create", "billing.adjust", "upload.create", "upload.receive",
                     "task.create", "task.cancel"):
        assert expected in actions, expected


def test_isolation_and_validation(client, env):
    register(client)
    key = make_key(client)
    token = csrf_of(client, "/admin/users/1")
    client.post("/admin/users/1/adjust", data={"csrf": token, "amount_usd": "5", "direction": "add"})
    task_id = client.post("/api/v1/tasks", json={"task": "x"}, headers={"Authorization": f"Bearer {key}"}).json()["id"]

    client.post("/logout", data={"csrf": csrf_of(client, "/dashboard")})
    register(client, "user2@example.com")
    other_key = make_key(client)
    other = {"Authorization": f"Bearer {other_key}"}
    assert client.get(f"/api/v1/tasks/{task_id}", headers=other).status_code == 404
    assert client.get(f"/tasks/{task_id}").status_code == 404
    assert client.get("/admin").status_code == 403
    assert client.get("/api/v1/tasks", headers={"Authorization": "Bearer dlg_nope"}).status_code == 401

    bad = client.post("/api/v1/tasks", json={"task": "x", "files": [{"path": "../etc/passwd", "content": "x"}]},
                      headers={"Authorization": f"Bearer {key}"})
    assert bad.status_code == 422
    assert client.post("/api/v1/uploads", json={"dest": "/abs"}, headers=other).status_code == 422
    # someone else's upload id cannot be attached
    slot = client.post("/api/v1/uploads", json={"dest": "data.bin"}, headers=other).json()
    client.put(slot["upload_url"].replace("http://testserver", ""), content=b"\x00\x01binary")
    resp = client.post("/api/v1/tasks", json={"task": "x", "upload_ids": [slot["upload_id"]]},
                       headers={"Authorization": f"Bearer {key}"})
    assert resp.status_code == 422
    assert client.get("/api/v1/downloads/forged/x.patch").status_code == 403


def test_raw_file_upload_needs_destination(client, env):
    register(client)
    key = make_key(client)
    slot = client.post("/api/v1/uploads", json={"dest": "."}, headers={"Authorization": f"Bearer {key}"}).json()
    resp = client.put(slot["upload_url"].replace("http://testserver", ""), content=b"just text")
    assert resp.status_code == 400 and "destination" in resp.json()["error"]


def test_csrf_required(client, env):
    resp = client.post("/login", data={"email": "a@b.c", "password": "x"})
    assert resp.status_code == 403
