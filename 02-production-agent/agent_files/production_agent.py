"""Production travel agent on Amazon Bedrock AgentCore Runtime.

Same reasoning-cache agent as stack 01's test Lambda, packaged for AgentCore
Runtime (option A: the runtime is VPC-attached, so the hook and tools reach
both Valkey stores directly). All configuration comes from SSM Parameter
Store (/semantic-cache/*) written by stack 01 — no hardcoded endpoints.
"""

import json
import logging
import os
import time

import boto3
from bedrock_agentcore import BedrockAgentCoreApp

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = BedrockAgentCoreApp()

PARAM_PREFIX = "/semantic-cache"

_params = None
_hook = None
_agent_model = None

SYSTEM_PROMPT = (
    "You are a travel research assistant. Use the tools to gather real data: "
    "geocode_destination first when you need coordinates, climate_summary "
    "for real historical weather (to judge the best season), "
    "wikipedia_summary for visa policies or country overviews (article "
    "titles like 'Visa policy of Japan'), and search_flights for prices. "
    "If a tool returns 'not found' or an error, do NOT retry it with "
    "variations more than once — answer with what you have and say what "
    "is missing. Maximum 4 sentences, plain text only (no XML tags, no "
    "<thinking>), in the user's language."
)


def _get_params() -> dict:
    """Read the cross-stack contract once per container."""
    global _params
    if _params is None:
        ssm = boto3.client("ssm")
        params = {}
        paginator = ssm.get_paginator("get_parameters_by_path")
        for page in paginator.paginate(Path=PARAM_PREFIX, Recursive=True):
            for p in page["Parameters"]:
                params[p["Name"].removeprefix(f"{PARAM_PREFIX}/")] = p["Value"]
        missing = {"valkey-host", "valkey-port", "tool-cache-host",
                   "tool-cache-port", "agent-model-id"} - params.keys()
        if missing:
            raise RuntimeError(f"SSM contract incomplete, missing: {missing}")
        _params = params
        # tools.py reads these from the environment
        os.environ.setdefault("EMBEDDING_MODEL_ID", _params["embedding-model-id"])
        os.environ.setdefault("DUFFEL_SECRET_ARN", _params["duffel-secret-arn"])
    return _params


def _get_hook():
    global _hook
    if _hook is None:
        import valkey

        from reasoning_cache import ReasoningCacheHook, ensure_trajectory_index
        from semantic_cache import supports_ft_search

        params = _get_params()
        conn_conf = dict(
            ssl=True,
            ssl_cert_reqs="required",
            decode_responses=False,
            socket_timeout=5,
            socket_connect_timeout=5,
        )
        client = valkey.Valkey(
            host=params["valkey-host"], port=int(params["valkey-port"]), **conn_conf
        )
        tool_client = valkey.Valkey(
            host=params["tool-cache-host"],
            port=int(params["tool-cache-port"]),
            **conn_conf,
        )
        if not supports_ft_search(client):
            logger.warning("FT.* unavailable; reasoning cache disabled")
            return None
        ensure_trajectory_index(client)
        _hook = ReasoningCacheHook(
            client,
            tool_client,
            threshold=0.85,
            ttl=86400,
        )
    return _hook


def _clean_answer(text: str) -> str:
    import re

    if "<answer>" in text:
        text = text.split("<answer>", 1)[1].split("</answer>", 1)[0]
    text = re.sub(r"<thinking>.*?(</thinking>|$)", "", text, flags=re.S)
    return text.strip()


@app.entrypoint
def invoke(payload):
    """AgentCore entrypoint. Payload: {"prompt": "..."}"""
    question = (payload.get("prompt") or "").strip()
    if not question:
        return {"error": "payload must include a 'prompt' string"}

    started = time.time()

    from strands import Agent
    from strands.models import BedrockModel

    from tools import ALL_TOOLS

    global _agent_model
    params = _get_params()
    if _agent_model is None:
        _agent_model = BedrockModel(model_id=params["agent-model-id"])

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
    baseline = stats.get("cold_baseline_tokens", 0)
    tokens_saved = max(0, baseline - usage.get("totalTokens", 0)) if baseline else 0

    response = {
        "answer": _clean_answer(str(result)),
        "tokens_saved": tokens_saved,
        "cycles": result.metrics.cycle_count,
        "usage": usage,
        "plan_hint_used": stats.get("plan_hint", False),
        "tool_cache_hits": stats.get("tool_cache_hits", 0),
        "tool_executions": stats.get("tool_executions", 0),
        "stale_served": stats.get("stale_served", 0),
        "latency_ms": int((time.time() - started) * 1000),
    }
    logger.info(json.dumps({k: v for k, v in response.items() if k != "answer"}))
    return response


if __name__ == "__main__":
    app.run()
