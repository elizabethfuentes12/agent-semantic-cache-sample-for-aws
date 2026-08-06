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
        # The prompt hash TAGS entries instead of scoping them out: a hit
        # whose answer was generated under an older prompt is still served,
        # but rewritten by the model under the current rules first.
        prompt_hash = hashlib.md5(SYSTEM_PROMPT.encode()).hexdigest()[:8]
        _cache = SemanticCache(
            client,
            model_id=os.environ["AGENT_MODEL_ID"],
            threshold=float(os.environ["SIMILARITY_THRESHOLD"]),
            ttl=int(os.environ["CACHE_TTL_SECONDS"]),
            prompt_hash=prompt_hash,
        )
    return _cache


def _get_model():
    """The Bedrock model, initialized lazily. Shared by the agent and the
    rewriter — the rewriter must NEVER fall back to the SDK default model."""
    global _agent_model
    if _agent_model is None:
        from strands.models import BedrockModel

        _agent_model = BedrockModel(model_id=os.environ["AGENT_MODEL_ID"])
    return _agent_model


def _rewrite_cached(question: str, cached_answer: str) -> tuple[str, dict]:
    """Adapt a cached answer to the current prompt/question (language, tone,
    length) WITHOUT re-researching. Much cheaper than a full agent run: the
    verified answer is the source of truth, the model only reformulates."""
    from strands import Agent

    rewriter = Agent(
        model=_get_model(),
        system_prompt=(
            "Rewrite the VERIFIED ANSWER so it directly answers the user's "
            "question. CRITICAL: your entire reply MUST be in the same "
            "language the QUESTION is written in — translate the answer if "
            "needed. Keep every fact exactly as given; add nothing, "
            "contradict nothing. Maximum 3 sentences, plain text."
        ),
    )
    result = rewriter(
        f"QUESTION: {question}\nVERIFIED ANSWER: {cached_answer}"
    )
    return str(result), dict(result.metrics.accumulated_usage)


def _run_agent(question: str) -> tuple[str, dict]:
    """Run the Strands agent; returns (answer, accumulated token usage)."""
    from strands import Agent

    agent = Agent(model=_get_model(), system_prompt=SYSTEM_PROMPT)
    result = agent(question)
    usage = dict(result.metrics.accumulated_usage)
    return str(result), usage


_ES_MARKERS = {"que", "necesito", "para", "cuando", "cual", "como", "donde",
               "el", "la", "los", "las", "un", "una", "es", "si", "de", "mi"}
_EN_MARKERS = {"the", "what", "when", "which", "how", "where", "do", "does",
               "need", "is", "are", "a", "an", "to", "for", "my", "i"}


def _language_differs(question: str, cached_answer: str) -> bool:
    """Cheap language check: rewrite is only worth its tokens when the
    languages differ (measured: ~200-token rewrite vs ~130-token savings on
    short FAQ answers — uneconomical for same-language paraphrases)."""
    def score(text):
        words = set(text.lower().split())
        return len(words & _ES_MARKERS) - len(words & _EN_MARKERS)

    return (score(question) > 0) != (score(cached_answer) > 0)


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
            answer = hit["answer"]
            source = "cache"
            rewrite_tokens = 0
            # CACHE_MODE=verbatim: serve stored answers as-is (max savings).
            # CACHE_MODE=rewrite: on paraphrased or stale-prompt hits, the
            # model adapts the verified answer to THIS question (language,
            # tone, current prompt rules) without re-researching. Identical
            # questions (sim 1.0) under the current prompt stay verbatim.
            # Economics of the rewrite (measured): ~200 tokens per rewrite vs
            # ~130 saved on short FAQ answers. So rewrite ONLY when it adds
            # value: stale prompt, or the user's language differs from the
            # cached answer. Same-language paraphrases serve verbatim.
            mode = os.environ.get("CACHE_MODE", "verbatim")
            needs_rewrite = not hit["prompt_current"] or (
                mode == "rewrite"
                and hit["similarity"] < 0.999
                and _language_differs(question, hit["answer"])
            )
            if needs_rewrite:
                try:
                    answer, rewrite_usage = _rewrite_cached(question, answer)
                    rewrite_tokens = rewrite_usage.get("totalTokens", 0)
                    if not hit["prompt_current"]:
                        # Self-heal only prompt-stale entries; paraphrase
                        # rewrites are question-specific, don't overwrite.
                        cache.refresh(hit["entry_id"], answer)
                    source = "cache-rewrite"
                except Exception:
                    logger.exception("rewrite failed, serving verbatim")
            tokens_saved = max(0, hit["tokens_saved"] - rewrite_tokens)
            elapsed_ms = int((time.time() - started) * 1000)
            logger.info(json.dumps({
                "cache_hit": True,
                "source": source,
                "similarity": hit["similarity"],
                "tokens_saved": tokens_saved,
                "rewrite_tokens": rewrite_tokens,
                "latency_ms": elapsed_ms,
            }))
            return {
                "answer": answer,
                "source": source,
                "similarity": hit["similarity"],
                "tokens_saved": tokens_saved,
                "usage": {"totalTokens": rewrite_tokens},
                "latency_ms": elapsed_ms,
            }

    answer, usage = _run_agent(question)
    if cache:
        cache.store(question, answer, usage)
        # B1 — if the lookup left a near-miss candidate, verify it against
        # the fresh answer and promote it so this phrasing band hits next time.
        cache.promote_near_miss(question, answer)

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
