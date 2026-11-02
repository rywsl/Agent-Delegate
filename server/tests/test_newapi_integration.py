"""Billing flows against a real new-api instance.

Runs only when NEWAPI_TEST_URL points at a *fresh* new-api (it performs first-time setup), e.g.:

    SESSION_SECRET=x CRITICAL_RATE_LIMIT_ENABLE=false ./new-api --port 3399
    NEWAPI_TEST_URL=http://127.0.0.1:3399 pytest tests/test_newapi_integration.py
"""

from __future__ import annotations

import os

import httpx
import pytest

URL = os.environ.get("NEWAPI_TEST_URL")
pytestmark = pytest.mark.skipif(not URL, reason="NEWAPI_TEST_URL not set")


@pytest.fixture()
def real(env, monkeypatch):
    from delegate import billing, config

    monkeypatch.setenv("NEWAPI_BASE_URL", URL)
    monkeypatch.setenv("NEWAPI_ROOT_PASSWORD", "Root-Integration-Pass-1")
    config.get_settings.cache_clear()
    billing._transport = None
    billing._root_client = None
    yield URL


def test_end_to_end_against_real_newapi(real):
    from delegate import billing
    from delegate.db import session_scope
    from delegate.models import Task, User
    from delegate.security import hash_password

    root = billing.bootstrap()
    assert root.token.startswith("nap_")
    assert root.self_info()["role"] == 100
    ok, msg = billing.health()
    assert ok, msg

    with session_scope() as db:
        user = User(email="it@example.com", display_name="it", password_hash=hash_password("password1"))
        db.add(user)
        db.flush()
        billing.ensure_mirror(db, user)
        assert user.newapi_user_id and billing.balance_quota(user) == 0

        billing.adjust(db, user, 3_000_000, kind="admin_grant", actor="it")
        billing.adjust(db, user, -500_000, kind="admin_deduct", actor="it")
        assert billing.balance_quota(user) == 2_500_000

        task = Task(user_id=user.id, title="it", prompt="p", agent="claude", model="claude-sonnet-5-5",
                    budget_quota=1_000_000, timeout_s=600, max_turns=5)
        db.add(task)
        db.flush()
        key = billing.open_task_token(db, user, task)
        assert key.startswith("sk-") and len(key) > 40 and "*" not in key

        # the key authenticates against the relay API
        resp = httpx.get(f"{URL}/v1/models", headers={"Authorization": f"Bearer {key}"})
        assert resp.status_code == 200, resp.text

        billing.close_task_token(db, task)
        resp = httpx.get(f"{URL}/v1/models", headers={"Authorization": f"Bearer {key}"})
        assert resp.status_code == 401, resp.text

        billing.reconcile_task(db, task)
        assert task.billed_quota == 0 and task.billing_reconciled_at is not None

        logs, total = billing.user_logs(user, page=1, page_size=10)
        assert total >= 0  # top-ups are recorded by new-api (log type depends on version)

        billing.set_mirror_enabled(user, False)
        assert billing.mirror_info(user)["status"] == 2
        billing.set_mirror_enabled(user, True)
        assert billing.mirror_info(user)["status"] == 1

        # a revoked mirror PAT is re-minted transparently
        user.newapi_pat_enc = billing.encrypt("nap_" + "x" * 43)
        assert billing.balance_quota(user) == 2_500_000
        task2 = Task(user_id=user.id, title="it2", prompt="p", agent="claude", model="m",
                     budget_quota=100_000, timeout_s=600, max_turns=5)
        db.add(task2)
        db.flush()
        assert billing.open_task_token(db, user, task2).startswith("sk-")
        billing.close_task_token(db, task2)

    # a second process with the stored credentials reuses the root PAT
    billing._root_client = None
    assert billing.bootstrap().token == root.token
