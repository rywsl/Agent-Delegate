"""MCP gateway: the only surface a delegating (local) agent talks to.

Stateless facade over the web site's /api/v1. It holds no credentials of its own: every call is made
with the caller's own API key (``Authorization: Bearer dlg_...``), so all authorisation and
auditing happen on the web site. The tools are intentionally coarse: hand a task over, wait for the
outcome, fetch deliverables. There is no way to steer the cloud agent step by step.
"""

from __future__ import annotations

import asyncio
import os
import time
from typing import Annotated, Any, Literal

import httpx
import uvicorn
from pydantic import BaseModel, Field
from starlette.requests import Request
from starlette.responses import JSONResponse

from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings

API_URL = os.environ.get("DELEGATE_API_URL", "http://web:8000").rstrip("/")
POLL_SLICE_S = 25
# Claude Code moves MCP calls running longer than ~2 min to the background and aborts calls that are
# idle for 5 min, so each call waits a bounded time and the agent calls wait_task again if needed.
DEFAULT_WAIT_S = int(os.environ.get("DELEGATE_MCP_DEFAULT_WAIT", "100"))
MAX_WAIT_S = int(os.environ.get("DELEGATE_MCP_MAX_WAIT", "3600"))

INSTRUCTIONS = """\
Delegate self-contained tasks to an autonomous cloud agent that works in an isolated sandbox.
The cloud agent cannot see your machine and cannot ask you questions, so put everything it needs into
the task description and its inputs. You hand the task over and receive the outcome: a final report,
a patch of workspace changes, and any output files. You cannot steer it while it runs.

Inputs: small text snippets via `files`; anything larger (a project directory, data, binaries) via
`create_upload` + curl, then pass the upload id to `delegate_task`. Do not paste large files into tool
arguments. Outputs come back as download URLs that you fetch with curl (patch -> `git apply`).

Tasks often take many minutes. Each call waits a bounded time; while the task is still running, keep
calling `wait_task` with its id until it reports a final status (you may do other work in between)."""

mcp = MCPServer(name="delegate", instructions=INSTRUCTIONS, version="0.2.0")


class InlineFile(BaseModel):
    path: Annotated[str, Field(description="Path relative to the cloud workspace, e.g. 'src/app.py'")]
    content: Annotated[str, Field(description="File content (text, or base64 if encoding='base64')")]
    encoding: Literal["utf-8", "base64"] = "utf-8"


# --------------------------------------------------------------------------- HTTP plumbing
def _api_key(ctx: Context) -> str:
    headers = ctx.headers or {}
    auth = headers.get("authorization") or headers.get("Authorization") or ""
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    key = headers.get("x-api-key") or headers.get("X-Api-Key")
    if key:
        return key.strip()
    raise ToolError(
        "No API key: configure this MCP server with the header 'Authorization: Bearer <key>' "
        "(create a key on the web site under 'API keys')."
    )


async def _call(ctx: Context, method: str, path: str, *, timeout: float = 30, **kwargs: Any) -> dict[str, Any]:
    headers = {"Authorization": f"Bearer {_api_key(ctx)}"}
    client_name = (ctx.headers or {}).get("user-agent")
    if client_name:
        headers["X-Delegate-Client"] = client_name[:200]
    try:
        async with httpx.AsyncClient(base_url=API_URL, timeout=timeout) as client:
            resp = await client.request(method, path, headers=headers, **kwargs)
    except httpx.HTTPError as exc:
        raise ToolError(f"delegate service unreachable: {exc}") from exc
    if resp.status_code >= 400:
        try:
            detail = resp.json().get("detail")
        except ValueError:
            detail = resp.text[:500]
        raise ToolError(f"{detail or resp.reason_phrase} (HTTP {resp.status_code})")
    return resp.json()


# --------------------------------------------------------------------------- formatting
def _size(n: int | float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n} B"


def _duration(seconds: float | None) -> str:
    if seconds is None:
        return "-"
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}h{m:02d}m" if h else (f"{m}m{s:02d}s" if m else f"{s}s")


def _shell_quote(value: str) -> str:
    return "'" + value.replace("'", "'\\''") + "'"


def format_task(view: dict[str, Any]) -> str:
    tid, status = view["id"], view["status"]
    if status in ("queued", "preparing", "running"):
        where = f" (queue position {view['queue_position']})" if view.get("queue_position") else ""
        return (
            f"Task {tid} is {status}{where}, elapsed {_duration(view.get('duration_s'))}.\n"
            f"It keeps running in the cloud. Call wait_task(task_id=\"{tid}\") to keep waiting for the outcome.\n"
            f"Audit trail (for humans): {view['audit_url']}"
        )

    lines = [f"Task {tid} {status} after {_duration(view.get('duration_s'))}."]
    if view.get("error"):
        lines.append(f"Reason: {view['error']}")
    lines += ["", "## Report from the cloud agent", view.get("result") or "(no report)"]

    patch = view.get("patch") or {}
    if patch.get("files"):
        lines += ["", f"## Workspace changes: {patch['files']} file(s), +{patch['insertions']}/-{patch['deletions']}"]
        if patch.get("paths"):
            lines.append("Files: " + ", ".join(patch["paths"][:30]) + (" …" if len(patch["paths"]) > 30 else ""))
        if patch.get("url"):
            name = f"{tid}.patch"
            lines.append(
                f"Apply (paths are relative to the cloud workspace root, i.e. where uploads with dest '.' landed): "
                f"curl -fsSL {_shell_quote(patch['url'])} -o {name} && git apply {name}"
            )
        if patch.get("inline"):
            lines += ["```diff", patch["inline"].rstrip("\n"), "```"]
        elif patch.get("bytes"):
            lines.append(f"(patch is {_size(patch['bytes'])}; not inlined, download it with the command above)")
    else:
        lines += ["", "## Workspace changes: none"]

    outputs = view.get("outputs") or {}
    if outputs.get("count"):
        lines += ["", f"## Output files: {outputs['count']} ({_size(outputs.get('bytes', 0))})"]
        for item in outputs.get("files", [])[:50]:
            lines.append(f"- {item['path']} ({_size(item['size'])}): curl -fsSL {_shell_quote(item['url'])} -o <dest>")
        lines.append(f"All outputs: curl -fsSL {_shell_quote(outputs['bundle_url'])} | tar -xzf - -C <dest-dir>")

    lines.append("Download links expire after a while; call wait_task again for fresh ones.")
    lines.append(f"Audit trail (for humans): {view['audit_url']}")
    return "\n".join(lines)


async def _wait(ctx: Context, task_id: str, wait_seconds: int) -> str:
    wait_seconds = max(0, min(int(wait_seconds), MAX_WAIT_S))
    deadline = time.monotonic() + wait_seconds
    started = time.monotonic()
    while True:
        remaining = deadline - time.monotonic()
        slice_s = int(max(0, min(POLL_SLICE_S, remaining)))
        view = await _call(ctx, "GET", f"/api/v1/tasks/{task_id}/wait", params={"timeout": slice_s}, timeout=slice_s + 30)
        if view["status"] not in ("queued", "preparing", "running") or remaining <= 0:
            return format_task(view)
        elapsed = time.monotonic() - started
        await ctx.report_progress(elapsed, wait_seconds or None, f"task {task_id}: {view['status']}")
        await asyncio.sleep(0)


# --------------------------------------------------------------------------- tools
@mcp.tool()
async def create_upload(
    ctx: Context,
    dest: Annotated[
        str,
        Field(
            description="Where the upload lands in the cloud workspace. '.' (default) for an archive "
            "(tar, tar.gz or zip) unpacked into the workspace root, a sub-directory for an archive "
            "unpacked there, or a file path like 'data/input.csv' for a single non-archive file."
        ),
    ] = ".",
) -> str:
    """Get a one-time URL to upload input files for a delegated task, without passing their content
    through tool arguments. Upload with curl from your shell, then pass the returned upload_id to
    delegate_task(upload_ids=[...]). Use this for project directories, large or binary files."""
    data = await _call(ctx, "POST", "/api/v1/uploads", json={"dest": dest})
    url = _shell_quote(data["upload_url"])
    return (
        f"upload_id: {data['upload_id']}  (expires {data['expires_at']}, max {_size(data['max_bytes'])})\n"
        f"Upload ONE of the following from your shell:\n"
        f"- a project directory (respects .gitignore, includes uncommitted changes):\n"
        f"    git ls-files -co --exclude-standard -z | tar --null -T - -czf - | curl -fsS -T - {url}\n"
        f"- any directory: tar -czf - -C <dir> . | curl -fsS -T - {url}\n"
        f"- a single file (create the upload with dest='path/name.ext'): curl -fsS -T <file> {url}\n"
        f"The upload response is JSON with status 'ready' on success. Then call "
        f"delegate_task(..., upload_ids=[\"{data['upload_id']}\"])."
    )


@mcp.tool()
async def delegate_task(
    ctx: Context,
    task: Annotated[
        str,
        Field(
            description="Complete, self-contained instructions: goal, context, constraints, acceptance criteria "
            "and how to verify. The cloud agent cannot ask follow-up questions."
        ),
    ],
    title: Annotated[str | None, Field(description="Short title for the audit trail")] = None,
    upload_ids: Annotated[
        list[str] | None, Field(description="Upload ids from create_upload, unpacked into the workspace in order")
    ] = None,
    files: Annotated[
        list[InlineFile] | None,
        Field(description="Small inline text files only (a few KB); use create_upload for anything larger"),
    ] = None,
    repo_url: Annotated[str | None, Field(description="Optional http(s) git URL to clone as the workspace")] = None,
    repo_ref: Annotated[str | None, Field(description="Branch, tag or commit to check out")] = None,
    wait_seconds: Annotated[
        int, Field(description="How long to wait for completion before returning (the task keeps running)")
    ] = DEFAULT_WAIT_S,
) -> str:
    """Hand a task over to an autonomous cloud agent running in an isolated sandbox and wait for the
    outcome. Returns the agent's final report, the workspace changes as a patch (inline if small, plus a
    download URL) and download URLs for any output files. If the task is still running when wait_seconds
    elapses, call wait_task with the returned task id."""
    payload: dict[str, Any] = {
        "task": task,
        "title": title,
        "upload_ids": upload_ids or [],
        "files": [f.model_dump() for f in files or []],
        "repo_url": repo_url,
        "repo_ref": repo_ref,
    }
    created = await _call(ctx, "POST", "/api/v1/tasks", json=payload, timeout=120)
    await ctx.report_progress(0, None, f"task {created['id']} submitted")
    return await _wait(ctx, created["id"], wait_seconds)


@mcp.tool()
async def wait_task(
    ctx: Context,
    task_id: Annotated[str, Field(description="Task id returned by delegate_task")],
    wait_seconds: Annotated[int, Field(description="Maximum time to wait before returning")] = DEFAULT_WAIT_S,
) -> str:
    """Wait for a delegated task to finish and return its outcome (also returns immediately for finished
    tasks, with fresh download links)."""
    return await _wait(ctx, task_id, wait_seconds)


@mcp.tool()
async def cancel_task(ctx: Context, task_id: Annotated[str, Field(description="Task id")]) -> str:
    """Cancel a delegated task. Work done so far is still collected and returned by wait_task."""
    data = await _call(ctx, "POST", f"/api/v1/tasks/{task_id}/cancel")
    return f"Task {task_id}: {data['status']}" + (" (cancellation requested)" if data.get("cancel_requested") else "")


@mcp.tool()
async def list_tasks(
    ctx: Context, limit: Annotated[int, Field(description="Number of recent tasks", ge=1, le=50)] = 10
) -> str:
    """List your most recent delegated tasks with their status."""
    data = await _call(ctx, "GET", "/api/v1/tasks", params={"limit": limit})
    if not data["tasks"]:
        return "No tasks yet."
    return "\n".join(
        f"{t['id']}  {t['status']:<10} {t['created_at'][:19]}  {t['title']}" for t in data["tasks"]
    )


@mcp.custom_route("/healthz", methods=["GET"])
async def healthz(_: Request) -> JSONResponse:
    return JSONResponse({"ok": True})


def build_app():
    allowed = [h.strip() for h in os.environ.get("DELEGATE_MCP_ALLOWED_HOSTS", "").split(",") if h.strip()]
    security = (
        TransportSecuritySettings(enable_dns_rebinding_protection=True, allowed_hosts=allowed, allowed_origins=[])
        if allowed
        else TransportSecuritySettings(enable_dns_rebinding_protection=False)
    )
    return mcp.streamable_http_app(streamable_http_path="/mcp", stateless_http=True, transport_security=security)


def main() -> None:
    uvicorn.run(
        build_app(),
        host=os.environ.get("DELEGATE_MCP_HOST", "0.0.0.0"),
        port=int(os.environ.get("DELEGATE_MCP_PORT", "8001")),
        proxy_headers=True,
        forwarded_allow_ips="*",
    )


if __name__ == "__main__":
    main()
