from __future__ import annotations

import pytest


def _user(db, email="a@example.com"):
    from delegate.models import User
    from delegate.security import hash_password

    user = User(email=email, display_name="a", password_hash=hash_password("password1"))
    db.add(user)
    db.flush()
    return user


def _task(db, user, budget=2_500_000):
    from delegate.models import Task

    task = Task(user_id=user.id, title="t", prompt="p", agent="claude", model="claude-sonnet-5-5",
                budget_quota=budget, timeout_s=600, max_turns=10)
    db.add(task)
    db.flush()
    return task


def test_bootstrap_runs_setup_and_mints_scoped_root_pat(env):
    from delegate import billing
    from delegate.newapi import ROOT_PAT_SCOPES

    client = billing.bootstrap()
    assert env.setup_done
    root = next(u for u in env.users.values() if u["role"] == 100)
    pat = env.pats[client.token]
    assert pat["user_id"] == root["id"] and pat["scopes"] == sorted(ROOT_PAT_SCOPES)
    assert env.options["RegisterEnabled"] == "false"
    # a second bootstrap reuses the stored PAT instead of minting another one
    billing._root_client = None
    assert billing.bootstrap().token == client.token
    assert len(env.pats) == 1


def test_bootstrap_rotates_rejected_pat(env):
    from delegate import billing

    first = billing.bootstrap().token
    env.pats.clear()  # e.g. revoked in the new-api console
    billing._root_client = None
    second = billing.bootstrap().token
    assert second != first and second in env.pats


def test_mirror_provisioning_is_idempotent(env):
    from delegate import billing
    from delegate.db import session_scope
    from delegate.newapi import MIRROR_PAT_SCOPES

    with session_scope() as db:
        user = _user(db)
        billing.ensure_mirror(db, user)
        mirror = env.users[user.newapi_user_id]
        assert mirror["username"] == user.newapi_username and mirror["role"] == 1
        assert env.pats[billing.decrypt(user.newapi_pat_enc)]["scopes"] == sorted(MIRROR_PAT_SCOPES)
        # simulate a crash after the account was created but before the site stored the PAT
        user.newapi_user_id = None
        user.newapi_pat_enc = None
        billing.ensure_mirror(db, user)
        assert user.newapi_user_id == mirror["id"]
        assert sum(1 for u in env.users.values() if u["username"] == mirror["username"]) == 1
        # the stale PAT of the same name was replaced, not accumulated
        assert sum(1 for p in env.pats.values() if p["user_id"] == mirror["id"]) == 1


def test_adjust_balance_and_insufficient_balance(env):
    from delegate import billing
    from delegate.db import session_scope
    from delegate.models import LedgerEntry

    with session_scope() as db:
        user = _user(db)
        with pytest.raises(billing.BillingError) as exc:
            billing.check_can_start(db, user)
        assert exc.value.status_code == 402
        billing.adjust(db, user, 1_000_000, kind="admin_grant", actor="admin:1")
        assert billing.balance_quota(user) == 1_000_000
        billing.adjust(db, user, -250_000, kind="admin_deduct", actor="admin:1")
        assert billing.balance_quota(user) == 750_000
        billing.check_can_start(db, user)
        assert [e.status for e in db.query(LedgerEntry).all()] == ["applied", "applied"]


def test_task_token_lifecycle_and_reconcile(env):
    from delegate import billing
    from delegate.db import session_scope

    with session_scope() as db:
        user = _user(db)
        billing.adjust(db, user, 5_000_000, kind="admin_grant", actor="admin:1")
        task = _task(db, user)
        key = billing.open_task_token(db, user, task)
        assert key.startswith("sk-") and "*" not in key
        token = env.tokens[task.newapi_token_id]
        assert token["name"] == f"task-{task.id}" and token["remain_quota"] == task.budget_quota

        env.consume(key, 120_000, prompt=9000, completion=800)
        env.consume(key, 80_000, prompt=7000, completion=500)
        billing.close_task_token(db, task)
        assert task.newapi_token_id not in env.tokens

        billing.reconcile_task(db, task)
        assert task.billed_quota == 200_000
        assert task.billed_prompt_tokens == 16_000 and task.billed_completion_tokens == 1300
        assert task.billed_requests == 2
        assert billing.balance_quota(user) == 5_000_000 - 200_000


def test_reconcile_adds_anthropic_cache_tokens(env):
    """Anthropic logs keep cache read/write outside prompt_tokens; OpenAI logs already include them."""
    from delegate import billing
    from delegate.db import session_scope

    with session_scope() as db:
        user = _user(db)
        billing.adjust(db, user, 5_000_000, kind="admin_grant", actor="admin:1")
        task = _task(db, user)
        key = billing.open_task_token(db, user, task)
        env.consume(key, 50_000, prompt=2, completion=20,
                    other={"usage_semantic": "anthropic", "cache_tokens": 1_000, "cache_write_tokens": 9_000})
        env.consume(key, 50_000, prompt=3_000, completion=20,
                    other={"usage_semantic": "openai", "cache_tokens": 1_000})
        billing.close_task_token(db, task)
        billing.reconcile_task(db, task)
        assert task.billed_prompt_tokens == 2 + 1_000 + 9_000 + 3_000
        assert task.billed_completion_tokens == 40


def test_parse_log_handles_gateway_variants():
    """Gateway logs differ per upstream protocol; broken payloads must never raise."""
    from delegate import billing

    def row(**kwargs):
        base = {"prompt_tokens": 10, "completion_tokens": 5}
        base.update(kwargs)
        return base

    assert billing.parse_log(row()) == billing.LogUsage(10, 5, 0, 0)
    # Anthropic: prompt excludes cache reads/writes (cache_creation_tokens is the older name)
    usage = billing.parse_log(row(other='{"usage_semantic":"anthropic","cache_tokens":4,"cache_creation_tokens":6}'))
    assert (usage.input_tokens, usage.cache_read_tokens, usage.cache_write_tokens) == (20, 4, 6)
    # OpenAI: prompt already contains the cached tokens, so nothing is added
    usage = billing.parse_log(row(prompt_tokens=100, other='{"usage_semantic":"openai","cache_tokens":90}'))
    assert usage.input_tokens == 100
    # new-api's normalised total wins over any add-back
    usage = billing.parse_log(row(other='{"usage_semantic":"anthropic","cache_tokens":4,"input_tokens_total":99}'))
    assert usage.input_tokens == 99
    # unparseable or hostile payloads degrade instead of breaking the page
    assert billing.parse_log(row(other="not-json")).input_tokens == 10
    assert billing.parse_log(row(other='{"cache_tokens":"1,000"}')).input_tokens == 10
    usage = billing.parse_log(row(prompt_tokens="12", completion_tokens=None))
    assert (usage.input_tokens, usage.output_tokens) == (12, 0)


def test_budget_exhausted_reason(env):
    from delegate import billing
    from delegate.db import session_scope

    with session_scope() as db:
        user = _user(db)
        billing.adjust(db, user, 5_000_000, kind="admin_grant", actor="admin:1")
        task = _task(db, user, budget=100_000)
        key = billing.open_task_token(db, user, task)
        env.consume(key, 100_000, prompt=1, completion=1)
        task.status, task.status_reason = "failed", "API error"
        billing.reconcile_task(db, task)
        assert task.status_reason.startswith("budget exhausted")


def test_redeem_codes_single_use(env):
    from delegate import billing
    from delegate.db import session_scope

    with session_scope() as db:
        user = _user(db)
        other = _user(db, "b@example.com")
        [code] = billing.create_codes(db, 500_000, 1, actor="admin:1")
        assert billing.redeem(db, user, code.lower(), actor="user:1") == 500_000
        assert billing.balance_quota(user) == 500_000
        with pytest.raises(billing.BillingError, match="already used"):
            billing.redeem(db, other, code, actor="user:2")
        with pytest.raises(billing.BillingError, match="invalid"):
            billing.redeem(db, other, "DLG-NOPE", actor="user:2")


def test_disable_mirror_uses_step_up_proof(env):
    from delegate import billing
    from delegate.db import session_scope

    with session_scope() as db:
        user = _user(db)
        billing.ensure_mirror(db, user)
        billing.set_mirror_enabled(user, False)
        assert env.users[user.newapi_user_id]["status"] == 2
        billing.set_mirror_enabled(user, True)
        assert env.users[user.newapi_user_id]["status"] == 1
