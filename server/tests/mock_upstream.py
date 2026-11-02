"""Scripted model upstream for end-to-end tests (sits behind new-api as channels).

/v1/messages (Anthropic): main-loop requests (with tools) first ask to Write a file, the turn after the
tool result ends with a report; requests without tools (background helpers) get a short text answer.
/v1/responses (OpenAI Responses API, used by Codex): answers with a single final message.
"""

from __future__ import annotations

import json
import os
import threading
import time

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

INPUT_TOKENS = 1000
OUTPUT_TOKENS = 50


class Script:
    write_path = ""
    requests: list[dict] = []


def _last_user_has_tool_result(body: dict) -> bool:
    for message in reversed(body.get("messages") or []):
        if message.get("role") != "user":
            continue
        content = message.get("content")
        return isinstance(content, list) and any(b.get("type") == "tool_result" for b in content)
    return False


def _reply(body: dict) -> tuple[list[dict], str]:
    tools = {t.get("name") for t in body.get("tools") or []}
    if "Write" in tools and not _last_user_has_tool_result(body):
        return [{"type": "tool_use", "id": "toolu_mock_1", "name": "Write",
                 "input": {"file_path": Script.write_path, "content": "hello from the cloud agent\n"}}], "tool_use"
    if tools:
        return [{"type": "text", "text": "## Report\nCreated hello.txt with a greeting. Verified by reading it back."}], "end_turn"
    return [{"type": "text", "text": "ok"}], "end_turn"


def _sse(event: str, data: dict) -> bytes:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n".encode()


def create_app() -> FastAPI:
    app = FastAPI()

    @app.post("/v1/messages/count_tokens")
    async def count_tokens(_: Request):
        return {"input_tokens": INPUT_TOKENS}

    @app.post("/v1/messages")
    async def messages(request: Request):
        body = await request.json()
        Script.requests.append(body)
        blocks, stop = _reply(body)
        msg_id = f"msg_mock_{len(Script.requests)}"
        model = body.get("model", "mock")
        usage_in = {"input_tokens": INPUT_TOKENS, "output_tokens": 1, "cache_read_input_tokens": 0,
                    "cache_creation_input_tokens": 0}
        if not body.get("stream"):
            return JSONResponse({"id": msg_id, "type": "message", "role": "assistant", "model": model,
                                 "content": blocks, "stop_reason": stop, "stop_sequence": None,
                                 "usage": {**usage_in, "output_tokens": OUTPUT_TOKENS}})

        def stream():
            yield _sse("message_start", {"type": "message_start", "message": {
                "id": msg_id, "type": "message", "role": "assistant", "model": model, "content": [],
                "stop_reason": None, "stop_sequence": None, "usage": usage_in}})
            for i, block in enumerate(blocks):
                if block["type"] == "text":
                    yield _sse("content_block_start", {"type": "content_block_start", "index": i,
                                                       "content_block": {"type": "text", "text": ""}})
                    yield _sse("content_block_delta", {"type": "content_block_delta", "index": i,
                                                       "delta": {"type": "text_delta", "text": block["text"]}})
                else:
                    yield _sse("content_block_start", {"type": "content_block_start", "index": i, "content_block": {
                        "type": "tool_use", "id": block["id"], "name": block["name"], "input": {}}})
                    yield _sse("content_block_delta", {"type": "content_block_delta", "index": i, "delta": {
                        "type": "input_json_delta", "partial_json": json.dumps(block["input"])}})
                yield _sse("content_block_stop", {"type": "content_block_stop", "index": i})
            yield _sse("message_delta", {"type": "message_delta", "delta": {"stop_reason": stop, "stop_sequence": None},
                                         "usage": {"output_tokens": OUTPUT_TOKENS}})
            yield _sse("message_stop", {"type": "message_stop"})

        return StreamingResponse(stream(), media_type="text/event-stream")

    @app.post("/v1/responses")
    async def responses(request: Request):
        body = await request.json()
        Script.requests.append(body)
        n = len(Script.requests)
        model = body.get("model", "mock")
        text = "## Report\nNothing to change; the workspace already satisfies the request."
        item = {"type": "message", "id": f"msg_{n}", "status": "completed", "role": "assistant",
                "content": [{"type": "output_text", "text": text, "annotations": []}]}
        usage = {"input_tokens": INPUT_TOKENS, "input_tokens_details": {"cached_tokens": 0},
                 "output_tokens": OUTPUT_TOKENS, "output_tokens_details": {"reasoning_tokens": 0},
                 "total_tokens": INPUT_TOKENS + OUTPUT_TOKENS}
        base = {"id": f"resp_{n}", "object": "response", "created_at": int(time.time()), "model": model}

        def stream():
            def ev(kind: str, **data):
                return f"event: {kind}\ndata: {json.dumps({'type': kind, **data})}\n\n".encode()

            yield ev("response.created", response={**base, "status": "in_progress", "output": []})
            yield ev("response.output_item.added", output_index=0,
                     item={**item, "status": "in_progress", "content": []})
            yield ev("response.output_text.delta", item_id=item["id"], output_index=0, content_index=0, delta=text)
            yield ev("response.output_item.done", output_index=0, item=item)
            yield ev("response.completed", response={**base, "status": "completed", "output": [item], "usage": usage})

        return StreamingResponse(stream(), media_type="text/event-stream")

    return app


def serve_in_thread(port: int, host: str | None = None) -> uvicorn.Server:
    """Start the scripted upstream on ``host`` (default MOCK_BIND_HOST, else loopback).

    When new-api runs in a container it reaches the host as host.docker.internal, which needs a
    non-loopback listener: set MOCK_BIND_HOST=0.0.0.0 for that setup.
    """
    host = host or os.environ.get("MOCK_BIND_HOST", "127.0.0.1")
    server = uvicorn.Server(uvicorn.Config(create_app(), host=host, port=port, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    return server
