"""CachedTravelAgent - one Strands agent with the three cache hooks, on Valkey.

Same design as the DynamoDB track and the notebook: a single ``Agent`` with
ResponseCache, ToolResultCache, and ReasoningCache attached. No wrapper logic
around the agent; the caching happens inside the loop through Strands hook
events. Only the storage backend changes (local Valkey instead of DynamoDB), so
the notebook and Streamlit app are interchangeable across tracks.

    agent = CachedTravelAgent(ValkeyCacheConfig())
    r = agent.ask("Best time to visit Japan and do I need a visa?")
    print(r["source"], r["tokens_saved"], r["similarity"])
"""

import logging
import re
import time

from cache_lib.caches import ReasoningCache, ResponseCache, ToolResultCache
from cache_lib.config import ValkeyCacheConfig
from cache_lib.rewrite import rewrite_to_question_language
from cache_lib.tools import ALL_TOOLS
from cache_lib.valkey_setup import ensure_indexes, get_client

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You are a travel research specialist. Ground every claim in data you "
    "retrieve with the available tools rather than prior knowledge, and resolve "
    "each tool's inputs from earlier results before calling it. If a tool returns "
    "nothing useful, do not retry it with small variations; answer with what you "
    "have and state what is missing. Be direct: at most 4 sentences, plain text "
    "only (no XML tags, no <thinking>). Always reply in the same language the "
    "user's question is written in."
)


# A hit at or above this cosine similarity is treated as the same question in
# the same language: served verbatim (0 tokens), no cross-language rewrite call.
VERBATIM_SIMILARITY = 0.985

def _clean_answer(text: str) -> str:
    if "<answer>" in text:
        text = text.split("<answer>", 1)[1].split("</answer>", 1)[0]
    text = re.sub(r"<thinking>.*?(</thinking>|$)", "", text, flags=re.S)
    return text.strip()


class CachedTravelAgent:
    """A Strands travel agent with the response, tool-result, and reasoning
    caches attached as hooks on one agent, on one local Valkey.

    Args:
        cfg: The ValkeyCacheConfig describing host/port, models, thresholds.
        cache_mode: "both" (default, all three), "response-cache" (response only),
            or "reasoning-cache" (tool-result + reasoning only).
        ensure_index: if True (default), create the FT.* indexes on init.
    """

    def __init__(self, cfg: ValkeyCacheConfig, cache_mode: str = "both",
                 ensure_index: bool = True):
        self._cfg = cfg
        self._cache_mode = cache_mode
        self._client = get_client(cfg)
        self._model = None
        if ensure_index:
            try:
                ensure_indexes(self._client)
            except Exception:
                logger.exception("could not ensure indexes; caching may be degraded")
        self._response = ResponseCache(self._client, cfg)
        self._tools = ToolResultCache(self._client, cfg)
        self._reasoning = ReasoningCache(self._client, cfg)

    def _get_model(self):
        if self._model is None:
            from strands.models import BedrockModel
            self._model = BedrockModel(
                model_id=self._cfg.agent_model_id, region_name=self._cfg.region,
            )
        return self._model

    def _hooks(self) -> list:
        hooks = []
        if self._cache_mode in ("both", "response-cache"):
            hooks.append(self._response)     # first: can cancel before the rest work
        if self._cache_mode in ("both", "reasoning-cache"):
            hooks.extend([self._tools, self._reasoning])
        return hooks

    def ask(self, question: str) -> dict:
        """Answer a question through one agent with the cache hooks attached.

        Returns: answer, source ("cache" | "cache-rewrite" | "agent"), similarity,
        tokens_saved, cycles, usage, plan_hint_used, tool_cache_hits,
        tool_executions, flow.
        """
        question = (question or "").strip()
        if not question:
            return {"error": "question is empty", "answer": "", "source": "error"}

        started = time.time()
        from strands import Agent
        agent = Agent(
            model=self._get_model(),
            system_prompt=SYSTEM_PROMPT,
            tools=ALL_TOOLS,
            hooks=self._hooks(),
        )
        result = agent(question)

        usage = dict(result.metrics.accumulated_usage)
        hit = self._response.hit
        if hit:
            answer = _clean_answer(str(result))
            source = "cache"
            rewrite_tokens = 0
            flow = [{"step": "response_hit", "kind": "hit",
                     "detail": f"similarity {hit['similarity']} "
                               "- model skipped via BeforeInvocationEvent.cancel"}]
            # Cross-language rewrite (option 2): the multilingual embedding can
            # match a Spanish question to an English answer. One cheap Nova Lite
            # call expresses the verified answer in the question's language. On a
            # same-language hit the model reports so and the answer is unchanged.
            # A near-identical hit (very high similarity) is almost certainly the
            # same question in the same language, so it is served verbatim at 0
            # tokens without a rewrite call.
            if self._cfg.rewrite_on_hit and hit["similarity"] < VERBATIM_SIMILARITY:
                rw = rewrite_to_question_language(
                    question, answer,
                    self._cfg.rewrite_model_id, self._cfg.region)
                answer = rw["answer"]
                rewrite_tokens = rw["tokens"]
                if rw["rewritten"]:
                    source = "cache-rewrite"
                    flow.append({"step": "cross_language_rewrite", "kind": "hit",
                                 "detail": "answer translated to the question's "
                                           f"language ({rewrite_tokens} tokens, "
                                           "cheap model)"})
            return {
                "answer": answer,
                "source": source,
                "similarity": hit["similarity"],
                "tokens_saved": hit["tokens_saved"],
                "cycles": 0,
                "usage": {"totalTokens": rewrite_tokens},
                "rewrite_tokens": rewrite_tokens,
                "plan_hint_used": False,
                "tool_cache_hits": 0,
                "tool_executions": 0,
                "flow": flow,
                "latency_ms": int((time.time() - started) * 1000),
            }

        flow = [{"step": "response_miss", "kind": "miss",
                 "detail": "no similar answer - the agent ran"}]
        if self._reasoning.plan_used:
            flow.append({"step": "plan_hint_injected", "kind": "hit",
                         "detail": "a cached tool plan guided the agent"})
        flow.append({"step": "tool_cache", "kind": "hit" if self._tools.hits else "miss",
                     "detail": f"{self._tools.hits} tool-cache hit(s), "
                               f"{self._tools.executions} real API call(s)"})
        return {
            "answer": _clean_answer(str(result)),
            "source": "agent",
            "similarity": None,
            "tokens_saved": 0,
            "cycles": result.metrics.cycle_count,
            "usage": usage,
            "plan_hint_used": self._reasoning.plan_used,
            "tool_cache_hits": self._tools.hits,
            "tool_executions": self._tools.executions,
            "flow": flow,
            "latency_ms": int((time.time() - started) * 1000),
        }
