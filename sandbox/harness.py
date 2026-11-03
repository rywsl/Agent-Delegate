from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

DEFAULT_COMMANDS = {
    "claude-code": [
        "claude", "-p", "--output-format", "stream-json", "--verbose", "--model", "{model}",
        "--max-turns", "{max_turns}", "--dangerously-skip-permissions",
        "--append-system-prompt", "{system_prompt}", "--settings", '{"skipWebFetchPreflight":true}',
    ],
    "codex": [
        "codex", "exec", "--json", "--skip-git-repo-check", "--dangerously-bypass-approvals-and-sandbox",
        "--model", "{model}", "-C", "{workspace}", "-",
    ],
    "gemini": ["gemini", "--yolo", "--output-format", "json", "--prompt", "{full_prompt}"],
    "grok": ["grok", "--prompt", "{full_prompt}"],
    "pi": ["pi", "--print", "{full_prompt}"],
    "deepseek": ["deepseek", "--prompt", "{full_prompt}"],
}


def _environment(spec: dict, api_key: str) -> dict[str, str]:
    env = dict(os.environ)
    provider = spec["provider"]
    names = {
        "anthropic": ("ANTHROPIC_API_KEY", "ANTHROPIC_BASE_URL"),
        "openai": ("OPENAI_API_KEY", "OPENAI_BASE_URL"),
        "gemini": ("GEMINI_API_KEY", "GEMINI_BASE_URL"),
    }[provider]
    env[names[0]] = api_key
    if provider == "gemini":
        env["GOOGLE_API_KEY"] = api_key
    if spec.get("base_url"):
        env[names[1]] = spec["base_url"]
    env.update({
        "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
        "DISABLE_TELEMETRY": "1",
        "DISABLE_AUTOUPDATER": "1",
        "DISABLE_ERROR_REPORTING": "1",
        "IS_SANDBOX": "1",
    })
    return env


def _codex_config(spec: dict) -> str:
    home = Path(os.environ.get("HOME", "/home/agent")) / ".codex"
    home.mkdir(parents=True, exist_ok=True)
    base_url = spec.get("base_url") or "https://api.openai.com/v1"
    (home / "config.toml").write_text("\n".join([
        f"model = {json.dumps(spec['model'])}",
        'model_provider = "delegate"',
        'approval_policy = "never"',
        'sandbox_mode = "danger-full-access"',
        "check_for_update_on_startup = false",
        "",
        "[model_providers.delegate]",
        'name = "delegate"',
        f"base_url = {json.dumps(base_url)}",
        'env_key = "DELEGATE_LLM_API_KEY"',
        'wire_api = "responses"',
        "",
    ]))
    return str(home)


def run_harness(
    spec: dict[str, Any], api_key: str, workspace: Path, emit: Callable[[dict], None],
    should_stop: Callable[[], bool],
) -> int:
    harness = spec["harness"]
    command = spec.get("harness_command") or DEFAULT_COMMANDS.get(harness)
    if not command:
        raise RuntimeError(f"no command configured for harness {harness}")
    prompt = spec["prompt"]
    if harness == "codex":
        prompt = spec["system_prompt"] + "\n\n---\n\nTASK:\n" + prompt
    values = {
        "model": spec["model"], "max_turns": str(spec["max_turns"]), "prompt": prompt,
        "system_prompt": spec["system_prompt"], "workspace": str(workspace),
        "full_prompt": spec["system_prompt"] + "\n\n---\n\nTASK:\n" + spec["prompt"],
    }
    argv = [str(part).format_map(values) for part in command]
    env = _environment(spec, api_key)
    if harness == "codex":
        env["CODEX_HOME"] = _codex_config(spec)
    emit({"t": "runner", "phase": "agent", "msg": f"starting {harness} ({spec['model']})"})
    process = subprocess.Popen(
        argv, cwd=workspace, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace", bufsize=1,
    )
    if harness != "codex":
        assert process.stdin
        process.stdin.write(spec["prompt"])
        process.stdin.close()
    else:
        assert process.stdin
        process.stdin.write(prompt)
        process.stdin.close()

    event_agent = {"claude-code": "claude", "codex": "codex"}.get(harness, spec["provider"])
    plain_lines = []
    saw_result = False
    final_text = ""
    assert process.stdout
    for line in process.stdout:
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            plain_lines.append(line)
            emit({"t": "stderr", "line": line})
            continue
        if not isinstance(event, dict):
            continue
        saw_result = saw_result or event.get("type") == "result"
        text = event.get("result") or event.get("response") or event.get("text")
        if isinstance(text, str):
            final_text = text
        emit({"t": "agent", "agent": event_agent, "event": event})
    code = process.wait()
    if not saw_result:
        final_text = final_text or "\n".join(plain_lines)
        emit({"t": "agent", "agent": event_agent, "event": {
            "type": "result", "subtype": "success" if code == 0 else "error", "is_error": code != 0,
            "result": final_text or (f"harness exited with code {code}" if code else ""), "num_turns": 1, "usage": {},
        }})
    return code
