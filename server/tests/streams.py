"""Representative agent output, wrapped the way sandbox/runner.py wraps it."""

from __future__ import annotations

import json


PATCH = """diff --git a/app.py b/app.py
--- a/app.py
+++ b/app.py
@@ -1 +1 @@
-print(1)
+print(2)
"""


def wrap(agent: str, event: dict) -> str:
    return json.dumps({"t": "agent", "agent": agent, "event": event})


def runner(phase: str, msg: str = "", **extra) -> str:
    return json.dumps({"t": "runner", "phase": phase, "msg": msg, **extra})


CLAUDE_EVENTS = [
    {"type": "system", "subtype": "init", "session_id": "s-1", "model": "claude-sonnet-5-5", "cwd": "/workspace",
     "tools": ["Bash", "Read", "Edit", "Write"], "claude_code_version": "2.1.316", "permissionMode": "bypassPermissions"},
    {"type": "assistant", "session_id": "s-1", "parent_tool_use_id": None,
     "message": {"id": "msg_1", "model": "claude-sonnet-5-5", "role": "assistant", "stop_reason": None,
                 "content": [{"type": "thinking", "thinking": "Look at the failing test first.", "signature": "x"}],
                 "usage": {"input_tokens": 1200, "output_tokens": 1, "cache_read_input_tokens": 0}}},
    {"type": "assistant", "session_id": "s-1", "parent_tool_use_id": None,
     "message": {"id": "msg_1", "model": "claude-sonnet-5-5", "role": "assistant",
                 "content": [{"type": "tool_use", "id": "toolu_1", "name": "Bash",
                              "input": {"command": "pytest -q", "description": "run tests"}}],
                 "usage": {"input_tokens": 1200, "output_tokens": 1}}},
    {"type": "user", "session_id": "s-1", "parent_tool_use_id": None,
     "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "toolu_1",
                                               "content": "1 failed, 3 passed", "is_error": False}]}},
    {"type": "system", "subtype": "api_retry", "attempt": 1, "max_retries": 10, "retry_delay_ms": 500,
     "error_status": 529, "error": "overloaded"},
    {"type": "assistant", "session_id": "s-1", "parent_tool_use_id": None,
     "message": {"id": "msg_2", "model": "claude-sonnet-5-5", "role": "assistant",
                 "content": [{"type": "tool_use", "id": "toolu_2", "name": "Edit",
                              "input": {"file_path": "/workspace/app.py", "old_string": "a", "new_string": "b"}}],
                 "usage": {"input_tokens": 1500, "output_tokens": 1}}},
    {"type": "user", "session_id": "s-1", "parent_tool_use_id": None,
     "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "toolu_2",
                                               "content": [{"type": "text", "text": "File updated"}]}]}},
    {"type": "assistant", "session_id": "s-1", "parent_tool_use_id": None,
     "message": {"id": "msg_3", "model": "claude-sonnet-5-5", "role": "assistant",
                 "content": [{"type": "text", "text": "Fixed the off-by-one in app.py; all 4 tests pass."}],
                 "usage": {"input_tokens": 1700, "output_tokens": 1}}},
    {"type": "result", "subtype": "success", "is_error": False, "num_turns": 3, "duration_ms": 42000,
     "duration_api_ms": 30000, "total_cost_usd": 0.0412, "session_id": "s-1",
     "result": "## Report\nFixed the off-by-one in `app.py`; all 4 tests pass.",
     "usage": {"input_tokens": 4400, "output_tokens": 600, "cache_read_input_tokens": 0,
               "cache_creation_input_tokens": 0},
     "modelUsage": {"claude-sonnet-5-5": {"inputTokens": 4400, "outputTokens": 650, "cacheReadInputTokens": 100,
                                          "cacheCreationInputTokens": 50, "costUSD": 0.04},
                    "claude-haiku-5-5": {"inputTokens": 300, "outputTokens": 20, "cacheReadInputTokens": 0,
                                         "cacheCreationInputTokens": 0, "costUSD": 0.0012}}},
]

CODEX_EVENTS = [
    {"type": "thread.started", "thread_id": "th-1"},
    {"type": "turn.started"},
    {"type": "item.completed", "item": {"id": "item_0", "type": "reasoning", "text": "Plan: inspect repo"}},
    {"type": "item.started", "item": {"id": "item_1", "type": "command_execution", "command": "bash -lc ls",
                                      "aggregated_output": "", "exit_code": None, "status": "in_progress"}},
    {"type": "item.completed", "item": {"id": "item_1", "type": "command_execution", "command": "bash -lc ls",
                                        "aggregated_output": "app.py\n", "exit_code": 0, "status": "completed"}},
    {"type": "item.started", "item": {"id": "item_2", "type": "todo_list",
                                      "items": [{"text": "fix bug", "completed": False}]}},
    {"type": "item.completed", "item": {"id": "item_3", "type": "file_change", "status": "completed",
                                        "changes": [{"path": "app.py", "kind": "update"}]}},
    {"type": "error", "message": "stream disconnected, retrying"},
    {"type": "item.completed", "item": {"id": "item_4", "type": "agent_message", "text": "Done: patched app.py."}},
    {"type": "turn.completed", "usage": {"input_tokens": 5000, "cached_input_tokens": 1000, "output_tokens": 700}},
]


def claude_run_lines(finish_patch: dict | None = None, outputs: dict | None = None) -> list[str]:
    lines = [runner("start", "task"), runner("ready", "workspace prepared", baseline="abc")]
    lines += [wrap("claude", e) for e in CLAUDE_EVENTS]
    lines.append(json.dumps({"t": "stderr", "line": "some warning"}))
    lines.append(runner("collect", "collecting changes and outputs"))
    lines.append(json.dumps({"t": "finish", "exit_code": 0, "stopped": False, "duration_s": 42.0,
                             "patch": finish_patch or {"files": 1, "insertions": 1, "deletions": 1, "bytes": 0,
                                                       "paths": ["app.py"]},
                             "outputs": outputs or {"count": 0, "files": []}}))
    return lines
