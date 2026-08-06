"""Production travel agent on Amazon Bedrock AgentCore Runtime.

Same reasoning-cache agent as stack 01's test Lambda, packaged for AgentCore
Runtime (option A: the runtime is VPC-attached, so the hook and tools reach
both Valkey stores directly). All configuration comes from SSM Parameter
Store (/semantic-cache/*) written by stack 01 — no hardcoded endpoints.
"""

import hashlib
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
_response_cache = None

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


def _get_response_cache():
    """Level-1 cache (demo 01): semantic response cache in front of the
    agent loop. A repeated/paraphrased question is answered from Valkey and
    the agent never runs. Scoped separately from the stack-01 test Lambda
    (#agentcore suffix) so the two agents' prompts never fight over entries."""
    global _response_cache
    if _response_cache is None:
        from semantic_cache import SemanticCache, ensure_index

        hook = _get_hook()
        if hook is None:
            return None
        ensure_index(hook.client)
        params = _get_params()
        prompt_hash = hashlib.md5(SYSTEM_PROMPT.encode()).hexdigest()[:8]
        _response_cache = SemanticCache(
            hook.client,
            model_id=params["agent-model-id"] + "#agentcore",
            threshold=0.85,
            ttl=86400,
            prompt_hash=prompt_hash,
        )
    return _response_cache


def _rewrite_cached(question: str, cached_answer: str) -> tuple[str, dict]:
    """Adapt a verified cached answer to this question (language, tone)
    without re-researching — a small LLM call instead of a full agent run."""
    from strands import Agent

    rewriter = Agent(
        model=_agent_model,
        system_prompt=(
            "Rewrite the VERIFIED ANSWER so it directly answers the user's "
            "question. CRITICAL: your entire reply MUST be in the same "
            "language the QUESTION is written in — translate the answer if "
            "needed. Keep every fact exactly as given; add nothing, "
            "contradict nothing. Maximum 3 sentences, plain text."
        ),
    )
    result = rewriter(f"QUESTION: {question}\nVERIFIED ANSWER: {cached_answer}")
    return str(result), dict(result.metrics.accumulated_usage)


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
    response_cache = None
    try:
        hook = _get_hook()
        response_cache = _get_response_cache()
    except Exception:
        logger.exception("cache unavailable, running without it")

    # LEVEL 1 — semantic response cache (demo 01 pattern): repeated or
    # paraphrased question -> serve/rewrite the stored answer, skip the loop.
    if response_cache:
        hit = response_cache.lookup(question)
        if hit:
            answer = hit["answer"]
            source = "cache"
            rewrite_tokens = 0
            needs_rewrite = not hit["prompt_current"] or hit["similarity"] < 0.999
            if needs_rewrite:
                try:
                    answer, rewrite_usage = _rewrite_cached(question, answer)
                    rewrite_tokens = rewrite_usage.get("totalTokens", 0)
                    if not hit["prompt_current"]:
                        response_cache.refresh(hit["entry_id"], answer)
                    source = "cache-rewrite"
                except Exception:
                    logger.exception("rewrite failed, serving verbatim")
            tokens_saved = max(0, hit["tokens_saved"] - rewrite_tokens)
            response = {
                "answer": answer,
                "result": answer,
                "source": source,
                "similarity": hit["similarity"],
                "tokens_saved": tokens_saved,
                "cycles": 0,
                "usage": {"totalTokens": rewrite_tokens},
                "plan_hint_used": False,
                "tool_cache_hits": 0,
                "tool_executions": 0,
                "latency_ms": int((time.time() - started) * 1000),
            }
            logger.info(json.dumps({k: v for k, v in response.items() if k not in ("answer", "result")}))
            return response

    # LEVEL 2 — in-loop reasoning cache (demo 02 pattern): the agent runs,
    # hooks reuse trajectories and tool results.
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

    answer = _clean_answer(str(result))

    # Populate the level-1 cache so the next identical/paraphrased question
    # is served without running the agent at all.
    if response_cache:
        response_cache.store(question, answer, usage)

    response = {
        "answer": answer,
        # "result" is the key the website's publish Lambda renders from.
        "result": answer,
        "source": "agent",
        "tokens_saved": tokens_saved,
        "cycles": result.metrics.cycle_count,
        "usage": usage,
        "plan_hint_used": stats.get("plan_hint", False),
        "tool_cache_hits": stats.get("tool_cache_hits", 0),
        "tool_executions": stats.get("tool_executions", 0),
        "stale_served": stats.get("stale_served", 0),
        "latency_ms": int((time.time() - started) * 1000),
    }
    logger.info(json.dumps({k: v for k, v in response.items() if k not in ("answer", "result")}))
    return response


if __name__ == "__main__":
    app.run()
