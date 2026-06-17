# Design: Re-enable Streaming Responses to the UI

## Current State

The streaming infrastructure is **already fully wired** end-to-end:

```
Frontend (stream-handler.js)  ←→  SSE  ←→  main.py event_stream()  ←→  sessions.py run_turn()  ←→  llm.py chat_completion()
```

The **only broken link** is `llm.py:64-70` — it hardcodes a non-streaming `client.post()` and yields the entire response as one chunk:

```python
# llm.py:63-70  (current)
async with httpx.AsyncClient(timeout=None) as client:
    response = await client.post(url, json=payload, headers=headers)
    if response.status_code != 200:
        yield {"type": "error", "message": f"LLM Error: {response.status_code}"}
    else:
        yield response.json()   # ← entire response as one yield
```

The `stream` parameter exists in the signature (`stream: bool = False`) but is **ignored**.

`sessions.py:240-250` calls it with `stream=False` and only consumes one yielded chunk:

```python
async for chunk in self._llm.chat_completion(..., stream=False):
    if chunk.get("type") == "error":
        yield chunk
        return
    response = chunk
    break   # ← exits after first (only) chunk
```

## What Already Works (No Changes Needed)

| Layer | File | Status |
|-------|------|--------|
| SSE transport | `main.py:304-458` | `StreamingResponse` with `text/event-stream` ✅ |
| Event serialization | `main.py:461-462` | `_sse()` helper ✅ |
| DB persistence | `main.py:377-440` | Writes `text`, `tool_use`, `tool_result` to DB ✅ |
| Event dispatch | `sessions.py:232-388` | `run_turn()` yields correct event types ✅ |
| Frontend SSE reader | `stream-handler.js:71-93` | Parses `data:` lines, dispatches to handler ✅ |
| Frontend text streaming | `stream-handler.js:125-157` | Accumulates text deltas, renders markdown ✅ |
| Frontend tool blocks | `stream-handler.js:164-203` | Renders tool_use, tool_result, tool_error ✅ |
| Frontend token stats | `stream-handler.js:250-276` | `finalizeAssistantMessage` shows tokens from `result.usage` ✅ |
| Permission flow | `sessions.py:288-374` | Yields `permission_request`, blocks on future ✅ |

## What Needs to Change

### Change 1: `llm.py` — Enable streaming in `chat_completion()`

**What:** When `stream=True`, use `httpx.AsyncClient.stream()` instead of `.post()`, parse SSE lines, reassemble content blocks (exactly like the POC), and yield semantic events.

**How:** Port the reassembly logic from the POC (`parse_sse_events` + `reassemble_tool_calls`) into the async context. Instead of returning a single reassembled dict, yield each semantic event as it completes:

```python
async def chat_completion(self, messages, system=None, tools=None, stream=False):
    # ... build payload ...
    payload["stream"] = stream   # ← add to payload

    async with httpx.AsyncClient(timeout=None) as client:
        if not stream:
            # existing non-streaming path (unchanged)
            response = await client.post(url, json=payload, headers=headers)
            ...
        else:
            # NEW: streaming path
            async with client.stream("POST", url, json=payload, headers=headers) as resp:
                async for sse_event in self._parse_sse_stream(resp):
                    yield sse_event
```

**New private method `_parse_sse_stream(resp)`:**

- Reads lines from `resp.aiter_lines()`
- Parses `event:` / `data:` / blank-line SSE framing
- Tracks content blocks by index (same as POC)
- On `content_block_start` with `type: "text"` → no yield yet (accumulate)
- On `content_block_delta` with `type: "text_delta"` → yield `{"type": "text", "data": delta_text}` **immediately** (this is what gives the streaming feel)
- On `content_block_start` with `type: "tool_use"` → start accumulating `input_json_delta`
- On `content_block_stop` for a `tool_use` block → yield `{"type": "tool_use", "id": ..., "name": ..., "input": parsed_json}`
- On `message_start` → extract `usage` (input_tokens), store for later
- On `message_delta` → extract `stop_reason` and final `output_tokens`
- On `message_stop` → yield `{"type": "result", "usage": {input_tokens, output_tokens}, "stop_reason": ...}`

**Key design detail:** The text deltas must be yielded **inline during streaming**, not buffered until `content_block_stop`. This is the difference between "instant feel" and "batch feel". The POC buffers everything; for the UI you want to yield each `text_delta` as it arrives.

### Change 2: `sessions.py` — Remove `stream=False` hardcode, consume streaming events

**What:** Change the LLM call in `run_turn()` to use `stream=True` and handle the new event types.

**Lines 240-270 — the LLM call and parsing block:**

```python
# BEFORE (current):
response = None
async for chunk in self._llm.chat_completion(
    messages=self.messages,
    system=self._system_prompt_content,
    tools=get_tool_definitions(format=tool_format),
    stream=False   # ← hardcoded off
):
    if chunk.get("type") == "error":
        yield chunk
        return
    response = chunk
    break

# Parse Anthropic Messages API response
content_blocks = response.get("content", [])
assistant_content = ""
tool_uses = []

for block in content_blocks:
    block_type = block.get("type")
    if block_type == "text":
        text = block.get("text", "")
        assistant_content += text
        yield {"type": "text", "data": text}     # ← batch text
    elif block_type == "tool_use":
        tool_uses.append(block)
```

```python
# AFTER:
tool_uses = []
assistant_content = ""
usage_info = {}

async for event in self._llm.chat_completion(
    messages=self.messages,
    system=self._system_prompt_content,
    tools=get_tool_definitions(format=tool_format),
    stream=True,    # ← enabled
):
    if event.get("type") == "error":
        yield event
        return

    etype = event.get("type")

    if etype == "text":
        # Streaming text — forward directly to UI
        yield {"type": "text", "data": event["data"]}
        assistant_content += event["data"]

    elif etype == "tool_use":
        # Complete tool_use block — forward to UI
        tool_uses.append(event)

    elif etype == "result":
        # Final usage/stop_reason
        usage_info = event.get("usage", {})
```

**Lines 279-283 — adding assistant message to history:** No change needed. `content_blocks` construction changes slightly: instead of parsing from a single response dict, build it from the accumulated `assistant_content` and `tool_uses`. The Anthropic format expects:

```python
# Build content blocks for message history
content_blocks = []
if assistant_content:
    content_blocks.append({"type": "text", "text": assistant_content})
for tu in tool_uses:
    content_blocks.append(tu)  # already in Anthropic format from LLM

self.messages.append({"role": "assistant", "content": content_blocks})
```

### Change 3: `sessions.py` — Pass usage into `result` event

**Line 388:**

```python
# BEFORE:
yield {"type": "result", "num_turns": turn_count}

# AFTER:
yield {"type": "result", "num_turns": turn_count, "usage": usage_info}
```

This feeds the token counts into `finalizeAssistantMessage` in the frontend, which already reads `result.usage.input_tokens` and `result.usage.output_tokens`.

### Change 4: `llm.py` — Add `timeout` to streaming client

The streaming path should use a generous timeout (e.g., 300s) since LLM responses can take time, but not `timeout=None` which could hang forever:

```python
async with httpx.AsyncClient(timeout=httpx.Timeout(300.0)) as client:
```

## What Does NOT Change

- **`main.py`** — The `event_stream()` generator already handles all event types and persists to DB. No changes.
- **`tools.py`** — Tool execution is independent of streaming. No changes.
- **`models.py`** — No schema changes needed.
- **Frontend** — All event types (`text`, `tool_use`, `tool_result`, `tool_error`, `result`) are already handled. The text accumulation in `stream-handler.js:134-156` already works with incremental deltas.

## SSE Event Flow After Changes

```
User sends message
  → POST /v1/sessions/stream
  → main.py yields "session" event
  → sessions.py run_turn() loops:
    → llm.py yields "text" events (streamed incrementally)
      → main.py forwards each as SSE
      → frontend appends to .msg-content in real-time
    → llm.py yields "tool_use" event (complete block)
      → main.py forwards → frontend shows tool card
      → sessions.py checks permission → yields "permission_request" if needed
      → sessions.py executes tool → yields "tool_result" or "tool_error"
      → main.py persists to DB
    → loop continues with tool results in context
  → llm.py yields "result" with usage
    → main.py forwards → frontend shows token stats
  → main.py yields "done"
```

## Risk Areas

1. **Token estimation in UI**: The `result.usage` must include `input_tokens` and `output_tokens`. In streaming mode, `input_tokens` comes from `message_start` and `output_tokens` from `message_delta`. If the router doesn't send these, the stats will show `–`. Verify the router sends usage in streaming mode.

2. **Tool use reassembly correctness**: If the LLM returns malformed JSON in `input_json_delta`, the `json.loads()` will fail. The POC handles this with a `_raw` fallback — include the same in `_parse_sse_stream`.

3. **Concurrent permission + streaming**: The permission flow in `run_turn()` blocks on `pending.future` while streaming is paused. This already works today and streaming doesn't change it — the `async for` loop in `run_turn()` just stops yielding until the permission resolves.

4. **Interrupt/abort**: `sessions.py` checks `self._interrupt_flag` between turns. During streaming, if the user aborts, the `AbortController` in the frontend closes the fetch, but the server-side `run_turn()` continues until the next `while` loop iteration check. This is existing behavior and unchanged.

## Summary

| File | Lines changed | Nature of change |
|------|--------------|------------------|
| `llm.py` | ~40 lines new/modified | Add streaming path + SSE parser |
| `sessions.py` | ~25 lines modified | `stream=True`, consume events inline, pass usage to result |
| `main.py` | 0 | None |
| `tools.py` | 0 | None |
| `models.py` | 0 | None |
| Frontend | 0 | None |

The changes are concentrated in 2 files. The frontend and main.py infrastructure already support streaming — you're just reconnecting the pipe.
