from __future__ import annotations

import json
import os
import subprocess
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

TOOL_SCHEMAS = [
    {
        "name": "bash",
        "description": "Run a shell command in /workspace. Use this for searches, tests, builds and git operations.",
        "parameters": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Command to execute with bash."},
                "timeout": {"type": "integer", "description": "Timeout in seconds, from 1 to 300.", "default": 120},
            },
            "required": ["command"],
        },
    },
    {
        "name": "read_file",
        "description": "Read a UTF-8 text file from /workspace or /outputs.",
        "parameters": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    },
    {
        "name": "write_file",
        "description": "Create or replace a UTF-8 text file in /workspace or /outputs, creating parent directories.",
        "parameters": {
            "type": "object",
            "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
            "required": ["path", "content"],
        },
    },
    {
        "name": "edit_file",
        "description": "Replace exact text in a file. The old text must occur at least once.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "old_string": {"type": "string"},
                "new_string": {"type": "string"},
                "replace_all": {"type": "boolean", "default": False},
            },
            "required": ["path", "old_string", "new_string"],
        },
    },
    {
        "name": "list_files",
        "description": "List files below a directory in /workspace or /outputs.",
        "parameters": {
            "type": "object",
            "properties": {"path": {"type": "string", "default": "."}},
        },
    },
]

MAX_TOOL_OUTPUT = 60_000


def make_client(provider: str, api_key: str, base_url: str | None, timeout: int):
    if provider == "openai":
        from openai import OpenAI

        return OpenAI(api_key=api_key, base_url=base_url, timeout=timeout)
    if provider == "anthropic":
        from anthropic import Anthropic

        return Anthropic(api_key=api_key, base_url=base_url, timeout=timeout)
    if provider == "gemini":
        from google import genai
        from google.genai import types

        options = types.HttpOptions(base_url=base_url, timeout=timeout * 1000) if base_url else None
        return genai.Client(api_key=api_key, http_options=options)
    raise ValueError(f"unknown provider {provider}")


class SDKAgent:
    def __init__(
        self,
        spec: dict[str, Any],
        api_key: str,
        workspace: Path,
        outputs: Path,
        emit: Callable[[dict], None],
        should_stop: Callable[[], bool],
        client: Any = None,
    ) -> None:
        self.spec = spec
        self.provider = spec["provider"]
        self.api_key = api_key
        self.workspace = workspace.resolve()
        self.outputs = outputs.resolve()
        self.emit = emit
        self.should_stop = should_stop
        self.client = client or make_client(
            self.provider, api_key, spec.get("base_url"), int(spec.get("request_timeout_s") or 300)
        )
        self.usage = {"input_tokens": 0, "output_tokens": 0, "cache_read_tokens": 0, "cache_write_tokens": 0}
        self.turns = 0

    def run(self) -> int:
        try:
            if self.provider == "openai":
                return self._run_openai()
            if self.provider == "anthropic":
                return self._run_anthropic()
            if self.provider == "gemini":
                return self._run_gemini()
            return self._finish(error=f"unknown provider {self.provider}")
        except Exception as exc:
            message = str(exc).replace(self.api_key, "[redacted]")
            return self._finish(error=f"{self.provider} SDK request failed: {message}")

    def _run_openai(self) -> int:
        messages = [
            {"role": "system", "content": self.spec["system_prompt"]},
            {"role": "user", "content": self.spec["prompt"]},
        ]
        tools = [
            {"type": "function", "function": {"name": t["name"], "description": t["description"], "parameters": t["parameters"]}}
            for t in TOOL_SCHEMAS
        ]
        for _ in range(int(self.spec["max_turns"])):
            if self.should_stop():
                return 130
            response = self.client.chat.completions.create(
                model=self.spec["model"], messages=messages, tools=tools
            )
            self.turns += 1
            self._track(response.usage)
            message = response.choices[0].message
            blocks = []
            if message.content:
                blocks.append({"type": "text", "text": message.content})
            calls = list(message.tool_calls or [])
            for call in calls:
                args = self._arguments(call.function.arguments)
                blocks.append({"type": "tool_use", "id": call.id, "name": call.function.name, "input": args})
            self._assistant(blocks, response.usage)
            messages.append(message.model_dump(exclude_none=True))
            if not calls:
                return self._finish(message.content or "")
            for call, block in zip(calls, blocks[-len(calls):]):
                result, is_error = self._call_tool(call.function.name, block["input"])
                self._tool_result(call.id, result, is_error)
                messages.append({"role": "tool", "tool_call_id": call.id, "content": result})
        return self._finish(error="maximum agent turns reached")

    def _run_anthropic(self) -> int:
        messages = [{"role": "user", "content": self.spec["prompt"]}]
        tools = [{"name": t["name"], "description": t["description"], "input_schema": t["parameters"]} for t in TOOL_SCHEMAS]
        for _ in range(int(self.spec["max_turns"])):
            if self.should_stop():
                return 130
            response = self.client.messages.create(
                model=self.spec["model"],
                max_tokens=int(self.spec.get("max_output_tokens") or 8192),
                system=self.spec["system_prompt"],
                messages=messages,
                tools=tools,
            )
            self.turns += 1
            self._track(response.usage)
            blocks = []
            calls = []
            for block in response.content:
                if block.type == "text":
                    blocks.append({"type": "text", "text": block.text})
                elif block.type == "tool_use":
                    item = {"type": "tool_use", "id": block.id, "name": block.name, "input": block.input}
                    blocks.append(item)
                    calls.append(item)
            self._assistant(blocks, response.usage)
            messages.append({"role": "assistant", "content": [b.model_dump() for b in response.content]})
            if not calls:
                return self._finish("".join(b["text"] for b in blocks if b["type"] == "text"))
            results = []
            for call in calls:
                result, is_error = self._call_tool(call["name"], call["input"])
                self._tool_result(call["id"], result, is_error)
                results.append({
                    "type": "tool_result", "tool_use_id": call["id"], "content": result, "is_error": is_error,
                })
            messages.append({"role": "user", "content": results})
        return self._finish(error="maximum agent turns reached")

    def _run_gemini(self) -> int:
        from google.genai import types

        declarations = [
            types.FunctionDeclaration(
                name=t["name"], description=t["description"], parameters_json_schema=t["parameters"]
            )
            for t in TOOL_SCHEMAS
        ]
        config = types.GenerateContentConfig(
            system_instruction=self.spec["system_prompt"],
            tools=[types.Tool(function_declarations=declarations)],
            max_output_tokens=int(self.spec.get("max_output_tokens") or 8192),
        )
        contents: list[Any] = [self.spec["prompt"]]
        for _ in range(int(self.spec["max_turns"])):
            if self.should_stop():
                return 130
            response = self.client.models.generate_content(model=self.spec["model"], contents=contents, config=config)
            self.turns += 1
            self._track(response.usage_metadata)
            if not response.candidates:
                return self._finish(error="Gemini returned no candidates")
            content = response.candidates[0].content
            contents.append(content)
            blocks = []
            calls = []
            for part in content.parts or []:
                if part.text:
                    blocks.append({"type": "text", "text": part.text})
                if part.function_call:
                    call = part.function_call
                    item = {
                        "type": "tool_use",
                        "id": call.id or f"gemini-{self.turns}-{len(calls)}",
                        "name": call.name,
                        "input": dict(call.args or {}),
                    }
                    blocks.append(item)
                    calls.append(call)
            self._assistant(blocks, response.usage_metadata)
            if not calls:
                return self._finish("".join(b["text"] for b in blocks if b["type"] == "text"))
            response_parts = []
            for call in calls:
                result, is_error = self._call_tool(call.name, dict(call.args or {}))
                self._tool_result(call.id or call.name, result, is_error)
                response_parts.append(types.Part.from_function_response(
                    name=call.name, response={"result": result, "is_error": is_error}
                ))
            contents.append(types.Content(role="user", parts=response_parts))
        return self._finish(error="maximum agent turns reached")

    @staticmethod
    def _arguments(raw: str) -> dict[str, Any]:
        try:
            value = json.loads(raw or "{}")
            return value if isinstance(value, dict) else {"value": value}
        except json.JSONDecodeError as exc:
            return {"_invalid_arguments": str(exc), "_raw": raw}

    def _track(self, usage: Any) -> None:
        if usage is None:
            return
        self.usage["input_tokens"] += int(
            getattr(usage, "prompt_tokens", None) or getattr(usage, "input_tokens", None)
            or getattr(usage, "prompt_token_count", None) or 0
        )
        self.usage["output_tokens"] += int(
            getattr(usage, "completion_tokens", None) or getattr(usage, "output_tokens", None)
            or getattr(usage, "candidates_token_count", None) or 0
        )
        self.usage["cache_read_tokens"] += int(
            getattr(usage, "cache_read_input_tokens", None) or getattr(usage, "cached_content_token_count", None) or 0
        )
        self.usage["cache_write_tokens"] += int(getattr(usage, "cache_creation_input_tokens", None) or 0)

    def _assistant(self, blocks: list[dict], usage: Any) -> None:
        usage_data = {
            "input_tokens": self.usage["input_tokens"],
            "output_tokens": self.usage["output_tokens"],
            "cache_read_input_tokens": self.usage["cache_read_tokens"],
            "cache_creation_input_tokens": self.usage["cache_write_tokens"],
        }
        self.emit_event({"type": "assistant", "message": {"content": blocks, "usage": usage_data}})

    def _tool_result(self, call_id: str, result: str, is_error: bool) -> None:
        self.emit_event({"type": "user", "message": {"content": [{
            "type": "tool_result", "tool_use_id": call_id, "content": result, "is_error": is_error,
        }]}})

    def _finish(self, text: str = "", error: str | None = None) -> int:
        self.emit_event({
            "type": "result",
            "subtype": "success" if error is None else "error",
            "is_error": error is not None,
            "result": error or text,
            "errors": [error] if error else [],
            "num_turns": self.turns,
            "usage": self.usage,
        })
        return 1 if error else 0

    def emit_event(self, event: dict) -> None:
        self.emit({"t": "agent", "agent": self.provider, "event": event})

    def _path(self, raw: str) -> Path:
        path = Path(raw or ".")
        if path.is_absolute():
            if path == self.outputs or self.outputs in path.parents:
                target = path
            elif path == self.workspace or self.workspace in path.parents:
                target = path
            else:
                raise ValueError("path must be inside /workspace or /outputs")
        else:
            target = self.workspace / path
        target = target.resolve()
        if target != self.workspace and self.workspace not in target.parents and target != self.outputs and self.outputs not in target.parents:
            raise ValueError("path escapes the allowed directories")
        if self.workspace in target.parents and ".git" in target.relative_to(self.workspace).parts:
            raise ValueError("access to .git is not allowed")
        return target

    def _call_tool(self, name: str, args: dict[str, Any]) -> tuple[str, bool]:
        try:
            if "_invalid_arguments" in args:
                raise ValueError(args["_invalid_arguments"])
            if name == "bash":
                return self._bash(str(args["command"]), int(args.get("timeout") or 120)), False
            if name == "read_file":
                path = self._path(str(args["path"]))
                data = path.read_bytes()
                if len(data) > MAX_TOOL_OUTPUT:
                    return f"file is too large ({len(data)} bytes; limit {MAX_TOOL_OUTPUT})", True
                return data.decode("utf-8"), False
            if name == "write_file":
                path = self._path(str(args["path"]))
                content = str(args["content"])
                if len(content.encode()) > 1024 * 1024:
                    raise ValueError("write_file content exceeds 1 MB")
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content)
                return f"wrote {path}", False
            if name == "edit_file":
                path = self._path(str(args["path"]))
                content = path.read_text()
                old, new = str(args["old_string"]), str(args["new_string"])
                count = content.count(old)
                if not old or not count:
                    return "old_string not found", True
                if count > 1 and not args.get("replace_all"):
                    return f"old_string occurs {count} times; set replace_all or use more context", True
                path.write_text(content.replace(old, new, -1 if args.get("replace_all") else 1))
                return f"edited {path}", False
            if name == "list_files":
                path = self._path(str(args.get("path") or "."))
                files = [p for p in path.rglob("*") if p.is_file() and ".git" not in p.parts]
                return "\n".join(str(p.relative_to(self.workspace)) for p in sorted(files)[:2000]), False
            return f"unknown tool {name}", True
        except (KeyError, OSError, UnicodeError, ValueError) as exc:
            return str(exc), True

    def _bash(self, command: str, timeout: int) -> str:
        timeout = max(1, min(timeout, 300))
        env = {k: v for k, v in os.environ.items() if not k.endswith("_API_KEY") and k != "DELEGATE_LLM_API_KEY"}
        process = subprocess.Popen(
            ["bash", "-lc", command], cwd=self.workspace, env=env,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
        )
        deadline = time.monotonic() + timeout
        while process.poll() is None:
            if self.should_stop():
                process.terminate()
                break
            if time.monotonic() >= deadline:
                process.kill()
                break
            time.sleep(0.1)
        output, _ = process.communicate(timeout=10)
        if len(output) > MAX_TOOL_OUTPUT:
            output = output[:MAX_TOOL_OUTPUT] + "\n…[output truncated]"
        return f"exit code {process.returncode}\n{output}"
