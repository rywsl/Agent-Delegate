#!/usr/bin/env python3
"""Let a local OpenAI-compatible model command the delegate cloud agent.

The commander model only has to decide *what* to hand over; the heavy lifting happens in the
cloud sandbox. Its five MCP tools are re-exposed as OpenAI function definitions, plus one
helper that uploads a local path for it (the model has no shell).

    export DELEGATE_MCP_URL=http://localhost/mcp
    export DELEGATE_API_KEY=dlg_...
    export QWEN_BASE_URL=http://127.0.0.1:8000/v1     # any OpenAI-compatible server
    export QWEN_MODEL=qwen3.8-27b-unc
    export QWEN_API_KEY=...                           # omit for a local server without auth

    python client/qwen_commander.py "修好这个仓库里坏掉的测试"

    # plumbing check without a model (uploads a tiny directory, then delegates):
    python client/qwen_commander.py --script "写一个 hello.txt"

Optional: DELEGATE_API_URL when /api/v1 is not on the MCP origin, COMMANDER_UPLOAD_ROOTS (os.pathsep
separated) to widen what upload_local_path may read (default: the current directory), and
COMMANDER_MAX_TOKENS / COMMANDER_MAX_STEPS to bound one run.

Run it with the server environment: server/.venv/bin/python client/qwen_commander.py ...
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

try:  # mcp 2.x: the streamable HTTP client lives here and needs its httpx2 transport
    import httpx2 as httpx
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client
except ImportError as exc:  # pragma: no cover - environment guard
    raise SystemExit(f"this client needs mcp>=2.3 (with httpx2): pip install 'mcp>=2.3' httpx2 ({exc})") from exc

MCP_URL = os.environ.get("DELEGATE_MCP_URL", "http://localhost/mcp")
API_KEY = os.environ.get("DELEGATE_API_KEY", "")
MODEL_BASE = os.environ.get("QWEN_BASE_URL", "").rstrip("/")
MODEL_NAME = os.environ.get("QWEN_MODEL", "qwen3.8-27b-unc")
MODEL_KEY = os.environ.get("QWEN_API_KEY", "")
CLOUD_MODEL = os.environ.get("COMMANDER_CLOUD_MODEL", "Claude Opus")
MAX_STEPS = int(os.environ.get("COMMANDER_MAX_STEPS", "12"))
MAX_TOKENS = int(os.environ.get("COMMANDER_MAX_TOKENS", "2048"))
TERMINAL_STATUS = re.compile(r"\b(succeeded|failed|timeout|cancelled)\b")

# Never ship secrets or rebuildable junk from a home directory by accident.
UPLOAD_EXCLUDES = (".git", ".env", ".venv", "node_modules", "__pycache__", ".mypy_cache",
                   ".pytest_cache", ".ruff_cache", ".DS_Store")

SYSTEM_PROMPT = f"""\
You are a small local model with no shell, no file system, no test runner and a short context.
The user gives you access to a cloud agent that runs {CLOUD_MODEL} inside an isolated sandbox: it can
read and write files, run commands and tests, install packages, browse a repository and keep
working for many turns.

Delegate — do not attempt it yourself — as soon as ANY of these holds:
1. the work touches more than one file, or more than about 30 lines of code;
2. anything must be executed to be trusted: tests, builds, scripts, benchmarks, migrations;
3. the input is a repository, log, dataset or document you were not given in full;
4. the task has several dependent steps, or you would have to guess an answer;
5. you already tried once and cannot show the result is correct.

Answer directly only for explanations, short self-contained snippets, translations and quick
questions you already know the answer to. When in doubt, delegate: a wrong answer costs more than
a delegation.

How to delegate:
- Give goal, context, constraints, acceptance criteria and how to verify. The cloud agent cannot
  ask you questions, so put everything it needs into the task text.
- Small text inputs go in `files`; a local directory or large file goes through `upload_local_path`
  and its upload_id; a public git repository can be passed as repo_url.
- delegate_task returns after a bounded wait. If the result says the task is queued or running,
  keep calling wait_task with that task id until it reports a final status. Never give up early.
- You receive a report, a patch and download links. Relay them faithfully, say what was verified
  and what was not, and never fabricate a task id or a result you did not get back.
- The execution model, budget and timeout are fixed by the server (currently {CLOUD_MODEL}); do not
  ask the user to pick a model, and do not claim you chose one.

Reply in the language the user used."""

UPLOAD_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "upload_local_path",
        "description": (
            "Upload a local file or directory to the delegate service and return an upload id. "
            "The archive is packed for you (a directory is sent without .git) and uploaded; pass "
            "the id to delegate_task(upload_ids=[...]). Use this instead of create_upload when "
            "you have no shell."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Local file or directory to send"},
                "dest": {
                    "type": "string",
                    "description": "Where it lands in the cloud workspace: '.' for a directory, "
                                   "or a file path for a single file (default: the file name)",
                },
            },
            "required": ["path"],
        },
    },
}


# --------------------------------------------------------------------------- delegate API
def api_base() -> str:
    """Base URL of the delegate site (the MCP endpoint may live under a path prefix)."""
    override = os.environ.get("DELEGATE_API_URL", "").rstrip("/")
    if override:
        return override
    parts = urlsplit(MCP_URL)
    if parts.path not in ("", "/mcp"):
        print(f"note: deriving the API base from {MCP_URL}; set DELEGATE_API_URL if /api/v1 lives elsewhere",
              file=sys.stderr)
    return urlunsplit((parts.scheme, parts.netloc, "", "", ""))


def auth_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {API_KEY}"} if API_KEY else {}


def upload_roots() -> list[Path]:
    """Directories upload_local_path may read from (default: the current directory)."""
    raw = os.environ.get("COMMANDER_UPLOAD_ROOTS", "")
    roots = [Path(p).expanduser().resolve() for p in raw.split(os.pathsep) if p.strip()]
    return roots or [Path.cwd().resolve()]


def _inside_roots(path: Path) -> bool:
    return any(path == root or root in path.parents for root in upload_roots())


def _tar_args(source: Path) -> list[str]:
    """Pack ``source`` without secrets or rebuildable junk."""
    args = ["tar", "-czf", "-", "-C", str(source)]
    for name in UPLOAD_EXCLUDES:
        args += [f"--exclude=./{name}", f"--exclude=*/{name}"]
    args.append(".")
    return args


async def _file_chunks(fh: Any, size: int = 1 << 20) -> AsyncIterator[bytes]:
    """httpx2's AsyncClient only accepts async byte streams, not plain file objects."""
    while chunk := fh.read(size):
        yield chunk


async def upload_local_path(path: str, dest: str | None, *, trusted: bool = False) -> str:
    """Pack a local path and push it through a one-time upload URL.

    ``Path("")`` resolves to the working directory, so an empty path is rejected outright; paths
    outside COMMANDER_UPLOAD_ROOTS (default: the current directory) are rejected too. ``trusted``
    is for this script's own plumbing check, never for tool calls coming from the model.
    """
    raw = (path or "").strip()
    if not raw:
        return "error: path is required; refusing to upload the working directory"
    source = Path(raw).expanduser().resolve()
    if not source.exists():
        return f"error: no such path {raw!r}"
    if not trusted and not _inside_roots(source):
        return (f"error: {raw!r} is outside the allowed upload roots "
                f"({os.pathsep.join(str(r) for r in upload_roots())}); set COMMANDER_UPLOAD_ROOTS to widen it")
    dest = (dest or "").strip() or ("." if source.is_dir() else source.name)

    async with httpx.AsyncClient(base_url=api_base(), headers=auth_headers(), timeout=120) as api:
        resp = await api.post("/api/v1/uploads", json={"dest": dest})
    if resp.status_code >= 400:
        return f"error: cannot create upload: {resp.text[:300]}"
    slot = resp.json()
    limit = int(slot.get("max_bytes") or 0)

    with tempfile.SpooledTemporaryFile(max_size=8 << 20) as spool:
        if source.is_dir():
            proc = subprocess.run(_tar_args(source), stdout=spool, stderr=subprocess.PIPE)
            if proc.returncode != 0:
                return "error: tar failed: " + proc.stderr.decode("utf-8", "replace")[:500]
        else:
            with source.open("rb") as fh:
                shutil.copyfileobj(fh, spool)
        size = spool.tell()
        if limit and size > limit:
            return f"error: archive is {size} bytes, the gateway limit is {limit}; send less data"
        spool.seek(0)
        # The one-time URL is its own credential: this request carries no Authorization header.
        async with httpx.AsyncClient(timeout=600) as raw_client:
            put = await raw_client.put(slot["upload_url"], content=_file_chunks(spool))
    if put.status_code >= 400:
        return f"error: upload failed: {put.text[:300]}"
    info = put.json()
    return f"upload_id: {slot['upload_id']} (status {info.get('status')}, {size} bytes, dest {dest})"


# A delegated task legitimately blocks for minutes: never let a client-side read timeout cut the
# SSE stream of a tool call (delegate_task/wait_task wait up to ~100s each).
TRANSPORT_TIMEOUT = httpx.Timeout(connect=10.0, read=None, write=120.0, pool=30.0)


def mcp_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(headers=auth_headers(), timeout=TRANSPORT_TIMEOUT)


def tool_text(result: Any) -> str:
    parts = []
    for item in getattr(result, "content", []) or []:
        text = getattr(item, "text", None)
        parts.append(text if text is not None else json.dumps(item, ensure_ascii=False, default=str))
    text = "\n".join(parts) or "(no output)"
    if getattr(result, "isError", False) or getattr(result, "is_error", False):
        text = "ERROR: " + text
    return text


# --------------------------------------------------------------------------- model plumbing
def openai_tools(tools: list[Any]) -> list[dict[str, Any]]:
    out = []
    for tool in tools:
        schema = tool.input_schema or {"type": "object", "properties": {}}
        out.append(
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": (tool.description or "")[:1500],
                    "parameters": schema,
                },
            }
        )
    out.append(UPLOAD_TOOL)
    return out


async def chat(messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> dict[str, Any]:
    if not MODEL_BASE:
        raise SystemExit("QWEN_BASE_URL is not set (e.g. http://127.0.0.1:8000/v1)")
    headers = {"Authorization": f"Bearer {MODEL_KEY}"} if MODEL_KEY else {}
    payload = {
        "model": MODEL_NAME,
        "messages": messages,
        "tools": tools,
        "tool_choice": "auto",
        "temperature": 0.2,
        "max_tokens": MAX_TOKENS,
    }
    async with httpx.AsyncClient(base_url=MODEL_BASE, headers=headers, timeout=300) as client:
        resp = await client.post("/chat/completions", json=payload)
    if resp.status_code >= 400:
        raise SystemExit(f"model error {resp.status_code}: {resp.text[:500]}")
    try:
        data = resp.json()
    except ValueError as exc:
        raise SystemExit(f"model returned non-JSON: {resp.text[:500]}") from exc
    choices = data.get("choices") or []
    if not choices:
        # Several OpenAI-compatible servers answer 200 + {"error": ...} for oversized requests or
        # unsupported tool schemas; surface that instead of an IndexError traceback.
        raise SystemExit(f"model returned no choices: {json.dumps(data, ensure_ascii=False)[:500]}")
    return choices[0].get("message") or {}


def parse_args(raw: Any) -> tuple[dict[str, Any], str | None]:
    """Tool-call arguments as a dict, or an error message the model can act on."""
    if raw in (None, ""):
        return {}, None
    if isinstance(raw, dict):
        return raw, None
    try:
        value = json.loads(raw)
    except (TypeError, ValueError) as exc:
        return {}, f"arguments are not valid JSON ({exc})"
    if not isinstance(value, dict):
        return {}, "arguments must be a JSON object"
    return value, None


async def call(session: ClientSession, name: str, args: dict[str, Any]) -> str:
    if name == "upload_local_path":
        return await upload_local_path(str(args.get("path") or ""), args.get("dest"))
    try:
        return tool_text(await session.call_tool(name, args))
    except Exception as exc:  # noqa: BLE001 - surface the failure to the model, keep the loop alive
        return f"ERROR: {exc}"


def show(role: str, text: str, limit: int = 600) -> None:
    body = text if len(text) <= limit else text[: limit - 1] + "…"
    print(f"\n[{role}] {body}")


# --------------------------------------------------------------------------- modes
async def run_model(prompt: str) -> None:
    async with mcp_client() as http_client:
        async with streamable_http_client(MCP_URL, http_client=http_client) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = openai_tools((await session.list_tools()).tools)
                messages: list[dict[str, Any]] = [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ]
                for step in range(1, MAX_STEPS + 1):
                    message = await chat(messages, tools)
                    calls = message.get("tool_calls") or []
                    if not calls:
                        print("\n" + (message.get("content") or "").strip())
                        return
                    messages.append(message)
                    for item in calls:
                        fn = item.get("function") or {}
                        name = (fn.get("name") or "").strip()
                        call_id = item.get("id") or f"call_{step}_{len(messages)}"
                        args, error = parse_args(fn.get("arguments"))
                        if not name:
                            output = "ERROR: tool_calls[].function.name is empty; emit a valid tool name"
                        elif error:
                            output = f"ERROR: {error}; re-emit the tool call with valid JSON arguments"
                        else:
                            print(f"[step {step}] {name}({json.dumps(args, ensure_ascii=False)[:300]})")
                            output = await call(session, name, args)
                        show("result", output)
                        messages.append({"role": "tool", "tool_call_id": call_id, "content": output})
                print(f"\n(stopped after {MAX_STEPS} steps)")


async def run_script(prompt: str) -> None:
    """Replay the tool sequence a commander would use, to check the plumbing end to end."""
    with tempfile.TemporaryDirectory() as tmp:
        seed = Path(tmp) / "seed"
        seed.mkdir()
        (seed / "script-check.txt").write_text("commander plumbing check\n")
        uploaded = await upload_local_path(str(seed), ".", trusted=True)
        show("upload_local_path", uploaded)
        upload_id = re.search(r"upload_id: (\S+)", uploaded)
        if not upload_id:
            raise SystemExit("upload failed; \n" + uploaded)
        async with mcp_client() as http_client:
            async with streamable_http_client(MCP_URL, http_client=http_client) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    tools = (await session.list_tools()).tools
                    print("tools:", ", ".join(t.name for t in tools))
                    output = await call(session, "delegate_task",
                                        {"task": prompt, "wait_seconds": 100,
                                         "upload_ids": [upload_id.group(1)]})
                    show("delegate_task", output)
                    match = re.search(r"Task (t_[0-9a-f]+)", output)
                    for _ in range(10):
                        if not match or TERMINAL_STATUS.search(output):
                            break
                        output = await call(session, "wait_task",
                                            {"task_id": match.group(1), "wait_seconds": 100})
                        show("wait_task", output)
    print("\n" + output)
    if not TERMINAL_STATUS.search(output):
        raise SystemExit("task did not reach a final status (still queued/running)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("prompt", help="what you want solved")
    parser.add_argument("--script", action="store_true", help="replay tool calls without a model")
    args = parser.parse_args()
    if not API_KEY:
        raise SystemExit("DELEGATE_API_KEY is not set (create one on the web site under 'API keys')")
    asyncio.run(run_script(args.prompt) if args.script else run_model(args.prompt))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
