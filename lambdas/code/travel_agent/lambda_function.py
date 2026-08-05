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
    "You are a travel FAQ assistant (destinations, visas, documents, best "
    "seasons, local transportation). Rules:\n"
    "- Maximum 3 sentences. No filler, no 'generally', no 'it depends' "
    "without immediately saying on what.\n"
    "- Give the concrete fact for the most common case and name it (e.g. "
    "'US citizens: visa-free up to 90 days'). If nationality matters and "
    "was not given, answer for the most likely case and say which case "
    "you answered.\n"
    "- Do not tell the user to 'check with the embassy' unless you truly "
    "do not know — and then say plainly you do not know.\n"
    "- Reply in the user's language."
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
        import hashlib

        from semantic_cache import SemanticCache

        client = _get_valkey()
        if not _search_available:
            return None
        # The cache scope includes the system-prompt hash: answers were
        # generated under these rules, so changing the prompt must stop
        # serving them (old entries just expire via TTL).
        prompt_hash = hashlib.md5(SYSTEM_PROMPT.encode()).hexdigest()[:8]
        _cache = SemanticCache(
            client,
            model_id=f"{os.environ['AGENT_MODEL_ID']}#{prompt_hash}",
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
