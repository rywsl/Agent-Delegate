"""Bring-your-own-key fallback, sandbox time billing, and the admission queue."""

from __future__ import annotations

from delegate.security import encrypt


def test_console_register_grants_free_sandbox_time(client):
    session = client.get("/api/console/session").json()
    created = client.post(
        "/api/console/register",
        json={"email": "console@example.com", "password": "password1", "display_name": "Console"},
        headers={"X-CSRF-Token": session["csrf"]},
    )
    assert created.status_code == 200, created.text
    body = created.json()
    assert body["user"]["is_admin"] is True
    assert body["user"]["sandbox_free_seconds"] == 3600
    assert body["user"]["billing_mode"] == "platform"
    home = client.get("/api/console/dashboard")
    assert home.status_code == 200
    assert home.json()["queue"]["per_user"] == 8


def test_package_list_is_unpinned_and_matches_the_image():
    from pathlib import Path

    from delegate.harness import NPM_PACKAGES

    text = (Path(__file__).resolve().parents[2] / "sandbox" / "cli-packages.txt").read_text().split()
    assert text == list(NPM_PACKAGES)
    assert all("@" not in name.split("/")[-1] or not name.split("@")[-1][:1].isdigit() for name in NPM_PACKAGES)


def test_recharge_converts_usd_to_points_and_sandbox_spends_points(env):
    from delegate import billing
    from delegate.config import get_settings
    from delegate.db import session_scope
    from delegate.models import Task, User, utcnow
    from delegate.security import hash_password
    from delegate.site import POINTS_PER_USD_KEY, SANDBOX_POINTS_KEY, put

    with session_scope() as db:
        put(db, POINTS_PER_USD_KEY, "80")
        put(db, SANDBOX_POINTS_KEY, "2")
        user = User(email="points@example.com", display_name="p", password_hash=hash_password("password1"),
                    sandbox_free_seconds=60, points=0)
        db.add(user)
        db.flush()
        [code] = billing.create_codes(db, get_settings().usd_to_quota(2), 1, actor="admin:1")
        billing.redeem(db, user, code, actor="user:1")
        assert user.points == 160
        assert billing.balance_quota(user) == get_settings().usd_to_quota(2)

        put(db, POINTS_PER_USD_KEY, "50")
        [again] = billing.create_codes(db, get_settings().usd_to_quota(1), 1, actor="admin:1")
        billing.redeem(db, user, again, actor="user:1")
        assert user.points == 210

        task = Task(
            id="t_points", user_id=user.id, title="t", prompt="p", source="api", agent="claude", model="m",
            budget_quota=1, timeout_s=60, max_turns=1, billing_mode="byok", sandbox_started_at=utcnow(),
        )
        db.add(task)
        billing.charge_sandbox(db, task, 130)
        assert task.sandbox_billed_seconds == 180
        assert task.sandbox_free_seconds_used == 60
        assert task.sandbox_billed_points == 4
        assert task.sandbox_billed_quota == 0
        assert user.sandbox_free_seconds == 0
        assert user.points == 206

        user.points = 1
        billing.charge_sandbox(db, task, 120)
        assert task.sandbox_billed_points == 1
        assert user.points == 0
        assert "short by 3 points" in (task.status_reason or "")


def test_sandbox_charge_spends_free_time_before_the_wallet():
    from delegate.billing import sandbox_charge_parts

    billed, free_used, quota = sandbox_charge_parts(61, 60, 0.02, 500_000)
    assert (billed, free_used) == (120, 60)
    assert quota == 500_000 * 0.02  # one paid minute
    assert sandbox_charge_parts(0, 60, 0.02, 500_000) == (0, 0, 0)


def test_custom_key_is_the_fallback_and_sandbox_time_is_charged(env, fake_docker):
    from delegate import billing, tasks, worker
    from delegate.db import session_scope
    from delegate.models import Task, User, UserProviderKey
    from delegate.security import hash_password

    with session_scope() as db:
        user = User(email="byok@example.com", display_name="b", password_hash=hash_password("password1"),
                    sandbox_free_seconds=120)
        db.add(user)
        db.flush()
        db.add(UserProviderKey(user_id=user.id, provider="anthropic", api_key_enc=encrypt("sk-ant-user"),
                               base_url="https://api.anthropic.com", enabled=True))
        task = tasks.create_task(db, user, tasks.TaskInput(task="edit the readme"), source="api")
        task_id = task.id
        assert task.billing_mode == "byok"
        assert task.timeout_s == 120

    env.consume = lambda *args, **kwargs: None
    worker.Worker().claim_next()
    worker.run_task(task_id)
    spec = fake_docker["specs"][0]
    assert spec.spec["auth"]["mode"] == "byok"
    assert "DELEGATE_LLM_API_KEY" not in str(spec.spec)
    assert "sk-ant-user" not in str(spec.spec)
    assert spec.gateway_key == "sk-ant-user"
    with session_scope() as db:
        task = db.get(Task, task_id)
        user = db.query(User).one()
        assert task.status == "succeeded", task.status_reason
        assert task.newapi_token_id is None
        assert task.sandbox_billed_seconds == 60
        assert task.sandbox_free_seconds_used == 60
        assert user.sandbox_free_seconds == 60
        assert task.sandbox_billed_quota == 0


def test_missing_custom_key_falls_back_to_the_platform(env):
    from delegate import billing, tasks
    from delegate.db import session_scope
    from delegate.models import User
    from delegate.security import hash_password

    with session_scope() as db:
        user = User(email="plat@example.com", display_name="p", password_hash=hash_password("password1"))
        db.add(user)
        db.flush()
        billing.adjust(db, user, 1_000_000, kind="admin_grant", actor="test")
        task = tasks.create_task(db, user, tasks.TaskInput(task="use the platform"), source="api")
        assert task.billing_mode == "platform"


def test_queue_rejects_a_stampede(env, monkeypatch):
    from delegate import billing, tasks
    from delegate.db import session_scope
    from delegate.models import User
    from delegate.security import hash_password
    from delegate.site import MAX_QUEUED_USER_KEY, put

    with session_scope() as db:
        user = User(email="q@example.com", display_name="q", password_hash=hash_password("password1"))
        db.add(user)
        db.flush()
        billing.adjust(db, user, 5_000_000, kind="admin_grant", actor="test")
        put(db, MAX_QUEUED_USER_KEY, "1")
        tasks.create_task(db, user, tasks.TaskInput(task="first"), source="api")
        try:
            tasks.create_task(db, user, tasks.TaskInput(task="second"), source="api")
            raised = False
        except tasks.QueueFull:
            raised = True
        assert raised


def test_admin_can_add_a_channel_without_opening_new_api(env):
    from delegate import billing
    from delegate.web.routes_console import admin_channels, admin_channel_create, ChannelIn

    billing.bootstrap()
    admin_channel_create(ChannelIn(name="anthropic", type=14, key="sk-upstream", models="claude-sonnet-5-5"), user=None)
    listed = admin_channels(user=None)
    assert listed["channels"][0]["name"] == "anthropic"
    assert listed["channels"][0]["key"] if False else "key" not in listed["channels"][0]
    assert listed["channels"][0]["has_key"] is True


def test_runner_keeps_telemetry_off_and_keys_out_of_argv(tmp_path, monkeypatch):
    import importlib.util
    from pathlib import Path

    runner_path = Path(__file__).resolve().parents[2] / "sandbox" / "runner.py"
    spec = importlib.util.spec_from_file_location("sandbox_runner_billing", runner_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("DELEGATE_LLM_API_KEY", "sk-secret-key")
    auth = {"mode": "byok", "base_url": "https://example.invalid"}
    spec_body = {"model": "m", "max_turns": 3, "system_prompt": "sys", "prompt": "do it", "auth": auth}
    for builder in (module.claude_command, module.gemini_command, module.grok_command, module.pi_command, module.deepseek_command):
        cmd, env, _prompt = builder(spec_body)
        assert "sk-secret-key" not in " ".join(cmd)
        assert env["DISABLE_TELEMETRY"] == "1"
        assert env["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"] == "1"
    cmd, env, prompt = module.codex_command(spec_body)
    assert "sk-secret-key" not in " ".join(cmd)
    assert env["DISABLE_TELEMETRY"] == "1"
    assert "enabled = false" in (tmp_path / ".codex" / "config.toml").read_text()
    assert prompt


def test_console_deep_link_serves_the_spa(client):
    import pytest

    from delegate.web.app import _console_dist

    dist = _console_dist()
    if dist is None:
        pytest.skip("console dist not built")
    page = client.get("/app/admin")
    assert page.status_code == 200
    assert 'id="root"' in page.text
    home = client.get("/app/")
    assert home.status_code == 200
    assert 'id="root"' in home.text
    escaped = client.get("/app/../../etc/passwd")
    assert "root:" not in escaped.text
