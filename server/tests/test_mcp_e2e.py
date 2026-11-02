"""MCP protocol end to end: MCP client -> MCP gateway (HTTP) -> web API (HTTP) -> worker (fake Docker)."""

from __future__ import annotations

import io
import re
import socket
import tarfile
import threading
import time

import httpx
import httpx2
import pytest
import uvicorn
from streams import PATCH

from mcp.client.client import Client
from mcp.client.streamable_http import streamable_http_client


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _serve(app, port: int) -> uvicorn.Server:
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    for _ in range(200):
        if server.started:
            return server
        time.sleep(0.05)
    raise RuntimeError("server did not start")


@pytest.fixture()
def stack(env, fake_docker, monkeypatch):
    from delegate import billing, config
    from delegate.db import session_scope
    from delegate.models import ApiKey, User
    from delegate.security import generate_api_key, hash_password

    web_port, mcp_port = _free_port(), _free_port()
    monkeypatch.setenv("DELEGATE_PUBLIC_URL", f"http://127.0.0.1:{web_port}")
    config.get_settings.cache_clear()

    from delegate.web.app import create_app
    import delegate_mcp.server as gateway

    monkeypatch.setattr(gateway, "API_URL", f"http://127.0.0.1:{web_port}")
    web = _serve(create_app(), web_port)
    mcp = _serve(gateway.build_app(), mcp_port)

    with session_scope() as db:
        user = User(email="mcp@example.com", display_name="m", password_hash=hash_password("password1"))
        db.add(user)
        db.flush()
        billing.adjust(db, user, 10_000_000, kind="admin_grant", actor="test")
        plaintext, prefix, digest = generate_api_key()
        db.add(ApiKey(user_id=user.id, name="t", prefix=prefix, key_hash=digest))
    yield {"url": f"http://127.0.0.1:{mcp_port}/mcp", "key": plaintext}
    web.should_exit = mcp.should_exit = True


def _client(url: str, key: str | None) -> Client:
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    return Client(streamable_http_client(url, http_client=httpx2.AsyncClient(headers=headers, timeout=60)))


def _text(result) -> str:
    return "\n".join(c.text for c in result.content if getattr(c, "type", "") == "text")


async def test_delegate_wait_and_fetch(stack):
    from delegate import worker

    async with _client(stack["url"], stack["key"]) as client:
        tools = {t.name for t in (await client.list_tools()).tools}
        assert tools == {"create_upload", "delegate_task", "wait_task", "cancel_task", "list_tasks"}

        upload = _text(await client.call_tool("create_upload", {"dest": "."}))
        upload_id = re.search(r"upload_id: (u_[0-9a-f]+)", upload).group(1)
        upload_url = re.search(r"curl -fsS -T - '([^']+)'", upload).group(1)
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tar:
            info = tarfile.TarInfo("app.py")
            info.size = 9
            tar.addfile(info, io.BytesIO(b"print(1)\n"))
        assert httpx.put(upload_url, content=buf.getvalue()).json()["status"] == "ready"

        first = await client.call_tool("delegate_task", {
            "task": "Change app.py to print 2 and write a report to /outputs/report.md",
            "upload_ids": [upload_id], "wait_seconds": 1,
        })
        text = _text(first)
        assert not first.is_error, text
        task_id = re.search(r"Task (t_[0-9a-f]+) is (queued|preparing|running)", text).group(1)
        assert "wait_task" in text

        # the worker picks the task up and runs it in the (fake) sandbox
        w = worker.Worker()
        assert w.claim_next() == task_id
        await_thread = threading.Thread(target=worker.run_task, args=(task_id,))
        await_thread.start()
        result = await client.call_tool("wait_task", {"task_id": task_id, "wait_seconds": 30})
        await_thread.join()
        text = _text(result)
        assert f"Task {task_id} succeeded" in text, text
        assert "## Report" in text and "```diff" in text and "report.md" in text
        assert "Bash" not in text and "pytest" not in text  # no execution trail leaks out

        patch_url = re.search(r"curl -fsSL '([^']+\.patch)'", text).group(1)
        assert httpx.get(patch_url).text == PATCH
        listing = _text(await client.call_tool("list_tasks", {"limit": 5}))
        assert task_id in listing and "succeeded" in listing

        bad = await client.call_tool("cancel_task", {"task_id": "t_doesnotexist"})
        assert bad.is_error and "not found" in _text(bad)


async def test_missing_or_bad_key(stack):
    async with _client(stack["url"], None) as client:
        result = await client.call_tool("list_tasks", {})
        assert result.is_error and "API key" in _text(result)
    async with _client(stack["url"], "dlg_wrong") as client:
        result = await client.call_tool("list_tasks", {})
        assert result.is_error and "invalid or revoked API key" in _text(result)
