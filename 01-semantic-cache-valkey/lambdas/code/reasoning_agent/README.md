# reasoning_agent

Demo 02: in-loop reasoning cache. The Strands agent ALWAYS runs; savings
come from inside the event loop via two hooks backed by Valkey:

- **Plan hint** (`BeforeInvocationEvent.messages`, documented writable): on a
  semantic match with a past question, the cached tool trajectory (with
  resolved arguments) is appended to the user message, so the model issues
  the right tool calls in its first cycle instead of exploring.
- **Tool cache** (`BeforeToolCallEvent.selected_tool`, documented interception
  pattern): an exact repeated (tool, args) call is served by a stub returning
  the cached result: the real tool never executes.

Tools call real public APIs (Open-Meteo geocoding + climate archive,
Wikipedia REST): no hardcoded data, no API keys.

## Trigger

Direct invocation (`aws lambda invoke` or `scripts/test_reasoning_cache.py`).
`{"action": "flush"}` wipes the cache (test helper).

## Input

```json
{"question": "I'm a US citizen planning a trip to Tokyo. Do I need a visa, and when is the best time of year to go?"}
```

## Output

```json
{
  "answer": "...",
  "cycles": 2,
  "usage": {"inputTokens": 2785, "outputTokens": 791, "totalTokens": 3576},
  "plan_hint_used": true,
  "tool_cache_hits": 3,
  "tool_executions": 1,
  "latency_ms": 6749
}
```

## Measured (real deployment, cold vs paraphrased warm)

| Metric | Cold | Warm (plan hint) | Saved |
|---|---|---|---|
| Event-loop cycles | 13 | 2 | 85% |
| Total tokens | 24,561 | 3,576 | 85% |
| Tool executions | 8 | 1 | 88% |

## Environment variables

| Variable | Set in | Purpose |
|----------|--------|---------|
| VALKEY_HOST / VALKEY_PORT | stack wiring | ElastiCache endpoint |
| AGENT_MODEL_ID | stack wiring | Bedrock model for the agent |
| EMBEDDING_MODEL_ID | stack wiring | Titan Text Embeddings V2 (trajectory match) |
| SIMILARITY_THRESHOLD | stack wiring | Min similarity for a plan hint (0.85) |
| CACHE_TTL_SECONDS | stack wiring | TTL for trajectories and tool results |

## Permissions

`bedrock:InvokeModel(WithResponseStream)`. Outbound internet via NAT for the
public-API tools. Valkey access via security group.

## Layers / dependencies

`deps` layer (strands-agents + valkey). `embeddings.py` and
`semantic_cache.py` (FT probe helper) shared with demo 01.
