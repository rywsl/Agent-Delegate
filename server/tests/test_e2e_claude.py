"""Real Claude Code CLI -> real new-api (per-task key) -> scripted upstream, then billing reconciliation.

Opt-in: needs a running new-api (NEWAPI_TEST_URL, already initialised by test_newapi_integration or fresh)
and the `claude` CLI on PATH. Set CLAUDE_E2E=1. Uses a throwaway CLAUDE_CONFIG_DIR.
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
    not (URL and os.environ.get("CLAUDE_E2E") and shutil.which("claude")), reason="CLAUDE_E2E/NEWAPI_TEST_URL not set"
)
MOCK_PORT = 3398
# The mock upstream runs in this process; when new-api runs in a container, 127.0.0.1 is the
# container itself, so the gateway has to be pointed at something like host.docker.internal.
# MOCK_BASE_URL may use a {port} placeholder (the codex e2e test listens on another port).
MOCK_BASE_URL = os.environ.get("MOCK_BASE_URL", "http://127.0.0.1:{port}").replace("{port}", str(MOCK_PORT))
MODEL = "claude-sonnet-5-5"
ROOT_PASSWORD = "Root-Integration-Pass-1"
RUNNER = Path(__file__).resolve().parents[2] / "sandbox" / "runner.py"


def _root_session() -> httpx.Client:
    jwt = httpx.post(f"{URL}/api/user/login", json={"username": "root", "password": ROOT_PASSWORD}).json()
    return httpx.Client(base_url=URL, headers={"Authorization": f"Bearer {jwt['data']['access_token']}"})


def _ensure_channel_and_pricing(root_pat: str) -> None:
    with _root_session() as s:
        existing = s.get("/api/channel/", params={"p": 1, "page_size": 100}).json()
        items = (existing.get("data") or {}).get("items") or []
        channel = next((c for c in items if c.get("name") == "mock-anthropic"), None)
        if channel is not None and channel.get("base_url") != MOCK_BASE_URL:
            # a channel left by an earlier run still points at the old mock address; the update
            # endpoint rejects a full channel payload, so replace it instead
            assert s.delete(f"/api/channel/{channel['id']}").json()["success"]
            channel = None
        if channel is None:
            resp = s.post("/api/channel/", json={"mode": "single", "channel": {
                "type": 14, "name": "mock-anthropic", "key": "mock-upstream-key",
                "base_url": MOCK_BASE_URL, "models": f"{MODEL},claude-haiku-5-5",
                "group": "default", "status": 1}}).json()
            assert resp["success"], resp
    opts = httpx.Client(base_url=URL, headers={"Authorization": f"Bearer {root_pat}"})
    # price: ratio 1.5 => $3 / 1M input tokens; completion ratio 5 => $15 / 1M output tokens
    for key, value in (("ModelRatio", {MODEL: 1.5, "claude-haiku-5-5": 0.5}),
                       ("CompletionRatio", {MODEL: 5, "claude-haiku-5-5": 5})):
        resp = opts.put("/api/option/", json={"key": key, "value": json.dumps(value)}).json()
        assert resp["success"], resp


@pytest.fixture()
def real(env, monkeypatch):
    from delegate import billing, config

    monkeypatch.setenv("NEWAPI_BASE_URL", URL)
    monkeypatch.setenv("NEWAPI_ROOT_PASSWORD", ROOT_PASSWORD)
    config.get_settings.cache_clear()
    billing._transport = None
    billing._root_client = None
    from mock_upstream import serve_in_thread

    server = serve_in_thread(MOCK_PORT)
    yield
    server.should_exit = True


def test_claude_cli_through_gateway(real, tmp_path):
    from delegate import billing
    from delegate.db import session_scope
    from delegate.events import Normalizer
    from delegate.models import Task, User
    from delegate.security import hash_password
    from mock_upstream import INPUT_TOKENS, OUTPUT_TOKENS, Script

    root = billing.bootstrap()
    _ensure_channel_and_pricing(root.token)

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    Script.write_path = str(workspace / "hello.txt")
    Script.requests.clear()

    with session_scope() as db:
        user = User(email=f"e2e{os.getpid()}@example.com", display_name="e2e", password_hash=hash_password("password1"))
        db.add(user)
        db.flush()
        billing.adjust(db, user, 5_000_000, kind="admin_grant", actor="e2e")
        task = Task(user_id=user.id, title="e2e", prompt="Create hello.txt", agent="claude", model=MODEL,
                    budget_quota=1_000_000, timeout_s=600, max_turns=5)
        db.add(task)
        db.flush()
        key = billing.open_task_token(db, user, task)

        # Build the exact command line the sandbox runner uses.
        spec = importlib.util.spec_from_file_location("sandbox_runner", RUNNER)
        runner = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(runner)
        os.environ["DELEGATE_GATEWAY_KEY"] = key
        cmd, extra_env, prompt = runner.claude_command({
            "model": MODEL, "max_turns": 5, "system_prompt": "You are a delegated cloud agent.",
            "prompt": "Create hello.txt containing a greeting.", "gateway_url": URL,
        })
        env = {k: v for k, v in os.environ.items() if not k.startswith(("ANTHROPIC_", "CLAUDE_"))}
        env.update(extra_env)
        env["CLAUDE_CONFIG_DIR"] = str(tmp_path / "claude-config")
        exe = shutil.which("claude")
        proc = subprocess.run([exe, *cmd[1:]], input=prompt, capture_output=True, text=True, encoding="utf-8",
                              cwd=workspace, env=env, timeout=300)

        normalizer = Normalizer()
        events = []
        for line in proc.stdout.splitlines():
            if line.strip():
                try:
                    events += normalizer.feed_line(json.dumps({"t": "agent", "agent": "claude",
                                                               "event": json.loads(line)}))
                except json.JSONDecodeError:
                    pass
        kinds = [e.kind for e in events]
        assert proc.returncode == 0, (proc.stderr[-2000:], kinds)
        assert (workspace / "hello.txt").read_text() == "hello from the cloud agent\n"
        assert "system" in kinds and "tool_call" in kinds and "tool_result" in kinds and "agent_result" in kinds
        assert any(e.kind == "tool_call" and e.summary.startswith("Write:") for e in events)
        assert normalizer.final_message.startswith("## Report") and not normalizer.usage.is_error

        billing.close_task_token(db, task)
        billing.reconcile_task(db, task)
        main_calls = [r for r in Script.requests if r.get("tools")]
        assert len(main_calls) == 2
        assert task.billed_requests == len(Script.requests)
        assert task.billed_prompt_tokens == INPUT_TOKENS * len(Script.requests)
        assert task.billed_completion_tokens == OUTPUT_TOKENS * len(Script.requests)
        assert task.billed_quota > 0
        assert billing.balance_quota(user) == 5_000_000 - task.billed_quota
        print(f"\nclaude e2e: {len(Script.requests)} upstream calls, billed quota {task.billed_quota}, "
              f"events {kinds}")
