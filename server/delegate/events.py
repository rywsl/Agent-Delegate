"""Normalise the sandbox runner's JSONL stream into audit events.

The runner (sandbox/runner.py) wraps everything it prints in an envelope:

    {"t": "runner", "phase": "...", "msg": "..."}       lifecycle of the sandbox itself
    {"t": "agent", "agent": "claude"|"codex", "event": {...}}  one line of the agent CLI's JSON stream
    {"t": "stderr", "line": "..."}                     agent CLI stderr
    {"t": "finish", ...}                               final report written by the runner

Every envelope is turned into zero or more ``NormEvent`` rows for the audit timeline, while
``UsageTracker`` keeps the agent-reported token usage and the final answer.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

MAX_FIELD_CHARS = 64_000
SUMMARY_CHARS = 300


@dataclass
class NormEvent:
    kind: str
    summary: str
    data: dict[str, Any] = field(default_factory=dict)


def clip(text: Any, limit: int = SUMMARY_CHARS) -> str:
    if text is None:
        return ""
    if not isinstance(text, str):
        text = json.dumps(text, ensure_ascii=False)
    text = text.strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def shrink(value: Any, limit: int = MAX_FIELD_CHARS) -> Any:
    """Bound the size of large strings stored in the database (the raw log keeps everything)."""
    if isinstance(value, str):
        if len(value) > limit:
            return value[:limit] + f"\n…[truncated {len(value) - limit} chars; see raw log]"
        return value
    if isinstance(value, dict):
        return {k: shrink(v, limit) for k, v in value.items()}
    if isinstance(value, list):
        return [shrink(v, limit) for v in value]
    return value


def _tool_result_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
            elif isinstance(block, dict):
                parts.append(f"[{block.get('type', 'block')}]")
        return "\n".join(parts)
    return json.dumps(content, ensure_ascii=False) if content is not None else ""


def _describe_tool_input(name: str, args: Any) -> str:
    if not isinstance(args, dict):
        return clip(args, 200)
    for key in ("command", "file_path", "path", "pattern", "url", "query", "description", "prompt"):
        if key in args and isinstance(args[key], str):
            return clip(args[key], 200)
    return clip(args, 200)


@dataclass
class UsageTracker:
    """Token usage and the final answer as reported by the agent CLI itself.

    Billing never relies on these numbers (new-api's logs are authoritative); they are kept to
    cross-check and to show per-turn detail in the audit view.
    """

    agent: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    turns: int = 0
    reported_cost_usd: float | None = None
    final_message: str | None = None
    result_subtype: str | None = None
    is_error: bool = False
    error: str | None = None
    session_id: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "agent": self.agent,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cache_read_tokens": self.cache_read_tokens,
            "cache_write_tokens": self.cache_write_tokens,
            "turns": self.turns,
            "reported_cost_usd": self.reported_cost_usd,
            "result_subtype": self.result_subtype,
            "is_error": self.is_error,
            "error": self.error,
            "session_id": self.session_id,
        }


class Normalizer:
    def __init__(self) -> None:
        self.usage = UsageTracker()
        self.finish: dict[str, Any] | None = None
        self._last_codex_message: str | None = None

    # ------------------------------------------------------------------ entry point
    def feed_line(self, line: str) -> list[NormEvent]:
        line = line.strip()
        if not line:
            return []
        try:
            envelope = json.loads(line)
        except json.JSONDecodeError:
            return [NormEvent("log", clip(line), {"line": shrink(line)})]
        if not isinstance(envelope, dict):
            return [NormEvent("log", clip(line), {"line": shrink(line)})]
        kind = envelope.get("t")
        if kind == "runner":
            return [self._runner(envelope)]
        if kind == "stderr":
            text = envelope.get("line", "")
            return [NormEvent("stderr", clip(text), {"line": shrink(text)})]
        if kind == "finish":
            self.finish = envelope
            return [NormEvent("finish", self._finish_summary(envelope), shrink(envelope))]
        if kind == "agent":
            agent = envelope.get("agent", "")
            self.usage.agent = agent
            event = envelope.get("event")
            if not isinstance(event, dict):
                return [NormEvent("log", clip(event), {"event": shrink(event)})]
            if agent == "claude":
                return self._claude(event)
            if agent == "codex":
                return self._codex(event)
            return [NormEvent("log", clip(event), shrink(event))]
        return [NormEvent("log", clip(envelope), shrink(envelope))]

    @property
    def final_message(self) -> str | None:
        return self.usage.final_message or self._last_codex_message

    # ------------------------------------------------------------------ runner
    @staticmethod
    def _runner(env: dict[str, Any]) -> NormEvent:
        phase = env.get("phase", "")
        msg = env.get("msg", "")
        data = {k: v for k, v in env.items() if k != "t"}
        return NormEvent("phase", clip(f"[{phase}] {msg}" if msg else f"[{phase}]"), shrink(data))

    @staticmethod
    def _finish_summary(env: dict[str, Any]) -> str:
        patch = env.get("patch") or {}
        return clip(
            f"agent exited with code {env.get('exit_code')}; "
            f"{patch.get('files', 0)} file(s) changed, +{patch.get('insertions', 0)}/-{patch.get('deletions', 0)}"
        )

    # ------------------------------------------------------------------ claude code (stream-json)
    def _claude(self, ev: dict[str, Any]) -> list[NormEvent]:
        etype = ev.get("type")
        if etype == "system":
            subtype = ev.get("subtype")
            if subtype == "init":
                self.usage.session_id = ev.get("session_id")
                summary = (f"session started (model={ev.get('model')}, tools={len(ev.get('tools') or [])}, "
                           f"claude code {ev.get('claude_code_version', '?')})")
                return [NormEvent("system", summary, shrink(ev))]
            if subtype == "api_retry":
                summary = f"API retry {ev.get('attempt')}/{ev.get('max_retries')}: {ev.get('error_status')} {ev.get('error')}"
                return [NormEvent("error", clip(summary), shrink(ev))]
            if subtype == "permission_denied":
                return [NormEvent("error", clip(f"permission denied: {ev.get('tool_name')}: {ev.get('message')}"),
                                  shrink(ev))]
            return [NormEvent("system", clip(f"system: {subtype}"), shrink(ev))]

        if etype == "assistant":
            message = ev.get("message") or {}
            usage = message.get("usage") or {}
            out: list[NormEvent] = []
            for block in message.get("content") or []:
                btype = block.get("type")
                if btype == "text":
                    out.append(NormEvent("message", clip(block.get("text")), shrink({"text": block.get("text")})))
                elif btype in ("thinking", "redacted_thinking"):
                    text = block.get("thinking") or ""
                    out.append(NormEvent("thinking", clip(text) or "(redacted)", shrink({"text": text})))
                elif btype in ("tool_use", "server_tool_use"):
                    name = block.get("name", "?")
                    out.append(
                        NormEvent(
                            "tool_call",
                            clip(f"{name}: {_describe_tool_input(name, block.get('input'))}"),
                            shrink({"id": block.get("id"), "name": name, "input": block.get("input")}),
                        )
                    )
                else:
                    out.append(NormEvent("log", clip(f"assistant block: {btype}"), shrink(block)))
            if out and usage:
                out[0].data["usage"] = usage
                out[0].data["message_id"] = message.get("id")
            return out

        if etype == "user":
            message = ev.get("message") or {}
            content = message.get("content")
            out = []
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "tool_result":
                        text = _tool_result_text(block.get("content"))
                        prefix = "error" if block.get("is_error") else "ok"
                        out.append(
                            NormEvent(
                                "tool_result",
                                clip(f"{prefix}: {text}"),
                                shrink(
                                    {
                                        "tool_use_id": block.get("tool_use_id"),
                                        "is_error": bool(block.get("is_error")),
                                        "content": text,
                                    }
                                ),
                            )
                        )
            return out or [NormEvent("log", "user message", shrink(ev))]

        if etype == "result":
            # modelUsage also covers subagents and compaction; usage only the main loop.
            per_model = ev.get("modelUsage") or {}
            if per_model:
                def total(key: str) -> int:
                    return sum(int(m.get(key) or 0) for m in per_model.values() if isinstance(m, dict))

                self.usage.input_tokens = total("inputTokens")
                self.usage.output_tokens = total("outputTokens")
                self.usage.cache_read_tokens = total("cacheReadInputTokens")
                self.usage.cache_write_tokens = total("cacheCreationInputTokens")
            else:
                usage = ev.get("usage") or {}
                self.usage.input_tokens = int(usage.get("input_tokens") or 0)
                self.usage.output_tokens = int(usage.get("output_tokens") or 0)
                self.usage.cache_read_tokens = int(usage.get("cache_read_input_tokens") or 0)
                self.usage.cache_write_tokens = int(usage.get("cache_creation_input_tokens") or 0)
            if ev.get("num_turns") is not None:
                self.usage.turns = int(ev["num_turns"])
            self.usage.reported_cost_usd = ev.get("total_cost_usd")
            self.usage.result_subtype = ev.get("subtype")
            self.usage.is_error = bool(ev.get("is_error")) or ev.get("subtype") != "success"
            if isinstance(ev.get("result"), str):
                self.usage.final_message = ev["result"]
            if self.usage.is_error:
                errors = ev.get("errors")
                self.usage.error = clip(errors if errors else ev.get("result") or ev.get("subtype"), 2000)
            summary = (
                f"{ev.get('subtype')}: turns={ev.get('num_turns')}, "
                f"in={self.usage.input_tokens}, out={self.usage.output_tokens}, "
                f"cache_read={self.usage.cache_read_tokens}"
            )
            return [NormEvent("agent_result", clip(summary), shrink(ev))]

        if etype == "stream_event":
            return []  # partial deltas are not useful in the audit trail
        return [NormEvent("log", clip(f"claude: {etype}"), shrink(ev))]

    # ------------------------------------------------------------------ codex (exec --json)
    def _codex(self, ev: dict[str, Any]) -> list[NormEvent]:
        etype = ev.get("type", "")
        if etype == "thread.started":
            self.usage.session_id = ev.get("thread_id")
            return [NormEvent("system", clip(f"thread started ({ev.get('thread_id')})"), shrink(ev))]
        if etype == "turn.started":
            return []
        if etype == "turn.completed":
            # usage is the thread's cumulative total, not a per-turn delta
            usage = ev.get("usage") or {}
            self.usage.turns += 1
            self.usage.input_tokens = int(usage.get("input_tokens") or 0)
            self.usage.cache_read_tokens = int(usage.get("cached_input_tokens") or 0)
            self.usage.cache_write_tokens = int(usage.get("cache_write_input_tokens") or 0)
            self.usage.output_tokens = int(usage.get("output_tokens") or 0)
            summary = (
                f"turn completed: in={usage.get('input_tokens', 0)}, "
                f"cached={usage.get('cached_input_tokens', 0)}, out={usage.get('output_tokens', 0)}"
            )
            return [NormEvent("usage", summary, shrink(ev))]
        if etype == "turn.failed":
            err = (ev.get("error") or {}).get("message") if isinstance(ev.get("error"), dict) else ev.get("error")
            self.usage.is_error = True
            self.usage.error = clip(err, 2000)
            return [NormEvent("error", clip(f"turn failed: {err}"), shrink(ev))]
        if etype == "error":
            self.usage.error = clip(ev.get("message"), 2000)
            return [NormEvent("error", clip(ev.get("message")), shrink(ev))]
        if etype.startswith("item."):
            return self._codex_item(etype, ev.get("item") or {})
        return [NormEvent("log", clip(f"codex: {etype}"), shrink(ev))]

    def _codex_item(self, etype: str, item: dict[str, Any]) -> list[NormEvent]:
        itype = item.get("type") or item.get("item_type") or ""
        done = etype == "item.completed"
        if itype == "agent_message":
            if not done:
                return []
            self._last_codex_message = item.get("text")
            return [NormEvent("message", clip(item.get("text")), shrink(item))]
        if itype == "reasoning":
            if not done:
                return []
            return [NormEvent("thinking", clip(item.get("text")), shrink(item))]
        if itype == "command_execution":
            if etype == "item.started":
                return [NormEvent("tool_call", clip(f"$ {item.get('command')}"), shrink(item))]
            if not done:
                return []
            summary = f"exit {item.get('exit_code')}: {clip(item.get('aggregated_output'), 200)}"
            return [NormEvent("tool_result", clip(summary), shrink(item))]
        if itype == "file_change":
            if not done:
                return []
            changes = item.get("changes") or []
            desc = ", ".join(f"{c.get('kind')} {c.get('path')}" for c in changes if isinstance(c, dict))
            return [NormEvent("file_change", clip(desc or "file change"), shrink(item))]
        if itype == "mcp_tool_call":
            if etype == "item.started":
                return [NormEvent("tool_call", clip(f"mcp {item.get('server')}.{item.get('tool')}"), shrink(item))]
            if not done:
                return []
            return [NormEvent("tool_result", clip(f"mcp {item.get('tool')}: {item.get('status')}"), shrink(item))]
        if itype == "web_search":
            if not done:
                return []
            action = item.get("action") or {}
            what = item.get("query") or action.get("query") or action.get("url") or action.get("type")
            return [NormEvent("tool_call", clip(f"web_search: {what}"), shrink(item))]
        if itype == "collab_tool_call":
            if etype == "item.started":
                return [NormEvent("tool_call", clip(f"subagent {item.get('tool')}: {item.get('prompt') or ''}"),
                                  shrink(item))]
            if not done:
                return []
            return [NormEvent("tool_result", clip(f"subagent {item.get('tool')}: {item.get('status')}"), shrink(item))]
        if itype == "todo_list":
            items = item.get("items") or []
            desc = "; ".join(f"[{'x' if t.get('completed') else ' '}] {t.get('text')}" for t in items)
            return [NormEvent("todo", clip(desc or "todo list"), shrink(item))]
        if itype == "error":
            return [NormEvent("error", clip(item.get("message")), shrink(item))]
        if not done:
            return []
        return [NormEvent("log", clip(f"codex item: {itype}"), shrink(item))]
