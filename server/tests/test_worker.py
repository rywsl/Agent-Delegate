"""Worker + sandbox lifecycle with Docker replaced by a fake container that replays an agent run."""

from __future__ import annotations

import io
import re
import tarfile

from streams import PATCH

def _submit(budget_usd=5.0):
    from delegate import billing, tasks
    from delegate.db import session_scope
    from delegate.models import User
    from delegate.security import hash_password

    with session_scope() as db:
        user = User(email="w@example.com", display_name="w", password_hash=hash_password("password1"),
                    pref_budget_usd=budget_usd)
        db.add(user)
        db.flush()
        billing.adjust(db, user, 10_000_000, kind="admin_grant", actor="test")
        task = tasks.create_task(db, user, tasks.TaskInput(task="fix app.py", files=[{"path": "a.txt", "content": "x"}]),
                                 source="api")
        return task.id


def test_successful_run(env, fake_docker, monkeypatch):
    from delegate import worker
    from delegate.db import session_scope
    from delegate.models import AuditLog, Task, TaskEvent

    task_id = _submit()
    w = worker.Worker()
    assert w.claim_next() == task_id
    worker.run_task(task_id)

    spec = fake_docker["specs"][0]
    assert spec.spec["agent"] == "claude" and spec.spec["gateway_url"] == "http://new-api:3000"
    assert "DELEGATE_GATEWAY_KEY" not in str(spec.spec) and spec.gateway_key.startswith("sk-")
    assert spec.files == {"a.txt": b"x"}
    assert fake_docker["removed"] == 1

    with session_scope() as db:
        task = db.get(Task, task_id)
        assert task.status == "succeeded", task.status_reason
        assert task.result_text.startswith("## Report")
        assert task.patch_stats["files"] == 1 and task.patch_stats["bytes"] == len(PATCH)
        assert task.outputs == [{"path": "report.md", "size": 11}]
        assert task.agent_usage["input_tokens"] == 4700
        assert task.newapi_token_id not in env.tokens  # gateway key revoked after the run
        kinds = [e.kind for e in db.query(TaskEvent).filter_by(task_id=task_id).order_by(TaskEvent.seq)]
        assert kinds[:3] == ["phase", "phase", "phase"] and "tool_call" in kinds and kinds[-1] == "phase"
        assert task.event_count == len(kinds)
        actions = {a.action for a in db.query(AuditLog).filter_by(target=task_id)}
        assert {"task.create", "billing.key_open", "billing.key_close", "task.finish"} <= actions

    monkeypatch.setattr(worker, "RECONCILE_DELAY_S", -5)
    w.reconcile_billing()
    with session_scope() as db:
        task = db.get(Task, task_id)
        assert task.billed_quota == 150_000 and task.billed_requests == 1
        assert task.billing_reconciled_at is not None
    assert worker.raw_log_path(task_id).read_text().count("\n") == len(fake_docker["lines"])


def test_deliverables_reach_the_delegating_agent(client, env, fake_docker):
    from delegate import tasks, worker
    from delegate.db import session_scope
    from delegate.models import Task
    from delegate_mcp.server import format_task

    task_id = _submit()
    worker.Worker().claim_next()
    worker.run_task(task_id)
    with session_scope() as db:
        view = tasks.public_view(db, db.get(Task, task_id))
    assert view["patch"]["inline"] == PATCH
    assert view["outputs"]["count"] == 1
    # signed links work without the API key, and only for what they were issued for
    patch_url = view["patch"]["url"].replace("http://testserver", "")
    assert client.get(patch_url).text == PATCH
    file_url = view["outputs"]["files"][0]["url"].replace("http://testserver", "")
    assert client.get(file_url).content == b"# report\nok"
    bundle = client.get(view["outputs"]["bundle_url"].replace("http://testserver", "")).content
    assert tarfile.open(fileobj=io.BytesIO(bundle)).getnames() == ["report.md"]

    # the owner sees the full audit trail on the web site
    html = client.get("/login").text
    csrf = re.search(r'name="csrf-token" content="([^"]+)"', html).group(1)
    client.post("/login", data={"csrf": csrf, "email": "w@example.com", "password": "password1"})
    page = client.get(f"/tasks/{task_id}")
    assert page.status_code == 200
    for fragment in ("<h2>Report</h2>", "print(2)", "report.md", "执行轨迹"):
        assert fragment in page.text, fragment
    events = client.get(f"/tasks/{task_id}/events").json()
    assert events["finished"] and any(e["summary"] == "Bash: pytest -q" for e in events["events"])
    billing_rows = client.get(f"/tasks/{task_id}/billing").json()["logs"]
    assert len(billing_rows) == 1 and billing_rows[0]["prompt_tokens"] == 12_000
    for artifact in ("patch", "outputs", "log", "output?path=report.md"):
        assert client.get(f"/tasks/{task_id}/artifacts/{artifact}").status_code == 200, artifact

    text = format_task(view)
    assert f"Task {task_id} succeeded" in text and "git apply" in text and "report.md" in text
    assert "```diff" in text and "Bash" not in text  # outcome only: no execution trail
    assert re.search(r"Audit trail \(for humans\): http://testserver/tasks/" + task_id, text)


def test_crashed_sandbox_marks_failure(env, fake_docker):
    from delegate import worker
    from delegate.db import session_scope
    from delegate.models import Task

    fake_docker["lines"] = fake_docker["lines"][:5]  # no finish envelope
    fake_docker["exit"] = 137
    task_id = _submit()
    worker.Worker().claim_next()
    worker.run_task(task_id)
    with session_scope() as db:
        task = db.get(Task, task_id)
        assert task.status == "failed" and "exit code 137" in task.status_reason
        assert task.newapi_token_id not in env.tokens


def test_insufficient_balance_fails_without_sandbox(env, fake_docker):
    from delegate import billing, worker
    from delegate.db import session_scope
    from delegate.models import Task, User

    task_id = _submit()
    with session_scope() as db:
        user = db.query(User).one()
        billing.adjust(db, user, -10_000_000, kind="admin_deduct", actor="test")
    worker.Worker().claim_next()
    worker.run_task(task_id)
    with session_scope() as db:
        task = db.get(Task, task_id)
        assert task.status == "failed" and "insufficient balance" in task.status_reason
    assert fake_docker["specs"] == []


def test_per_user_concurrency_limit(env, fake_docker, monkeypatch):
    from delegate import config, worker

    monkeypatch.setenv("DELEGATE_PER_USER_CONCURRENCY", "1")
    config.get_settings.cache_clear()
    first = _submit()
    from delegate import tasks
    from delegate.db import session_scope
    from delegate.models import User

    with session_scope() as db:
        second = tasks.create_task(db, db.query(User).one(), tasks.TaskInput(task="again"), source="api").id
    w = worker.Worker()
    assert w.claim_next() == first
    assert w.claim_next() is None  # same user already has a running task
    worker.run_task(first)
    assert w.claim_next() == second
