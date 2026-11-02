"""Task worker: claims queued tasks, runs each in its own sandbox container, records the audit trail."""

from __future__ import annotations

import logging
import os
import signal
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import func, select, update

from . import audit, billing, sandbox, transfer
from .config import ensure_data_dirs, get_settings
from .db import init_db, session_scope
from .events import NormEvent, Normalizer
from .models import Task, TaskEvent, TaskStatus, User, utcnow
from .security import decrypt
from .tasks import SYSTEM_PROMPT, outputs_path, patch_path, raw_log_path, task_dir

log = logging.getLogger("delegate.worker")

STOP_GRACE_S = 45  # time the runner gets to stop the agent and collect the patch
RECONCILE_DELAY_S = 20
CLAUDE_SMALL_MODEL = os.environ.get("DELEGATE_CLAUDE_SMALL_MODEL", "")


class EventSink:
    """Buffers normalised events and writes them to the database in small batches."""

    def __init__(self, task_id: str) -> None:
        self.task_id = task_id
        self.buffer: list[TaskEvent] = []
        self.last_flush = time.monotonic()
        with session_scope() as s:
            self.seq = int(s.scalar(select(func.max(TaskEvent.seq)).where(TaskEvent.task_id == task_id)) or 0)

    def add(self, event: NormEvent, ts: datetime | None = None) -> None:
        self.seq += 1
        self.buffer.append(
            TaskEvent(
                task_id=self.task_id,
                seq=self.seq,
                ts=ts or utcnow(),
                kind=event.kind,
                summary=event.summary,
                data=event.data,
            )
        )
        if len(self.buffer) >= 50 or time.monotonic() - self.last_flush > 0.5:
            self.flush()

    def note(self, kind: str, summary: str, **data) -> None:
        self.add(NormEvent(kind, summary, data))

    def flush(self) -> None:
        self.last_flush = time.monotonic()
        if not self.buffer:
            return
        rows, self.buffer = self.buffer, []
        with session_scope() as s:
            s.add_all(rows)
            s.execute(update(Task).where(Task.id == self.task_id).values(event_count=self.seq))


def _parse_ts(ts: str) -> datetime | None:
    if not ts:
        return None
    try:  # docker uses RFC3339 with nanoseconds
        base, _, frac = ts.rstrip("Z").partition(".")
        return datetime.fromisoformat(f"{base}.{(frac or '0')[:6]}").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


class Watchdog(threading.Thread):
    """Stops the container on cancellation or when the task exceeds its time limit."""

    def __init__(self, task_id: str, container, deadline: float) -> None:
        super().__init__(daemon=True)
        self.task_id = task_id
        self.container = container
        self.deadline = deadline
        self.reason: str | None = None
        self.done = threading.Event()

    def run(self) -> None:
        while not self.done.wait(2.0):
            if time.monotonic() > self.deadline:
                self.reason = "timeout"
            else:
                with session_scope() as s:
                    if s.scalar(select(Task.cancel_requested).where(Task.id == self.task_id)):
                        self.reason = "cancel"
            if self.reason:
                sandbox.stop(self.container, STOP_GRACE_S)
                return


def build_spec(task: Task) -> dict:
    s = get_settings()
    repo_full = decrypt(task.repo_url_enc) if task.repo_url_enc else task.repo_url
    return {
        "task_id": task.id,
        "agent": task.agent,
        "model": task.model,
        "small_model": CLAUDE_SMALL_MODEL if task.agent == "claude" else "",
        "max_turns": task.max_turns,
        "prompt": task.prompt,
        "system_prompt": SYSTEM_PROMPT,
        "repo_url": repo_full,
        "repo_display": task.repo_url,
        "repo_ref": task.repo_ref,
        "gateway_url": s.sandbox_newapi_url,
        "uploads": [{"id": u["id"], "dest": u["dest"], "kind": u["kind"]} for u in task.uploads or []],
        "max_output_bytes": s.max_output_bytes,
    }


def load_files(task: Task) -> dict[str, bytes]:
    base = task_dir(task.id) / "files"
    return {a["path"]: (base / a["path"]).read_bytes() for a in task.attachments or []}


def upload_files(task: Task) -> dict[str, Path]:
    base = task_dir(task.id) / "uploads"
    return {u["id"]: base / u["id"] for u in task.uploads or []}


def run_task(task_id: str) -> None:
    s = get_settings()
    sink = EventSink(task_id)
    normalizer = Normalizer()
    container = None
    watchdog: Watchdog | None = None
    status, reason, exit_code = TaskStatus.FAILED, None, None
    patch_stats: dict = {}
    outputs: list[dict] = []
    task_dir(task_id).mkdir(parents=True, exist_ok=True)

    try:
        # Events are written in their own transactions: never while this session holds writes (SQLite).
        with session_scope() as session:
            task = session.get(Task, task_id)
            user = session.get(User, task.user_id)
            agent, model = task.agent, task.model
        sink.note("phase", f"[prepare] worker picked up the task ({agent}, {model})")
        with session_scope() as session:
            task = session.get(Task, task_id)
            gateway_key = billing.open_task_token(session, session.get(User, task.user_id), task)
            spec = build_spec(task)
            files = load_files(task)
            uploads = upload_files(task)
            token_name, budget_quota = task.newapi_token_name, task.budget_quota
        sink.note("phase", f"[billing] budget {s.quota_to_usd(budget_quota):.2f} USD on gateway key {token_name}",
                  token=token_name, budget_quota=budget_quota)

        container = sandbox.create_and_start(
            sandbox.SandboxSpec(
                task_id=task_id, user_id=user.id, spec=spec, files=files, uploads=uploads, gateway_key=gateway_key
            )
        )
        with session_scope() as session:
            task = session.get(Task, task_id)
            task.status = TaskStatus.RUNNING
            task.container_id = container.id
            task.container_name = container.name
            task.sandbox_image = s.sandbox_image
            task.sandbox_limits = sandbox.limits()
            timeout_s = task.timeout_s
        sink.note("phase", f"[sandbox] container {container.name} started", container_id=container.id, **sandbox.limits())

        watchdog = Watchdog(task_id, container, time.monotonic() + timeout_s)
        watchdog.start()
        with raw_log_path(task_id).open("a", encoding="utf-8") as raw:
            for ts, line in sandbox.stream_lines(container):
                raw.write(f"{ts} {line}\n")
                for event in normalizer.feed_line(line):
                    sink.add(event, _parse_ts(ts))
        exit_code = sandbox.wait_exit(container)
        watchdog.done.set()

        size = sandbox.fetch_file(container, sandbox.PATCH_PATH, patch_path(task_id), sandbox.MAX_PATCH_BYTES)
        finish = normalizer.finish or {}
        if (finish.get("outputs") or {}).get("count"):
            got = sandbox.fetch_file(container, sandbox.OUTPUTS_PATH, outputs_path(task_id), s.max_output_bytes)
            if got is not None:
                outputs = list(finish["outputs"].get("files") or [])
        if watchdog.reason == "cancel":
            status, reason = TaskStatus.CANCELLED, "cancelled by user"
        elif watchdog.reason == "timeout":
            status, reason = TaskStatus.TIMEOUT, f"time limit of {timeout_s}s exceeded"
        elif not finish:
            reason = f"sandbox exited unexpectedly (exit code {exit_code})"
        elif exit_code == 0 and not normalizer.usage.is_error:
            status = TaskStatus.SUCCEEDED
        else:
            reason = normalizer.usage.error or finish.get("error") or f"agent exited with code {exit_code}"
        patch_stats = dict(finish.get("patch") or {})
        if size is not None:
            patch_stats["bytes"] = size
    except billing.BillingError as exc:
        reason = str(exc)
        sink.note("error", f"[billing] {exc}")
    except Exception as exc:  # noqa: BLE001 - any failure must end the task cleanly
        log.exception("task %s failed", task_id)
        reason = f"internal error: {exc}"
        sink.note("error", f"[worker] {reason}")
    finally:
        if watchdog:
            watchdog.done.set()
        if container is not None:
            sandbox.remove(container)

    with session_scope() as session:
        task = session.get(Task, task_id)
        billing.close_task_token(session, task)
        task.status = status
        task.status_reason = reason
        task.exit_code = exit_code
        task.finished_at = utcnow()
        task.result_text = normalizer.final_message or ("" if status == TaskStatus.SUCCEEDED else reason)
        task.patch_stats = patch_stats
        task.outputs = outputs
        task.agent_usage = normalizer.usage.as_dict()
        audit.record(
            session,
            "task.finish",
            actor="system",
            user_id=task.user_id,
            target=task.id,
            status=status,
            reason=reason,
            exit_code=exit_code,
        )
    sink.note("phase", f"[done] {status}" + (f": {reason}" if reason else ""))
    sink.flush()


class Worker:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.worker_id = os.environ.get("DELEGATE_WORKER_ID", "worker-1")
        self.threads: dict[str, threading.Thread] = {}
        self.stopping = threading.Event()
        self.last_reconcile = 0.0

    # -------------------------------------------------------------- lifecycle
    def recover(self) -> None:
        """Tasks left active by a previous run of this worker cannot be resumed: stop and fail them."""
        try:
            containers = sandbox.find_task_containers()
        except Exception as exc:  # noqa: BLE001
            log.error("docker unavailable during recovery: %s", exc)
            containers = {}
        with session_scope() as session:
            stale = session.scalars(
                select(Task).where(
                    Task.status.in_([TaskStatus.PREPARING, TaskStatus.RUNNING]), Task.worker_id == self.worker_id
                )
            ).all()
            for task in stale:
                container = containers.pop(task.id, None)
                if container is not None:
                    sandbox.remove(container)
                billing.close_task_token(session, task)
                task.status = TaskStatus.FAILED
                task.status_reason = "worker restarted while the task was running"
                task.finished_at = utcnow()
                audit.record(session, "task.finish", actor="system", user_id=task.user_id, target=task.id,
                             status=task.status, reason=task.status_reason)
                log.warning("marked orphaned task %s as failed", task.id)

    def claim_next(self) -> str | None:
        with session_scope() as session:
            busy = dict(
                session.execute(
                    select(Task.user_id, func.count())
                    .where(Task.status.in_([TaskStatus.PREPARING, TaskStatus.RUNNING]))
                    .group_by(Task.user_id)
                ).all()
            )
            candidates = session.scalars(
                select(Task).where(Task.status == TaskStatus.QUEUED).order_by(Task.created_at).limit(50)
            ).all()
            for task in candidates:
                if busy.get(task.user_id, 0) >= self.settings.per_user_concurrency:
                    continue
                claimed = session.execute(
                    update(Task)
                    .where(Task.id == task.id, Task.status == TaskStatus.QUEUED)
                    .values(status=TaskStatus.PREPARING, worker_id=self.worker_id, started_at=utcnow())
                ).rowcount
                if claimed:
                    return task.id
        return None

    def reconcile_billing(self) -> None:
        cutoff = utcnow() - timedelta(seconds=RECONCILE_DELAY_S)
        with session_scope() as session:
            pending = session.scalars(
                select(Task)
                .where(
                    Task.status.in_(TaskStatus.TERMINAL),
                    Task.billing_reconciled_at.is_(None),
                    Task.newapi_token_name.is_not(None),
                    Task.finished_at < cutoff,
                )
                .limit(20)
            ).all()
            for task in pending:
                try:
                    billing.reconcile_task(session, task)
                except Exception as exc:  # noqa: BLE001
                    log.warning("billing reconcile for %s failed: %s", task.id, exc)

    def run_forever(self) -> None:
        ensure_data_dirs()
        init_db()
        self.recover()
        log.info("worker %s started (max %d sandboxes)", self.worker_id, self.settings.sandbox_max_concurrent)
        while not self.stopping.is_set():
            for task_id, thread in list(self.threads.items()):
                if not thread.is_alive():
                    del self.threads[task_id]
            try:
                while len(self.threads) < self.settings.sandbox_max_concurrent and not self.stopping.is_set():
                    task_id = self.claim_next()
                    if not task_id:
                        break
                    thread = threading.Thread(target=self._guarded_run, args=(task_id,), name=f"task-{task_id}")
                    self.threads[task_id] = thread
                    thread.start()
                if time.monotonic() - self.last_reconcile > 15:
                    self.last_reconcile = time.monotonic()
                    self.reconcile_billing()
                    with session_scope() as session:
                        transfer.purge_expired_uploads(session)
            except Exception:  # noqa: BLE001 - keep the loop alive (e.g. database restarts)
                log.exception("worker loop error")
            self.stopping.wait(1.0)
        log.info("worker stopping; waiting for %d running task(s)", len(self.threads))
        for thread in self.threads.values():
            thread.join()

    def _guarded_run(self, task_id: str) -> None:
        try:
            run_task(task_id)
        except Exception:  # noqa: BLE001
            log.exception("unhandled error in task %s", task_id)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    worker = Worker()

    def _stop(*_):
        worker.stopping.set()

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    worker.run_forever()


if __name__ == "__main__":
    main()
