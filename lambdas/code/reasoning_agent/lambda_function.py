"""Demo 02 — in-loop reasoning cache: savings INSIDE the agent loop.

Unlike demo 01 (query-level cache, agent skipped entirely), here the agent
ALWAYS runs — the savings come from inside the loop via hooks:

- plan hint (BeforeInvocationEvent): a similar past question's tool
  trajectory steers the model to the right tools on the first cycle,
  cutting deliberation cycles and their tokens.
- tool cache (BeforeToolCallEvent): exact repeated tool calls return the
  cached result without executing the tool.

The response includes cycle and token metrics so cold vs warm runs can be
compared directly.
"""

import json
import logging
import os
import time

logger = logging.getLogger()
logger.setLevel(logging.INFO)

_client = None
_hook = None
_agent_model = None

SYSTEM_PROMPT = (
    "You are a travel research assistant. Use the tools to gather real data: "
    "geocode_destination first when you need coordinates, climate_summary "
    "for real historical weather (to judge the best season), and "
    "wikipedia_summary for visa policies or country overviews. Base your "
    "answer on tool results, not prior knowledge. Be concise and factual."
)


def _get_hook():
    """Connect both stores and build the hook. Globals are assigned only
    after full setup succeeds so a failed attempt retries next invocation.

    Split-store: vectors (trajectories) on the node-based cluster, tool
    results on ElastiCache Serverless.
    """
    global _client, _hook
    if _hook is None:
        import valkey

        from reasoning_cache import ReasoningCacheHook, ensure_trajectory_index
        from semantic_cache import supports_ft_search

        conn_conf = dict(
            ssl=True,
            ssl_cert_reqs="required",
            decode_responses=False,
            socket_timeout=5,
            socket_connect_timeout=5,
        )
        client = valkey.Valkey(
            host=os.environ["VALKEY_HOST"],
            port=int(os.environ["VALKEY_PORT"]),
            **conn_conf,
        )
        tool_client = valkey.Valkey(
            host=os.environ["TOOL_CACHE_HOST"],
            port=int(os.environ["TOOL_CACHE_PORT"]),
            **conn_conf,
        )
        if not supports_ft_search(client):
            logger.warning("FT.* unavailable; reasoning cache disabled")
            return None
        ensure_trajectory_index(client)
        _client = client
        _hook = ReasoningCacheHook(
            client,
            tool_client,
            threshold=float(os.environ["SIMILARITY_THRESHOLD"]),
            ttl=int(os.environ["CACHE_TTL_SECONDS"]),
        )
    return _hook


def _scan_entries(client, pattern: str, limit: int = 200) -> list:
    keys, cursor = [], 0
    while len(keys) < limit:
        cursor, batch = client.scan(cursor=cursor, match=pattern, count=100)
        keys.extend(batch)
        if cursor == 0:
            break
    return keys[:limit]


def _cache_stats(hook) -> dict:
    """Inventory of both stores for the local dashboard (truncated values)."""
    node, serverless = hook.client, hook.tool_client

    responses = []
    for key in _scan_entries(node, "semcache:ans:*"):
        data = node.hgetall(key)
        responses.append({
            "question": data.get(b"question", b"").decode()[:120],
            "answer": data.get(b"answer", b"").decode()[:120],
            "tokens": int(data.get(b"total_tokens", b"0")),
            "ttl": node.ttl(key),
        })

    plans = []
    for key in _scan_entries(node, "trajcache:plan:*"):
        value = node.get(key)
        plans.append({
            "plan": (value.decode()[:160] if value else ""),
            "ttl": node.ttl(key),
        })

    tools = []
    for key in _scan_entries(serverless, "toolcache:*"):
        value = serverless.get(key)
        name = key.decode().split(":")[1] if b":" in key else ""
        tools.append({
            "tool": name,
            "result": (value.decode()[:120] if value else ""),
            "ttl": serverless.ttl(key),
        })

    return {
        "node_based": {
            "description": "Valkey 9.0 node-based (vector search)",
            "responses": responses,
            "trajectories": plans,
        },
        "serverless": {
            "description": "ElastiCache Serverless (exact-match tool cache)",
            "tools": tools,
        },
    }


def lambda_handler(event, context):
    # Test helper: {"action": "flush"} wipes both caches for a clean cold run.
    if event.get("action") == "flush":
        hook = _get_hook()
        if hook:
            hook.client.flushdb()
            hook.tool_client.flushdb()
            from reasoning_cache import ensure_trajectory_index
            ensure_trajectory_index(hook.client)
        return {"flushed": bool(hook)}

    # Dashboard helper: {"action": "cache_stats"} lists what both stores hold.
    if event.get("action") == "cache_stats":
        hook = _get_hook()
        if not hook:
            return {"available": False}
        return {"available": True, "stores": _cache_stats(hook)}

    question = event.get("question")
    if not question or not isinstance(question, str):
        return {"error": "event must include a 'question' string"}

    started = time.time()

    from strands import Agent
    from strands.models import BedrockModel

    from tools import ALL_TOOLS

    global _agent_model
    if _agent_model is None:
        _agent_model = BedrockModel(model_id=os.environ["AGENT_MODEL_ID"])

    hook = None
    try:
        hook = _get_hook()
    except Exception:
        logger.exception("reasoning cache unavailable, running without it")

    agent = Agent(
        model=_agent_model,
        system_prompt=SYSTEM_PROMPT,
        tools=ALL_TOOLS,
        hooks=[hook] if hook else [],
    )
    result = agent(question)

    usage = dict(result.metrics.accumulated_usage)
    stats = dict(hook.stats) if hook else {}
    elapsed_ms = int((time.time() - started) * 1000)

    response = {
        "answer": str(result),
        "cycles": result.metrics.cycle_count,
        "usage": usage,
        "plan_hint_used": stats.get("plan_hint", False),
        "tool_cache_hits": stats.get("tool_cache_hits", 0),
        "tool_executions": stats.get("tool_executions", 0),
        "stale_served": stats.get("stale_served", 0),
        "latency_ms": elapsed_ms,
    }
    logger.info(json.dumps({k: v for k, v in response.items() if k != "answer"}))
    return response
