from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest


@pytest.fixture()
def agent_module():
    path = Path(__file__).resolve().parents[2] / "sandbox" / "agent.py"
    spec = importlib.util.spec_from_file_location("delegate_sdk_agent", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _spec(provider):
    return {
        "provider": provider, "model": "test-model", "system_prompt": "SYS", "prompt": "write a file",
        "max_turns": 3, "max_output_tokens": 1000, "request_timeout_s": 30,
    }


def _run(module, provider, client, tmp_path):
    workspace, outputs = tmp_path / "workspace", tmp_path / "outputs"
    workspace.mkdir()
    outputs.mkdir()
    emitted = []
    agent = module.SDKAgent(_spec(provider), "secret", workspace, outputs, emitted.append, lambda: False, client=client)
    assert agent.run() == 0
    assert (workspace / "answer.txt").read_text() == "done"
    result = next(e["event"] for e in emitted if e["event"]["type"] == "result")
    assert result["result"] == "finished" and result["usage"]["input_tokens"] > 0


def test_openai_sdk_tool_loop(agent_module, tmp_path):
    class Message:
        def __init__(self, content=None, tool_calls=None):
            self.content, self.tool_calls = content, tool_calls

        def model_dump(self, exclude_none=True):
            return {"role": "assistant", "content": self.content,
                    "tool_calls": [{"id": c.id, "type": "function", "function": {
                        "name": c.function.name, "arguments": c.function.arguments,
                    }} for c in self.tool_calls or []]}

    call = SimpleNamespace(id="call-1", function=SimpleNamespace(
        name="write_file", arguments='{"path":"answer.txt","content":"done"}'
    ))
    responses = [
        SimpleNamespace(choices=[SimpleNamespace(message=Message(tool_calls=[call]))],
                        usage=SimpleNamespace(prompt_tokens=10, completion_tokens=2)),
        SimpleNamespace(choices=[SimpleNamespace(message=Message(content="finished"))],
                        usage=SimpleNamespace(prompt_tokens=20, completion_tokens=3)),
    ]
    completions = SimpleNamespace(create=lambda **kwargs: responses.pop(0))
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    _run(agent_module, "openai", client, tmp_path)


def test_anthropic_sdk_tool_loop(agent_module, tmp_path):
    class Block(SimpleNamespace):
        def model_dump(self):
            return dict(self.__dict__)

    first = SimpleNamespace(content=[Block(type="tool_use", id="toolu-1", name="write_file",
                                           input={"path": "answer.txt", "content": "done"})],
                            usage=SimpleNamespace(input_tokens=10, output_tokens=2))
    second = SimpleNamespace(content=[Block(type="text", text="finished")],
                             usage=SimpleNamespace(input_tokens=20, output_tokens=3))
    responses = [first, second]
    client = SimpleNamespace(messages=SimpleNamespace(create=lambda **kwargs: responses.pop(0)))
    _run(agent_module, "anthropic", client, tmp_path)


def test_gemini_sdk_tool_loop(agent_module, tmp_path, monkeypatch):
    types = ModuleType("google.genai.types")
    types.FunctionDeclaration = lambda **kwargs: kwargs
    types.Tool = lambda **kwargs: kwargs
    types.GenerateContentConfig = lambda **kwargs: kwargs

    class Part:
        def __init__(self, text=None, function_call=None):
            self.text, self.function_call = text, function_call

        @classmethod
        def from_function_response(cls, **kwargs):
            return cls()

    types.Part = Part
    types.Content = lambda **kwargs: SimpleNamespace(**kwargs)
    google = ModuleType("google")
    genai = ModuleType("google.genai")
    genai.types = types
    monkeypatch.setitem(sys.modules, "google", google)
    monkeypatch.setitem(sys.modules, "google.genai", genai)
    monkeypatch.setitem(sys.modules, "google.genai.types", types)

    call = SimpleNamespace(id="gem-1", name="write_file", args={"path": "answer.txt", "content": "done"})
    responses = [
        SimpleNamespace(candidates=[SimpleNamespace(content=SimpleNamespace(parts=[Part(function_call=call)]))],
                        usage_metadata=SimpleNamespace(prompt_token_count=10, candidates_token_count=2)),
        SimpleNamespace(candidates=[SimpleNamespace(content=SimpleNamespace(parts=[Part(text="finished")]))],
                        usage_metadata=SimpleNamespace(prompt_token_count=20, candidates_token_count=3)),
    ]
    client = SimpleNamespace(models=SimpleNamespace(generate_content=lambda **kwargs: responses.pop(0)))
    _run(agent_module, "gemini", client, tmp_path)


def test_file_tools_are_confined(agent_module, tmp_path):
    workspace, outputs = tmp_path / "workspace", tmp_path / "outputs"
    workspace.mkdir()
    outputs.mkdir()
    agent = agent_module.SDKAgent(_spec("openai"), "secret", workspace, outputs, lambda e: None,
                                  lambda: False, client=object())
    result, is_error = agent._call_tool("read_file", {"path": "../outside"})
    assert is_error and "allowed directories" in result
    result, is_error = agent._call_tool("read_file", {"path": ".git/config"})
    assert is_error and ".git" in result
