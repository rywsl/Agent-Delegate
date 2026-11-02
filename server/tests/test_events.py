from __future__ import annotations

from streams import CLAUDE_EVENTS, CODEX_EVENTS, claude_run_lines, wrap

from delegate.events import Normalizer


def kinds(events):
    return [e.kind for e in events]


def test_claude_stream():
    n = Normalizer()
    out = []
    for line in claude_run_lines():
        out += n.feed_line(line)
    assert kinds(out) == ["phase", "phase", "system", "thinking", "tool_call", "tool_result", "error", "tool_call",
                          "tool_result", "message", "agent_result", "stderr", "phase", "finish"]
    call = out[4]
    assert call.summary == "Bash: pytest -q" and call.data["input"]["command"] == "pytest -q"
    assert out[3].data["usage"]["input_tokens"] == 1200
    assert out[5].summary.startswith("ok: 1 failed")
    assert out[8].data["content"] == "File updated"
    assert n.final_message.startswith("## Report")
    u = n.usage
    # modelUsage (main loop + background model) wins over the main-loop-only usage block
    assert (u.input_tokens, u.output_tokens, u.cache_read_tokens, u.cache_write_tokens) == (4700, 670, 100, 50)
    assert u.turns == 3 and not u.is_error and u.reported_cost_usd == 0.0412
    assert n.finish["exit_code"] == 0


def test_claude_error_result_is_error_even_with_success_subtype():
    n = Normalizer()
    n.feed_line(wrap("claude", {"type": "result", "subtype": "success", "is_error": True, "num_turns": 1,
                                "result": "API Error: 403 token quota exhausted", "usage": {}}))
    assert n.usage.is_error and "quota exhausted" in n.usage.error


def test_claude_max_turns():
    n = Normalizer()
    n.feed_line(wrap("claude", {"type": "result", "subtype": "error_max_turns", "is_error": True, "num_turns": 5,
                                "errors": ["Reached maximum number of turns (5)"], "usage": {}}))
    assert n.usage.is_error and "maximum number of turns" in n.usage.error and n.final_message is None


def test_codex_stream():
    n = Normalizer()
    out = []
    for event in CODEX_EVENTS:
        out += n.feed_line(wrap("codex", event))
    assert kinds(out) == ["system", "thinking", "tool_call", "tool_result", "todo", "file_change", "error",
                          "message", "usage"]
    assert out[2].summary == "$ bash -lc ls" and out[3].summary.startswith("exit 0")
    assert out[5].summary == "update app.py"
    assert n.final_message == "Done: patched app.py."
    assert (n.usage.input_tokens, n.usage.cache_read_tokens, n.usage.output_tokens) == (5000, 1000, 700)
    assert not n.usage.is_error  # a retried stream error is not a failure


def test_codex_usage_is_cumulative():
    n = Normalizer()
    n.feed_line(wrap("codex", {"type": "turn.completed", "usage": {"input_tokens": 100, "output_tokens": 10}}))
    n.feed_line(wrap("codex", {"type": "turn.completed", "usage": {"input_tokens": 250, "output_tokens": 30}}))
    assert (n.usage.input_tokens, n.usage.output_tokens, n.usage.turns) == (250, 30, 2)


def test_garbage_and_large_fields_are_bounded():
    n = Normalizer()
    assert kinds(n.feed_line("not json")) == ["log"]
    assert n.feed_line("   ") == []
    huge = "x" * 200_000
    [event] = n.feed_line(wrap("claude", {"type": "user", "message": {"content": [
        {"type": "tool_result", "tool_use_id": "t", "content": huge}]}}))
    assert len(event.data["content"]) < 70_000 and "truncated" in event.data["content"]
    assert len(event.summary) <= 300
