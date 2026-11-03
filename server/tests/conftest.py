from __future__ import annotations

import io
import os
import sys
import tarfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
os.environ.setdefault("DELEGATE_SECRET_KEY", "test-secret-key")


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("DELEGATE_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("DELEGATE_PUBLIC_URL", "http://testserver")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-provider-key")

    from delegate import config, db, sandbox, security

    config.get_settings.cache_clear()
    db.get_engine.cache_clear()
    db._session_factory.cache_clear()
    security._fernet.cache_clear()
    sandbox.docker_client.cache_clear()
    db.init_db()
    yield
    db.get_engine().dispose()


@pytest.fixture()
def fake_docker(env, monkeypatch):
    from streams import PATCH, claude_run_lines
    from delegate import sandbox

    state = {"lines": claude_run_lines(outputs={"count": 1, "files": [{"path": "report.md", "size": 11}]}),
             "exit": 0, "specs": [], "removed": 0}

    class FakeContainer:
        id = "c0ffee" * 10
        name = "delegate-test"

    def create_and_start(spec):
        state["specs"].append(spec)
        return FakeContainer()

    def stream_lines(container):
        for line in state["lines"]:
            yield "2026-11-02T08:00:00.123456789Z", line

    def fetch_file(container, path, dest, max_bytes):
        dest.parent.mkdir(parents=True, exist_ok=True)
        if path == sandbox.PATCH_PATH:
            dest.write_bytes(PATCH.encode())
        else:
            buf = io.BytesIO()
            with tarfile.open(fileobj=buf, mode="w:gz") as tar:
                data = b"# report\nok"
                info = tarfile.TarInfo("report.md")
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))
            dest.write_bytes(buf.getvalue())
        return dest.stat().st_size

    monkeypatch.setattr(sandbox, "create_and_start", create_and_start)
    monkeypatch.setattr(sandbox, "stream_lines", stream_lines)
    monkeypatch.setattr(sandbox, "wait_exit", lambda c: state["exit"])
    monkeypatch.setattr(sandbox, "fetch_file", fetch_file)
    monkeypatch.setattr(sandbox, "remove", lambda c: state.__setitem__("removed", state["removed"] + 1))
    monkeypatch.setattr(sandbox, "find_task_containers", lambda: {})
    return state


@pytest.fixture()
def client(env):
    from fastapi.testclient import TestClient
    from delegate.web.app import create_app

    with TestClient(create_app()) as c:
        yield c
