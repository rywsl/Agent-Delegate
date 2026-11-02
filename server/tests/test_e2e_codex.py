"""Real Codex CLI -> real new-api (per-task key, Responses API) -> scripted upstream -> billing.

Opt-in: NEWAPI_TEST_URL + CODEX_E2E=1 and `codex` on PATH. Uses a throwaway HOME/CODEX_HOME.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
from pathlib import Path

import httpx
import pytest

URL = os.environ.get("NEWAPI_TEST_URL")
pytestmark = pytest.mark.skipif(
    not (URL and os.environ.get("CODEX_E2E") and shutil.which("codex")), reason="CODEX_E2E/NEWAPI_TEST_URL not set"
)
MOCK_PORT = 3397
# The mock upstream runs in this process; when new-api runs in a container, 127.0.0.1 is the
# container itself, so the gateway has to be pointed at something like host.docker.internal.
# MOCK_BASE_URL may use a {port} placeholder (the claude e2e test listens on another port).
MOCK_BASE_URL = os.environ.get("MOCK_BASE_URL", "http://127.0.0.1:{port}").replace("{port}", str(MOCK_PORT))
MODEL = "gpt-5.5"
ROOT_PASSWORD = "Root-Integration-Pass-1"
RUNNER = Path(__file__).resolve().parents[2] / "sandbox" / "runner.py"


@pytest.fixture()
def real(env, monkeypatch):
    from delegate import billing, config
    from mock_upstream import serve_in_thread

    monkeypatch.setenv("NEWAPI_BASE_URL", URL)
    monkeypatch.setenv("NEWAPI_ROOT_PASSWORD", ROOT_PASSWORD)
    config.get_settings.cache_clear()
    billing._transport = None
    billing._root_client = None
    server = serve_in_thread(MOCK_PORT)
    yield
    server.should_exit = True


def _setup_gateway(root_pat: str) -> None:
    jwt = httpx.post(f"{URL}/api/user/login", json={"username": "root", "password": ROOT_PASSWORD}).json()
    with httpx.Client(base_url=URL, headers={"Authorization": f"Bearer {jwt['data']['access_token']}"}) as s:
        items = (s.get("/api/channel/", params={"p": 1, "page_size": 100}).json().get("data") or {}).get("items") or []
        channel = next((c for c in items if c.get("name") == "mock-openai"), None)
        if channel is not None and channel.get("base_url") != MOCK_BASE_URL:
            # a channel left by an earlier run still points at the old mock address; the update
            # endpoint rejects a full channel payload, so replace it instead
            assert s.delete(f"/api/channel/{channel['id']}").json()["success"]
            channel = None
        if channel is None:
            resp = s.post("/api/channel/", json={"mode": "single", "channel": {
                "type": 1, "name": "mock-openai", "key": "mock-upstream-key",
                "base_url": MOCK_BASE_URL, "models": MODEL, "group": "default", "status": 1}}).json()
            assert resp["success"], resp
    with httpx.Client(base_url=URL, headers={"Authorization": f"Bearer {root_pat}"}) as opts:
        for key, value in (("ModelRatio", {MODEL: 0.625, "claude-sonnet-5-5": 1.5, "claude-haiku-5-5": 0.5}),
                           ("CompletionRatio", {MODEL: 8, "claude-sonnet-5-5": 5, "claude-haiku-5-5": 5})):
            assert opts.put("/api/option/", json={"key": key, "value": json.dumps(value)}).json()["success"]


def test_codex_cli_through_gateway(real, tmp_path, monkeypatch):
    from delegate import billing
    from delegate.db import session_scope
    from delegate.events import Normalizer
    from delegate.models import Task, User
    from delegate.security import hash_password
    from mock_upstream import INPUT_TOKENS, OUTPUT_TOKENS, Script

    root = billing.bootstrap()
    _setup_gateway(root.token)
    Script.requests.clear()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    home = tmp_path / "home"
    home.mkdir()

    with session_scope() as db:
        user = User(email=f"codex{os.getpid()}@example.com", display_name="c", password_hash=hash_password("password1"))
        db.add(user)
        db.flush()
        billing.adjust(db, user, 5_000_000, kind="admin_grant", actor="e2e")
        task = Task(user_id=user.id, title="codex", prompt="check", agent="codex", model=MODEL,
                    budget_quota=1_000_000, timeout_s=600, max_turns=5)
        db.add(task)
        db.flush()
        key = billing.open_task_token(db, user, task)

        spec = importlib.util.spec_from_file_location("sandbox_runner", RUNNER)
        runner = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(runner)
        monkeypatch.setattr(runner, "WORKSPACE", workspace)
        monkeypatch.setenv("HOME", str(home))
        cmd, extra_env, prompt = runner.codex_command({
            "model": MODEL, "system_prompt": "You are a delegated cloud agent.", "prompt": "Check the workspace.",
            "gateway_url": URL,
        })
        env = {k: v for k, v in os.environ.items() if not k.startswith(("OPENAI_", "CODEX_"))}
        env.update(extra_env)
        env["DELEGATE_GATEWAY_KEY"] = key
        proc = subprocess.run([shutil.which("codex"), *cmd[1:]], input=prompt, capture_output=True, text=True,
                              encoding="utf-8", cwd=workspace, env=env, timeout=300)

        normalizer = Normalizer()
        events = []
        for line in proc.stdout.splitlines():
            try:
                events += normalizer.feed_line(json.dumps({"t": "agent", "agent": "codex", "event": json.loads(line)}))
            except json.JSONDecodeError:
                pass
        kinds = [e.kind for e in events]
        assert proc.returncode == 0, (proc.stderr[-3000:], kinds)
        assert kinds[0] == "system" and "message" in kinds and kinds[-1] == "usage", kinds
        assert normalizer.final_message.startswith("## Report")
        assert normalizer.usage.input_tokens == INPUT_TOKENS * len(Script.requests)

        billing.close_task_token(db, task)
        billing.reconcile_task(db, task)
        assert task.billed_requests == len(Script.requests) >= 1
        assert task.billed_prompt_tokens == INPUT_TOKENS * len(Script.requests)
        assert task.billed_completion_tokens == OUTPUT_TOKENS * len(Script.requests)
        assert task.billed_quota > 0 and billing.balance_quota(user) == 5_000_000 - task.billed_quota
        print(f"\ncodex e2e: {len(Script.requests)} upstream calls, billed quota {task.billed_quota}, events {kinds}")
