#!/usr/bin/env python3
"""Sandbox entrypoint: prepare /workspace, run one headless agent, report results.

Runs inside the sandbox container (stdlib only). Everything it prints to stdout is one JSON
envelope per line; the worker on the host reads the container log stream:

    {"t": "runner", "phase": ..., "msg": ...}
    {"t": "agent", "agent": "claude"|"codex", "event": {...}}
    {"t": "stderr", "line": ...}
    {"t": "finish", "exit_code": ..., "patch": {...}, ...}

Inputs (written by the worker before the container starts):
    /task/spec.json      task specification (no platform secrets)
    /task/files/...      small inline files to place into the workspace
    /task/uploads/<id>   uploaded files / archives (tar, tar.gz, zip), unpacked here, inside the sandbox
    env DELEGATE_GATEWAY_KEY   per-task new-api token, budget-limited, revoked after the task
Outputs:
    /out/changes.patch   binary git diff of everything the agent changed in /workspace
    /out/outputs.tar.gz  deliverables the agent put into /outputs
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import tarfile
import threading
import time
import zipfile
from pathlib import Path

WORKSPACE = Path("/workspace")
TASK_DIR = Path("/task")
OUT_DIR = Path("/out")
OUTPUTS = Path("/outputs")
PATCH_FILE = OUT_DIR / "changes.patch"
OUTPUTS_FILE = OUT_DIR / "outputs.tar.gz"
GIT_EXCLUDES = """\
node_modules/
.venv/
venv/
__pycache__/
*.pyc
.pytest_cache/
.mypy_cache/
.ruff_cache/
.cache/
.npm/
dist/
build/
target/
.next/
.DS_Store
"""

_out_lock = threading.Lock()
_child: subprocess.Popen | None = None
_stop_requested = threading.Event()


def emit(obj: dict) -> None:
    line = json.dumps(obj, ensure_ascii=False)
    with _out_lock:
        sys.stdout.write(line + "\n")
        sys.stdout.flush()


def phase(name: str, msg: str = "", **extra) -> None:
    emit({"t": "runner", "phase": name, "msg": msg, **extra})


def git(*args: str, check: bool = True, capture: bool = True, cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=cwd or WORKSPACE,
        check=check,
        text=True,
        stdout=subprocess.PIPE if capture else subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
    )


def _on_signal(signum, _frame) -> None:
    # Graceful stop (cancel / timeout): stop the agent, but still collect whatever it produced.
    _stop_requested.set()
    child = _child
    if child and child.poll() is None:
        try:
            child.terminate()
        except ProcessLookupError:
            pass


# --------------------------------------------------------------------------- workspace
def prepare_workspace(spec: dict) -> str:
    WORKSPACE.mkdir(parents=True, exist_ok=True)
    repo_url = spec.get("repo_url")
    if repo_url:
        phase("clone", f"cloning {spec.get('repo_display') or 'repository'}")
        git("clone", "--quiet", "--filter=blob:none", repo_url, str(WORKSPACE), cwd=Path("/"))
        if spec.get("repo_ref"):
            git("checkout", "--quiet", spec["repo_ref"])
        # Do not leave credentials embedded in the remote URL inside the sandbox.
        if spec.get("repo_display"):
            git("remote", "set-url", "origin", spec["repo_display"], check=False)

    for upload in spec.get("uploads") or []:
        count = place_upload(upload)
        phase("upload", f"upload {upload['id']} ({upload['kind']}) -> {upload['dest']}: {count} file(s)")

    if not (WORKSPACE / ".git").exists():
        git("init", "--quiet", "-b", "main")

    files_dir = TASK_DIR / "files"
    if files_dir.is_dir():
        count = 0
        for src in files_dir.rglob("*"):
            if src.is_file():
                dest = WORKSPACE / src.relative_to(files_dir)
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(src, dest)
                count += 1
        if count:
            phase("files", f"placed {count} attached file(s) into the workspace")

    git("config", "user.email", "agent@delegate.local")
    git("config", "user.name", "delegate-agent")
    exclude = WORKSPACE / ".git" / "info" / "exclude"
    exclude.parent.mkdir(parents=True, exist_ok=True)
    with exclude.open("a") as fh:
        fh.write("\n" + GIT_EXCLUDES)
    git("add", "-A")
    git("commit", "--quiet", "--allow-empty", "--no-verify", "-m", "delegate: baseline")
    return git("rev-parse", "HEAD").stdout.strip()


def _clean_name(name: str) -> str:
    name = name.replace("\\", "/")
    while name.startswith("./"):
        name = name[2:]
    return name


def _inside(root: Path, path: Path) -> bool:
    root = root.resolve()
    path = path.resolve()
    return path == root or root in path.parents


def _safe_target(base: Path, name: str) -> Path | None:
    name = _clean_name(name)
    if not name or name == "." or name.startswith("/") or ".." in name.split("/"):
        return None
    target = base / name
    return target if _inside(base, target) else None


def _is_git_path(name: str) -> bool:
    name = _clean_name(name).lstrip("/")
    return name == ".git" or name.startswith(".git/")


def place_upload(upload: dict) -> int:
    """Put one upload into the workspace. Archives are unpacked defensively (no escapes, no devices)."""
    src = TASK_DIR / "uploads" / upload["id"]
    kind = upload["kind"]
    dest = WORKSPACE if upload["dest"] in (".", "") else WORKSPACE / upload["dest"]
    skip_git = (WORKSPACE / ".git").exists()  # never let an upload clobber a cloned repository
    if kind == "file":
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dest)
        return 1
    dest.mkdir(parents=True, exist_ok=True)
    count = 0
    if kind in ("tar", "tgz"):
        with tarfile.open(src, "r:*") as tar:
            for member in tar:
                if skip_git and _is_git_path(member.name):
                    continue
                target = _safe_target(dest, member.name)
                if target is None:
                    continue
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                elif member.isfile():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    if target.is_symlink():
                        target.unlink()
                    with tar.extractfile(member) as fh, target.open("wb") as out:
                        shutil.copyfileobj(fh, out)
                    target.chmod(0o755 if member.mode & 0o111 else 0o644)
                    count += 1
                elif member.issym() and not member.linkname.startswith("/"):
                    if _inside(dest, target.parent / member.linkname):
                        target.parent.mkdir(parents=True, exist_ok=True)
                        if target.is_symlink() or target.exists():
                            target.unlink()
                        os.symlink(member.linkname, target)
                # hard links, devices and fifos are skipped on purpose
    elif kind == "zip":
        with zipfile.ZipFile(src) as zf:
            for info in zf.infolist():
                if skip_git and _is_git_path(info.filename):
                    continue
                target = _safe_target(dest, info.filename)
                if target is None:
                    continue
                if info.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(info) as fh, target.open("wb") as out:
                    shutil.copyfileobj(fh, out)
                target.chmod(0o755 if (info.external_attr >> 16) & 0o111 else 0o644)
                count += 1
    return count


def collect_outputs(limit: int) -> dict:
    if not OUTPUTS.is_dir():
        return {"count": 0, "files": []}
    files = sorted(p for p in OUTPUTS.rglob("*") if p.is_file() and not p.is_symlink())
    if not files:
        return {"count": 0, "files": []}
    listing = [{"path": p.relative_to(OUTPUTS).as_posix(), "size": p.stat().st_size} for p in files]
    total = sum(item["size"] for item in listing)
    if total > limit:
        phase("collect", f"/outputs holds {total} bytes, over the {limit} byte limit; outputs not returned")
        return {"count": 0, "files": [], "error": f"outputs exceed {limit} bytes"}
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with tarfile.open(OUTPUTS_FILE, "w:gz") as tar:
        for path, item in zip(files, listing):
            tar.add(path, arcname=item["path"], recursive=False)
    return {"count": len(listing), "files": listing[:1000], "bytes": OUTPUTS_FILE.stat().st_size}


def collect_patch(baseline: str) -> dict:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    try:
        git("add", "-A")
        with PATCH_FILE.open("w") as fh:
            subprocess.run(
                ["git", "diff", "--cached", "--binary", baseline], cwd=WORKSPACE, check=True, stdout=fh, text=True
            )
        numstat = git("diff", "--cached", "--numstat", baseline).stdout
    except (subprocess.CalledProcessError, OSError) as exc:
        phase("collect", f"failed to compute changes: {exc}")
        return {"files": 0, "insertions": 0, "deletions": 0, "bytes": 0, "error": str(exc)}
    files = insertions = deletions = 0
    paths = []
    for row in numstat.splitlines():
        parts = row.split("\t", 2)
        if len(parts) != 3:
            continue
        files += 1
        insertions += int(parts[0]) if parts[0].isdigit() else 0
        deletions += int(parts[1]) if parts[1].isdigit() else 0
        paths.append(parts[2])
    return {
        "files": files,
        "insertions": insertions,
        "deletions": deletions,
        "bytes": PATCH_FILE.stat().st_size,
        "paths": paths[:500],
    }


# --------------------------------------------------------------------------- agents
# Applied to every CLI. Claude Code in particular phones home unless these are set.
TELEMETRY_OFF = {
    "DISABLE_TELEMETRY": "1",
    "DISABLE_AUTOUPDATER": "1",
    "DISABLE_ERROR_REPORTING": "1",
    "DO_NOT_TRACK": "1",
    "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
    "CLAUDE_CODE_DISABLE_FEEDBACK_SURVEY": "1",
    "GEMINI_CLI_TELEMETRY": "0",
    "GROK_TELEMETRY_DISABLED": "1",
    "PI_TELEMETRY": "0",
    "DSH_TELEMETRY": "0",
    "IS_SANDBOX": "1",
}


def _auth(spec: dict) -> tuple[str, str, str]:
    """Return (base_url, api_key, env var the key was read from). The key never goes into argv."""
    auth = spec.get("auth") or {}
    if auth:
        env_name = "DELEGATE_LLM_API_KEY" if auth.get("mode") == "byok" else "DELEGATE_GATEWAY_KEY"
        return (auth.get("base_url") or "").rstrip("/"), os.environ[env_name], env_name
    return spec["gateway_url"].rstrip("/"), os.environ["DELEGATE_GATEWAY_KEY"], "DELEGATE_GATEWAY_KEY"


def claude_command(spec: dict) -> tuple[list[str], dict, str]:
    base, key, _env_name = _auth(spec)
    cmd = [
        "claude",
        "-p",
        "--output-format", "stream-json",
        "--verbose",
        "--model", spec["model"],
        "--max-turns", str(spec["max_turns"]),
        "--dangerously-skip-permissions",
        "--append-system-prompt", spec["system_prompt"],
        # WebFetch's domain preflight would otherwise call api.anthropic.com directly.
        "--settings", json.dumps({"skipWebFetchPreflight": True}),
    ]
    env = {
        # Bearer auth against the gateway; the per-task key is the only credential in the sandbox.
        "ANTHROPIC_BASE_URL": base,
        "ANTHROPIC_AUTH_TOKEN": key,
        "ANTHROPIC_API_KEY": key,
        "ANTHROPIC_MODEL": spec["model"],
        # Background work and subagents must use models the gateway actually serves.
        "ANTHROPIC_DEFAULT_HAIKU_MODEL": spec.get("small_model") or spec["model"],
        "CLAUDE_CODE_SUBAGENT_MODEL": spec["model"],
        **TELEMETRY_OFF,
    }
    return cmd, env, spec["prompt"]


def codex_command(spec: dict) -> tuple[list[str], dict, str]:
    if spec.get("auth"):
        base, key, env_name = _auth(spec)
    else:
        base = spec["gateway_url"].rstrip("/") + "/v1"
        key, env_name = os.environ["DELEGATE_GATEWAY_KEY"], "DELEGATE_GATEWAY_KEY"
    codex_home = Path(os.environ.get("HOME", "/home/agent")) / ".codex"
    codex_home.mkdir(parents=True, exist_ok=True)
    (codex_home / "config.toml").write_text(
        "\n".join(
            [
                f"model = {json.dumps(spec['model'])}",
                'model_provider = "delegate"',
                'approval_policy = "never"',
                'sandbox_mode = "danger-full-access"',
                "check_for_update_on_startup = false",
                "",
                "[analytics]",
                "enabled = false",
                "",
                "[feedback]",
                "enabled = false",
                "",
                "[otel]",
                'metrics_exporter = "none"',
                "",
                "[history]",
                'persistence = "none"',
                "",
                "[model_providers.delegate]",
                'name = "delegate"',
                f"base_url = {json.dumps(base)}",
                f"env_key = {json.dumps(env_name)}",
                'wire_api = "responses"',
                "",
            ]
        )
    )
    os.environ[env_name] = key
    cmd = [
        "codex",
        "exec",
        "--json",
        "--skip-git-repo-check",
        # The container is the sandbox; codex's own bubblewrap sandbox cannot run inside Docker.
        "--dangerously-bypass-approvals-and-sandbox",
        "--model", spec["model"],
        "-C", str(WORKSPACE),
        "-",
    ]
    # codex has no separate system-prompt flag for exec; prepend the delegation contract.
    prompt = spec["system_prompt"] + "\n\n---\n\nTASK:\n" + spec["prompt"]
    return cmd, {"CODEX_HOME": str(codex_home), env_name: key, **TELEMETRY_OFF}, prompt


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload))


def gemini_command(spec: dict) -> tuple[list[str], dict, str]:
    base, key, _env_name = _auth(spec)
    home = Path(os.environ.get("HOME", "/home/agent")) / ".gemini"
    _write_json(home / "settings.json", {
        "telemetry": {"enabled": False, "logUserPrompts": False},
        "usageStatisticsEnabled": False,
        "security": {"auth": {"selectedType": "gemini-api-key"}},
    })
    cmd = ["gemini", "--yolo", "--output-format", "stream-json", "-m", spec["model"], "-p", spec["prompt"]]
    env = {
        **TELEMETRY_OFF,
        "GEMINI_API_KEY": key,
        "GOOGLE_API_KEY": key,
        "GEMINI_MODEL": spec["model"],
        "GOOGLE_GEMINI_BASE_URL": base,
    }
    return cmd, env, ""


def grok_command(spec: dict) -> tuple[list[str], dict, str]:
    base, key, _env_name = _auth(spec)
    cmd = ["grok", "-p", spec["prompt"], "--model", spec["model"]]
    env = {
        **TELEMETRY_OFF,
        "XAI_API_KEY": key,
        "XAI_BASE_URL": base,
        "OPENAI_API_KEY": key,
        "OPENAI_BASE_URL": base,
    }
    return cmd, env, ""


def pi_command(spec: dict) -> tuple[list[str], dict, str]:
    base, key, _env_name = _auth(spec)
    home = Path(os.environ.get("HOME", "/home/agent")) / ".pi" / "agent"
    _write_json(home / "models.json", {
        "providers": {
            "delegate": {
                "baseUrl": base,
                "api": "openai-completions",
                "apiKey": "$OPENAI_API_KEY",
                "models": [{
                    "id": spec["model"],
                    "name": spec["model"],
                    "contextWindow": 128000,
                    "maxTokens": 8192,
                    "input": ["text"],
                    "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0},
                }],
            }
        }
    })
    _write_json(home / "settings.json", {"telemetry": False, "usageStatisticsEnabled": False})
    cmd = ["pi", "--print", "--provider", "delegate", "--model", spec["model"], spec["prompt"]]
    return cmd, {**TELEMETRY_OFF, "OPENAI_API_KEY": key, "OPENAI_BASE_URL": base}, ""


def deepseek_command(spec: dict) -> tuple[list[str], dict, str]:
    base, key, _env_name = _auth(spec)
    cmd = ["dsh", "--profile", "headless", "--json", "--approval-policy", "never"]
    env = {
        **TELEMETRY_OFF,
        "DEEPSEEK_API_KEY": key,
        "DEEPSEEK_BASE_URL": base,
        "OPENAI_API_KEY": key,
        "OPENAI_BASE_URL": base,
    }
    return cmd, env, spec["prompt"]


def run_agent(spec: dict) -> int:
    global _child
    agent = spec["agent"]
    builders = {
        "claude": claude_command,
        "codex": codex_command,
        "gemini": gemini_command,
        "grok": grok_command,
        "pi": pi_command,
        "deepseek": deepseek_command,
    }
    if agent not in builders:
        phase("error", f"unknown agent {agent!r}")
        return 2
    cmd, extra_env, prompt = builders[agent](spec)
    env = {**os.environ, **extra_env}
    phase("agent", f"starting {agent} ({spec['model']})")
    _child = subprocess.Popen(
        cmd,
        cwd=WORKSPACE,
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )

    def pump_stderr() -> None:
        assert _child and _child.stderr
        for line in _child.stderr:
            line = line.rstrip("\n")
            if line:
                emit({"t": "stderr", "line": line})

    stderr_thread = threading.Thread(target=pump_stderr, daemon=True)
    stderr_thread.start()
    try:
        assert _child.stdin
        _child.stdin.write(prompt)
        _child.stdin.close()
    except BrokenPipeError:
        pass
    assert _child.stdout
    saw_result = False
    plain: list[str] = []
    for line in _child.stdout:
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            plain.append(line)
            emit({"t": "stderr", "line": line})
            continue
        if isinstance(event, dict) and event.get("type") == "result":
            saw_result = True
        emit({"t": "agent", "agent": agent, "event": event})
    code = _child.wait()
    if not saw_result:
        text = "\n".join(plain)
        emit({"t": "agent", "agent": agent, "event": {
            "type": "result",
            "subtype": "success" if code == 0 else "error",
            "is_error": code != 0,
            "result": text or (f"harness exited with code {code}" if code else ""),
            "num_turns": 1,
            "usage": {},
        }})
    stderr_thread.join(timeout=5)
    return code


def main() -> int:
    signal.signal(signal.SIGTERM, _on_signal)
    signal.signal(signal.SIGINT, _on_signal)
    started = time.time()
    spec = json.loads((TASK_DIR / "spec.json").read_text())
    phase("start", f"task {spec.get('task_id')}")
    try:
        baseline = prepare_workspace(spec)
    except (subprocess.CalledProcessError, OSError, tarfile.TarError, zipfile.BadZipFile) as exc:
        detail = (getattr(exc, "stderr", "") or "").strip()[-2000:] or str(exc)
        if spec.get("repo_url") and spec["repo_url"] != spec.get("repo_display"):
            # git may echo the clone URL, which can embed an access token
            detail = detail.replace(spec["repo_url"], spec.get("repo_display") or "<repository>")
        phase("error", f"workspace preparation failed: {detail}")
        emit({"t": "finish", "exit_code": 3, "error": f"workspace preparation failed: {detail}", "patch": {}})
        return 3
    phase("ready", "workspace prepared", baseline=baseline)

    exit_code = 0
    if not _stop_requested.is_set():
        try:
            exit_code = run_agent(spec)
        except FileNotFoundError as exc:
            phase("error", f"agent binary not found: {exc}")
            exit_code = 127
    phase("collect", "collecting changes and outputs")
    patch = collect_patch(baseline)
    outputs = collect_outputs(int(spec.get("max_output_bytes") or 512 * 1024 * 1024))
    emit(
        {
            "t": "finish",
            "exit_code": exit_code,
            "stopped": _stop_requested.is_set(),
            "duration_s": round(time.time() - started, 1),
            "patch": patch,
            "outputs": outputs,
        }
    )
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
