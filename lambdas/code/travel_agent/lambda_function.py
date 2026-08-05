"""Travel FAQ agent with a Valkey semantic cache in front of the agent loop.

Flow per request:
    1. Look up the question in the semantic cache (embed + KNN).
    2. Hit -> return the stored answer; zero agent tokens spent.
    3. Miss -> run the Strands agent, store the answer with TTL, return it.

The cache fails open: if Valkey or vector search is unavailable the agent
still answers every request.
"""

import json
import logging
import os
import time

logger = logging.getLogger()
logger.setLevel(logging.INFO)

_client = None
_cache = None
_agent_model = None
_search_available = None

SYSTEM_PROMPT = (
    "You are a travel assistant that answers frequently asked questions about "
    "destinations, visas, documents, best seasons, and local transportation. "
    "Answer concisely and factually. If you do not know, say so."
)


def _get_valkey():
    """Connect and prepare the index. The globals are only assigned after the
    full setup succeeds, so a failed attempt is retried on the next invocation
    instead of leaving a half-initialized client in the warm container."""
    global _client, _search_available
    if _client is None:
        import valkey

        from semantic_cache import ensure_index, supports_ft_search

        client = valkey.Valkey(
            host=os.environ["VALKEY_HOST"],
            port=int(os.environ["VALKEY_PORT"]),
            ssl=True,
            ssl_cert_reqs="required",
            decode_responses=False,  # vectors are FLOAT32 bytes
            socket_timeout=5,
            socket_connect_timeout=5,
        )
        search_available = supports_ft_search(client)
        if search_available:
            ensure_index(client)
        else:
            logger.warning("FT.* not available on this engine; cache disabled")
        _client = client
        _search_available = search_available
    return _client


def _get_cache():
    global _cache
    if _cache is None:
        from semantic_cache import SemanticCache

        client = _get_valkey()
        if not _search_available:
            return None
        _cache = SemanticCache(
            client,
            model_id=os.environ["AGENT_MODEL_ID"],
            threshold=float(os.environ["SIMILARITY_THRESHOLD"]),
            ttl=int(os.environ["CACHE_TTL_SECONDS"]),
        )
    return _cache


def _run_agent(question: str) -> tuple[str, dict]:
    """Run the Strands agent; returns (answer, accumulated token usage)."""
    global _agent_model
    from strands import Agent
    from strands.models import BedrockModel

    if _agent_model is None:
        _agent_model = BedrockModel(model_id=os.environ["AGENT_MODEL_ID"])

    agent = Agent(model=_agent_model, system_prompt=SYSTEM_PROMPT)
    result = agent(question)
    usage = dict(result.metrics.accumulated_usage)
    return str(result), usage


def lambda_handler(event, context):
    question = event.get("question")
    if not question or not isinstance(question, str):
        return {"error": "event must include a 'question' string"}

    started = time.time()

    cache = None
    try:
        cache = _get_cache()
    except Exception:
        logger.exception("cache unavailable, running without it")

    if cache:
        hit = cache.lookup(question)
        if hit:
            elapsed_ms = int((time.time() - started) * 1000)
            logger.info(json.dumps({
                "cache_hit": True,
                "similarity": hit["similarity"],
                "tokens_saved": hit["tokens_saved"],
                "latency_ms": elapsed_ms,
            }))
            return {
                "answer": hit["answer"],
                "source": "cache",
                "similarity": hit["similarity"],
                "tokens_saved": hit["tokens_saved"],
                "latency_ms": elapsed_ms,
            }

    answer, usage = _run_agent(question)
    if cache:
        cache.store(question, answer, usage)

    elapsed_ms = int((time.time() - started) * 1000)
    logger.info(json.dumps({
        "cache_hit": False,
        "usage": usage,
        "latency_ms": elapsed_ms,
    }))
    return {
        "answer": answer,
        "source": "agent",
        "usage": usage,
        "latency_ms": elapsed_ms,
    }
