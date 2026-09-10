# Selective Stream Yield Strategy for Strands Agents

## Problem

The Strands SDK `agent.stream_async()` yields **every internal event** as raw dicts: model metadata, system prompts, event loop traces, tool config, partial content deltas, and more. Forwarding all of these to the client floods the UI with hundreds of noisy, unstructured events that carry no actionable information.

## Solution

Replace the pass-through loop with a **stateful filter** that classifies each chunk by its keys and yields only four structured event types to the client.

## Yielded Event Types

| Type | Shape | When |
|------|-------|------|
| `tool_call` | `{"type": "tool_call", "tool": name, "toolUseId": id, "input": {...}}` | Assistant invokes a tool |
| `tool_result` | `{"type": "tool_result", "tool": name, "toolUseId": id, "result": preview}` | Tool returns a result (truncated to 500 chars) |
| `message` | `{"type": "message", "content": text}` | Assistant finishes a reasoning cycle with text output |
| `complete` | `{"type": "complete", "answer": text}` | Stream ends — carries the final answer |

## Strands SDK Event Structure

Understanding the chunk keys is critical. The SDK emits these event shapes:

| Chunk Key | Value Type | Meaning |
|-----------|-----------|---------|
| `"data"` | `str` | Streaming text token (partial assistant output) |
| `"current_tool_use"` | `dict` with `name`, `toolUseId` | Tool identity announcement (before the tool runs) |
| `"start_event_loop"` | `True` | Cycle boundary — a new agent reasoning loop begins |
| `"message"` with `role: "assistant"` | `dict` | Complete assistant turn — contains `toolUse` blocks and/or text |
| `"message"` with `role: "user"` | `dict` | Complete user turn — contains `toolResult` blocks |
| Everything else | varies | Metadata, traces, config — **noise to skip** |

## Core Logic

### State Variables

```python
cycle_text_parts = []    # accumulates "data" string tokens within a cycle
tool_name_map = {}       # maps toolUseId → tool name for resolution
last_text = ""           # tracks the last flushed text (becomes the final answer)
had_dict_chunk = False   # guards the "complete" event — only emit if we processed something
```

### Event Processing Flow

```
stream_async chunk
    │
    ├─ not a dict? → skip
    │
    ├─ has "data" key (str)? → append to cycle_text_parts
    │
    ├─ has "current_tool_use"? → register toolUseId → name in tool_name_map
    │
    ├─ has "start_event_loop": True? → clear cycle_text_parts (new cycle)
    │
    ├─ has "message" with role "assistant"?
    │     ├─ for each toolUse block → yield tool_call + register in tool_name_map
    │     ├─ flush cycle_text_parts → yield message (if non-empty)
    │     └─ clear cycle_text_parts
    │
    ├─ has "message" with role "user"?
    │     └─ for each toolResult block → resolve name from tool_name_map → yield tool_result
    │
    └─ anything else → skip silently

after loop:
    └─ yield {"type": "complete", "answer": last_text}
```

Key insight: **the assistant message event is the flush trigger**, not the cycle boundary. The `start_event_loop` event clears the buffer (new cycle starts), and the assistant message flushes it (cycle ends with output).

### Why This Order Matters

A single chunk can have multiple keys simultaneously (e.g., `"data"` + `"message"`). The code uses `if` (not `elif`) so all relevant keys in a chunk are processed. The processing order ensures:

1. `"data"` is accumulated **before** the assistant message check flushes it
2. `"current_tool_use"` registers the name **before** the assistant message extracts `toolUse` blocks
3. `"start_event_loop"` clears the buffer **before** new data arrives

## Code Snippet

Drop this into any async generator that wraps `agent.stream_async()` or `AgentService.invoke_async()`:

```python
# State variables for selective stream yield
cycle_text_parts = []
tool_name_map = {}       # toolUseId → tool name
last_text = ""
had_dict_chunk = False

async for chunk in agent_stream:
    if not isinstance(chunk, dict):
        continue

    had_dict_chunk = True

    # --- Accumulate streaming text tokens ---
    if "data" in chunk:
        cycle_text_parts.append(chunk["data"])

    # --- Track tool names from current_tool_use events ---
    if "current_tool_use" in chunk:
        tool_use = chunk["current_tool_use"]
        if isinstance(tool_use, dict):
            t_name = tool_use.get("name")
            t_id = tool_use.get("toolUseId") or tool_use.get("id", "")
            if t_name and t_id:
                tool_name_map[t_id] = t_name

    # --- Cycle boundary: clear text buffer (new cycle starts) ---
    if chunk.get("start_event_loop", False):
        cycle_text_parts.clear()

    # --- Assistant message: extract toolUse blocks + flush text ---
    if "message" in chunk and chunk["message"].get("role") == "assistant":
        for block in chunk["message"].get("content", []):
            if isinstance(block, dict) and "toolUse" in block:
                tu = block["toolUse"]
                t_name = tu.get("name", "unknown")
                t_id = tu.get("toolUseId", "")
                t_input = tu.get("input", {})
                if t_id:
                    tool_name_map[t_id] = t_name
                yield {
                    "type": "tool_call",
                    "tool": t_name,
                    "toolUseId": t_id,
                    "input": t_input,
                }

        # Flush accumulated text as a message event
        cycle_text = "".join(cycle_text_parts)
        if cycle_text.strip():
            last_text = cycle_text
            yield {"type": "message", "content": cycle_text}
        cycle_text_parts.clear()

    # --- User message: extract toolResult blocks ---
    if "message" in chunk and chunk["message"].get("role") == "user":
        for block in chunk["message"].get("content", []):
            if isinstance(block, dict) and "toolResult" in block:
                tr = block["toolResult"]
                t_id = tr.get("toolUseId", "")
                resolved_name = tool_name_map.get(t_id, t_id)
                result_content = tr.get("content", [])
                result_parts = []
                for c in (result_content if isinstance(result_content, list) else [result_content]):
                    if isinstance(c, dict) and "text" in c:
                        result_parts.append(c["text"])
                    elif isinstance(c, str):
                        result_parts.append(c)
                result_text = "\n".join(result_parts) if result_parts else str(result_content)
                preview = result_text[:500] + "…" if len(result_text) > 500 else result_text
                yield {
                    "type": "tool_result",
                    "tool": resolved_name,
                    "toolUseId": t_id,
                    "result": preview,
                }

# --- After the loop: yield final complete event ---
if had_dict_chunk:
    yield {"type": "complete", "answer": last_text}
```

## Adapting for Non-Yield Contexts (e.g., AppSync publish)

If you're publishing to AppSync instead of yielding, replace each `yield {...}` with:

```python
appsync.publish_event(channel, [json.dumps({...})])
```

And replace the final `yield complete` with:

```python
appsync.publish_event(channel, [json.dumps({"type": "complete", "answer": last_text})])
```

The state machine and event classification logic remain identical.

## Example Stream Timeline

```
chunk: {"model": "claude-sonnet-4-5", ...}           → skipped (metadata)
chunk: {"data": "Let me search "}                     → accumulated
chunk: {"data": "for that."}                          → accumulated
chunk: {"current_tool_use": {"name": "web_search", "toolUseId": "tu_1"}}  → registered
chunk: {"message": {"role": "assistant", "content": [{"toolUse": {...}}]}}
    → yield: {"type": "tool_call", "tool": "web_search", ...}
    → yield: {"type": "message", "content": "Let me search for that."}
    → clear buffer
chunk: {"message": {"role": "user", "content": [{"toolResult": {...}}]}}
    → yield: {"type": "tool_result", "tool": "web_search", ...}
chunk: {"start_event_loop": true}                     → clear buffer (new cycle)
chunk: {"data": "Based on the results, "}             → accumulated
chunk: {"data": "here is the answer."}                → accumulated
chunk: {"message": {"role": "assistant", "content": [{"text": "..."}]}}
    → yield: {"type": "message", "content": "Based on the results, here is the answer."}
    → clear buffer
--- stream ends ---
    → yield: {"type": "complete", "answer": "Based on the results, here is the answer."}
```
