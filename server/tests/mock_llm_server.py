"""
Mock LLM Server — Anthropic Messages API compatible.

Responds with configurable sequences: text, tool_use, or mixed.
Supports keyword-based routing: if the user prompt contains a known
keyword, the matching canned response is returned regardless of the
sequence index.

Keyword map
-----------
  "run pwd"  → Bash(pwd), then text referencing the output
  "run ls"   → Bash(ls), then text
  "echo"     → Bash(echo hello), then text
  "delete"   → Bash(rm -rf /), then text (for deny testing)
  "edit"     → Bash(echo edit), then text

Used by integration tests to drive the agent loop deterministically.
"""

import asyncio
import time
import uuid
import argparse
from typing import Any
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import uvicorn
import logging

app = FastAPI(title="Mock LLM Server")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

_stats: dict[str, Any] = {
    "total_requests": 0,
    "start_time": None,
}

# Response sequence — each entry is returned in order, then the last one repeats.
_response_sequence: list[dict] = []
_response_index = 0


# ---------------------------------------------------------------------------
# Keyword → response mapping
# ---------------------------------------------------------------------------

def _keyword_response(prompt_lower: str) -> list[dict] | None:
    """Return a two-turn response list if the prompt matches a keyword."""
    if "run pwd" in prompt_lower:
        return [
            {
                "content": [
                    {"type": "text", "text": "I'll run pwd for you."},
                    {
                        "type": "tool_use",
                        "id": f"toolu_{uuid.uuid4().hex[:8]}",
                        "name": "Bash",
                        "input": {"command": "pwd"},
                    },
                ],
                "stop_reason": "tool_use",
            },
            {
                "content": [
                    {"type": "text", "text": "The current directory is shown above."},
                ],
                "stop_reason": "end_turn",
            },
        ]

    if "run ls" in prompt_lower:
        return [
            {
                "content": [
                    {"type": "text", "text": "I'll list the directory."},
                    {
                        "type": "tool_use",
                        "id": f"toolu_{uuid.uuid4().hex[:8]}",
                        "name": "Bash",
                        "input": {"command": "ls"},
                    },
                ],
                "stop_reason": "tool_use",
            },
            {
                "content": [
                    {"type": "text", "text": "Here are the files."},
                ],
                "stop_reason": "end_turn",
            },
        ]

    if "cat" in prompt_lower:
        return [
            {
                "content": [
                    {"type": "text", "text": "Running echo."},
                    {
                        "type": "tool_use",
                        "id": f"toolu_{uuid.uuid4().hex[:8]}",
                        "name": "Bash",
                        "input": {"command": "cat C:\\Users\\jorda\\Documents\\workspace\\model_containment\\CLAUDE.md"},
                    },
                ],
                "stop_reason": "tool_use",
            },
            {
                "content": [
                    {"type": "text", "text": "Echo completed."},
                ],
                "stop_reason": "end_turn",
            },
        ]

    if "echo" in prompt_lower:
        return [
            {
                "content": [
                    {"type": "text", "text": "Running echo."},
                    {
                        "type": "tool_use",
                        "id": f"toolu_{uuid.uuid4().hex[:8]}",
                        "name": "Bash",
                        "input": {"command": "echo hello"},
                    },
                ],
                "stop_reason": "tool_use",
            },
            {
                "content": [
                    {"type": "text", "text": "Echo completed."},
                ],
                "stop_reason": "end_turn",
            },
        ]

    if "delete" in prompt_lower or "rm " in prompt_lower:
        return [
            {
                "content": [
                    {"type": "text", "text": "I'll remove that."},
                    {
                        "type": "tool_use",
                        "id": f"toolu_{uuid.uuid4().hex[:8]}",
                        "name": "Bash",
                        "input": {"command": "rm -rf /tmp/test"},
                    },
                ],
                "stop_reason": "tool_use",
            },
            {
                "content": [
                    {"type": "text", "text": "Deletion complete."},
                ],
                "stop_reason": "end_turn",
            },
        ]

    if "edit" in prompt_lower:
        return [
            {
                "content": [
                    {"type": "text", "text": "I'll make that edit."},
                    {
                        "type": "tool_use",
                        "id": f"toolu_{uuid.uuid4().hex[:8]}",
                        "name": "Bash",
                        "input": {"command": "echo edited"},
                    },
                ],
                "stop_reason": "tool_use",
            },
            {
                "content": [
                    {"type": "text", "text": "Edit applied."},
                ],
                "stop_reason": "end_turn",
            },
        ]

    return None


def _default_sequence():
    """Default: ask to run `pwd`, then respond with text after tool result."""
    return [
        # Turn 1: call Bash with pwd
        {
            "content": [
                {"type": "text", "text": "I'll run pwd for you."},
                {
                    "type": "tool_use",
                    "id": f"toolu_{uuid.uuid4().hex[:8]}",
                    "name": "Bash",
                    "input": {"command": "pwd"},
                },
            ],
            "stop_reason": "tool_use",
        },
        # Turn 2: text response after tool result
        {
            "content": [
                {"type": "text", "text": "The current directory is shown above."},
            ],
            "stop_reason": "end_turn",
        },
    ]


def _extract_prompt(body: dict) -> str:
    """Pull a plain-text prompt from an Anthropic Messages API body."""
    messages = body.get("messages", [])
    parts = []
    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, str):
            parts.append(content)
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict):
                    if block.get("type") == "text":
                        parts.append(block.get("text", ""))
                    elif block.get("type") == "tool_result":
                        parts.append(str(block.get("content", "")))
    return " ".join(parts).lower()


def _next_response(body: dict | None = None):
    global _response_index

    logging.info(f"Request Index: {_response_index}")
    logging.info(f"Request Body: {body}")

    # --- keyword routing (takes priority over sequence) ---
    if body:
        prompt = _extract_prompt(body)
        kw = _keyword_response(prompt)
        if kw:
            idx = min(_response_index, len(kw) - 1)
            resp = kw[idx]
            # Only advance the index so turn 2 comes back on the next call
            if _response_index < len(kw) - 1:
                _response_index += 1
            return resp

    # --- fallback to explicit sequence ---
    if not _response_sequence:
        resp_data = _default_sequence()
    else:
        resp_data = _response_sequence

    idx = min(_response_index, len(resp_data) - 1)
    resp = resp_data[idx]
    _response_index += 1

    # Inject unique tool_use IDs so each call is distinct
    for block in resp.get("content", []):
        if block.get("type") == "tool_use":
            block["id"] = f"toolu_{uuid.uuid4().hex[:8]}"

    return resp


@app.post("/v1/messages")
async def anthropic_messages(request: Request):
    _stats["total_requests"] += 1

    try:
        body = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"error": "Invalid JSON"})

    await asyncio.sleep(0.02)
    resp = _next_response(body)
    logging.info(f"Request Response: {resp}")

    return JSONResponse(content={
        "id": f"msg_{uuid.uuid4().hex[:12]}",
        "type": "message",
        "role": "assistant",
        "content": resp["content"],
        "model": body.get("model", "mock-model"),
        "stop_reason": resp.get("stop_reason", "end_turn"),
        "usage": {"input_tokens": 10, "output_tokens": 20},
    })


@app.post("/v1/chat/completions")
async def openai_chat_completions(request: Request):
    _stats["total_requests"] += 1

    try:
        body = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"error": "Invalid JSON"})

    await asyncio.sleep(0.02)
    resp = _next_response(body)
    logging.info(f"Request Response: {resp}")

    # Convert Anthropic format to OpenAI format
    text_parts = []
    tool_calls = []
    for block in resp["content"]:
        if block["type"] == "text":
            text_parts.append(block["text"])
        elif block["type"] == "tool_use":
            tool_calls.append({
                "id": block["id"],
                "type": "function",
                "function": {
                    "name": block["name"],
                    "arguments": __import__("json").dumps(block["input"]),
                },
            })

    choice: dict[str, Any] = {
        "index": 0,
        "message": {
            "role": "assistant",
            "content": "\n".join(text_parts) if text_parts else None,
        },
        "finish_reason": "tool_calls" if tool_calls else "stop",
    }
    if tool_calls:
        choice["message"]["tool_calls"] = tool_calls

    return JSONResponse(content={
        "id": f"chatcmpl-{uuid.uuid4().hex[:12]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": body.get("model", "mock-model"),
        "choices": [choice],
        "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
    })


@app.get("/v1/models")
async def list_models():
    return JSONResponse(content={
        "object": "list",
        "data": [{"id": "mock-model", "object": "model", "created": 0, "owned_by": "mock"}],
    })


@app.get("/reset")
@app.post("/reset")
async def reset():
    global _response_index
    _response_index = 0
    _stats["total_requests"] = 0
    return {"reset": True}


@app.post("/set_sequence")
async def set_sequence(request: Request):
    global _response_sequence, _response_index
    body = await request.json()
    _response_sequence = body.get("sequence", [])
    _response_index = 0
    return {"set": True, "length": len(_response_sequence)}


@app.get("/stats")
async def stats():
    return _stats


def main():
    global _stats
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=9002)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()

    _stats["start_time"] = time.time()
    print(f"Mock LLM Server on {args.host}:{args.port}")
    print(f"  Endpoints: POST /v1/messages, POST /v1/chat/completions")
    print(f"  Keywords: run pwd, run ls, echo, delete, edit")
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
