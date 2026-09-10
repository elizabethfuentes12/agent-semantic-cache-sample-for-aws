# travel_agent

Travel FAQ agent (Strands Agents) with a semantic response cache on
Amazon ElastiCache for Valkey. On a cache hit the agent loop is skipped
entirely: 100% of that invocation's LLM tokens are saved.

## Trigger

Direct invocation (`aws lambda invoke` or the `scripts/test_cache.py` script).

## Input

```json
{"question": "What documents do I need to travel to Japan?"}
```

## Output

Cache miss (agent ran):

```json
{"answer": "...", "source": "agent", "usage": {"inputTokens": 123, "outputTokens": 456, "totalTokens": 579}, "latency_ms": 2100}
```

Cache hit (no LLM call for the answer):

```json
{"answer": "...", "source": "cache", "similarity": 0.93, "tokens_saved": 579, "latency_ms": 180}
```

## Environment variables

| Variable | Set in | Purpose |
|----------|--------|---------|
| VALKEY_HOST / VALKEY_PORT | stack wiring | ElastiCache primary endpoint |
| AGENT_MODEL_ID | stack wiring | Bedrock model for the agent (also scopes cache entries) |
| EMBEDDING_MODEL_ID | stack wiring | Titan Text Embeddings V2 |
| SIMILARITY_THRESHOLD | stack wiring | Min cosine similarity for a hit (default 0.85) |
| CACHE_TTL_SECONDS | stack wiring | Entry TTL (default 86400, plus jitter) |
| CACHE_MODE | stack wiring | `rewrite` (default in the stack) adapts a cached answer to the question's language/tone; `verbatim` serves it as-is |

## Permissions

`bedrock:InvokeModel` / `InvokeModelWithResponseStream` (agent + embeddings).
Network access to the cache comes from the VPC security groups, not IAM.

## Layers / dependencies

`deps` layer: `strands-agents`, `valkey`. Files `semantic_cache.py` and
`embeddings.py` ship with the function code.
