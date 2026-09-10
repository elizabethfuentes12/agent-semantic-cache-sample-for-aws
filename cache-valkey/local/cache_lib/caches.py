"""The three cache layers, each a Strands hook, on one local Valkey.

This is the packaged version of what the notebook builds inline, and it mirrors
the DynamoDB track 1:1 on purpose: same three independent HookProviders, same
responsibilities, same shared trajectory through ``invocation_state``. Only the
storage calls change (Valkey ``FT.SEARCH`` + ``get/set`` instead of DynamoDB
vector search). "If there are three, there are three" - the lesson is that the
cache pattern is backend-independent; swapping the store does not reshape it.

- ResponseCache: BeforeInvocationEvent looks up the question; on a hit it sets
  ``event.cancel`` to the stored answer so the model never runs (0 tokens).
  AfterInvocationEvent stores a freshly generated answer.
- ToolResultCache: BeforeToolCallEvent serves an exact repeated (tool, args)
  result via a stub; AfterToolCallEvent stores fresh results (negative-caching
  the not-useful ones), keeps a longer-lived stale copy, and records the call
  in the shared trajectory.
- ReasoningCache: BeforeInvocationEvent injects a matching past tool plan;
  AfterInvocationEvent stores this question's trajectory as its plan.

Difference from the production Valkey track: that one uses a SPLIT store -
node-based Valkey for vectors + ElastiCache Serverless for the tool cache. Here
a single local Valkey handles both. One client, no split.

Everything fails open: any Valkey or Bedrock error is logged and treated as a
miss, so the agent always keeps working.
"""

import hashlib
import json
import logging
import random
import re
import time
import uuid

from strands import tool
from strands.hooks import (
    AfterInvocationEvent,
    AfterToolCallEvent,
    BeforeInvocationEvent,
    BeforeToolCallEvent,
    HookProvider,
    HookRegistry,
)

from cache_lib.config import (
    DEFAULT_TOOL_TTL,
    NEGATIVE_TTL_SECONDS,
    PREFIX_SEM_ANS,
    PREFIX_SEM_VEC,
    PREFIX_TOOL,
    PREFIX_TOOL_STALE,
    PREFIX_TRAJ_PLAN,
    PREFIX_TRAJ_VEC,
    SEMCACHE_INDEX,
    TOOL_TTL_SECONDS,
    TRAJ_INDEX,
    ValkeyCacheConfig,
)
from cache_lib.embeddings import embedding_to_bytes, generate_embedding

logger = logging.getLogger(__name__)

STALE_RETENTION_FACTOR = 4

# Results that succeeded technically but found nothing useful. These are
# negative-cached briefly and kept out of the reasoning trajectory. The Duffel
# "no API key" message is included so a missing key is not cached as a success.
_NOT_USEFUL = (
    "no location found", "no wikipedia article found", "no summary available",
    "no flight offers found", "no climate data", "no data available",
    "no duffel api key",
)


# ---------------------------------------------------------------------------
# Shared low-level utilities (not cache logic; used across the hooks)
# ---------------------------------------------------------------------------

def _escape_tag(value: str) -> str:
    return value.replace("-", "\\-").replace(".", "\\.").replace(":", "\\:")


def _decode(value):
    return value.decode() if isinstance(value, bytes) else value


# ---------------------------------------------------------------------------
# ResponseCache - level 1
# ---------------------------------------------------------------------------

class ResponseCache(HookProvider):
    """Question -> answer. On a hit, cancels the invocation (0 tokens)."""

    def __init__(self, client, cfg: ValkeyCacheConfig):
        self._c = client
        self._cfg = cfg
        self.question: str | None = None
        self.hit: dict | None = None

    def _embed(self, text: str) -> bytes:
        return embedding_to_bytes(
            generate_embedding(text, self._cfg.embedding_model_id, self._cfg.region)
        )

    @staticmethod
    def _question_of(event) -> str | None:
        if not event.messages:
            return None
        texts = [b["text"] for b in event.messages[-1].get("content", []) if "text" in b]
        return " ".join(texts) if texts else None

    @staticmethod
    def _critical_params(text: str) -> set:
        """Dates/numbers that must match exactly; embeddings cannot separate them."""
        params = set(re.findall(r"\d{4}-\d{2}-\d{2}", text))
        params.update(re.findall(r"\b\d{1,2}/\d{1,2}(?:/\d{2,4})?\b", text))
        params.update(re.findall(r"\b\d+\b", text))
        return params

    def register_hooks(self, registry: HookRegistry) -> None:
        registry.add_callback(BeforeInvocationEvent, self.check)
        registry.add_callback(AfterInvocationEvent, self.store)

    def lookup(self, question: str) -> dict | None:
        try:
            result = self._c.execute_command(
                "FT.SEARCH", SEMCACHE_INDEX,
                "*=>[KNN 1 @embedding $vec AS score]",
                "PARAMS", "2", "vec", self._embed(question),
                "RETURN", "2", "entry_id", "score",
                "DIALECT", "2",
            )
        except Exception:
            logger.exception("response cache lookup failed, treating as miss")
            return None
        if not result or int(result[0]) == 0:
            return None
        fields = result[2]
        doc = {_decode(fields[i]): _decode(fields[i + 1]) for i in range(0, len(fields), 2)}
        similarity = 1.0 - (float(doc["score"]) / 2.0)
        if similarity < self._cfg.similarity_threshold:
            return None
        payload = self._c.hgetall(f"{PREFIX_SEM_ANS}{doc['entry_id']}")
        if not payload:
            return None
        cached_question = _decode(payload.get(b"question", b""))
        # dates/numbers must match exactly even on a high-similarity hit
        if self._critical_params(question) != self._critical_params(cached_question):
            return None
        return {
            "answer": _decode(payload.get(b"answer", b"")),
            "similarity": round(similarity, 4),
            "tokens_saved": int(payload.get(b"tokens", b"0")),
        }

    def check(self, event: BeforeInvocationEvent) -> None:
        self.question = self._question_of(event)
        self.hit = None
        if not self.question:
            return
        try:
            hit = self.lookup(self.question)
        except Exception:
            logger.exception("response cache check failed, running the agent")
            return
        if hit:
            self.hit = hit
            event.cancel = hit["answer"]     # model never runs; this is the answer

    def store(self, event: AfterInvocationEvent) -> None:
        if self.hit or not self.question or event.result is None:
            return
        try:
            tokens = int(event.result.metrics.accumulated_usage.get("totalTokens", 0))
            ttl = self._cfg.response_ttl_seconds
            ttl += random.randint(0, max(1, ttl // 10))  # jitter avoids synced expiry
            entry_id = str(uuid.uuid4())
            self._c.hset(f"{PREFIX_SEM_VEC}{entry_id}", mapping={
                "embedding": self._embed(self.question),
                "entry_id": entry_id,
            })
            self._c.hset(f"{PREFIX_SEM_ANS}{entry_id}", mapping={
                "question": self.question,
                "answer": str(event.result),
                "tokens": str(tokens),
            })
            self._c.expire(f"{PREFIX_SEM_VEC}{entry_id}", ttl)
            self._c.expire(f"{PREFIX_SEM_ANS}{entry_id}", ttl)
        except Exception:
            logger.exception("response cache store failed")


# ---------------------------------------------------------------------------
# ToolResultCache - the tool-result cache
# ---------------------------------------------------------------------------

class ToolResultCache(HookProvider):
    """Exact (tool, args) -> result. Serves via a stub; negative-caches misses."""

    def __init__(self, client, cfg: ValkeyCacheConfig):
        self._c = client
        self._cfg = cfg
        self.hits = 0
        self.executions = 0
        self._served: set = set()

    def register_hooks(self, registry: HookRegistry) -> None:
        registry.add_callback(BeforeInvocationEvent, self.reset)
        registry.add_callback(BeforeToolCallEvent, self.serve)
        registry.add_callback(AfterToolCallEvent, self.store)

    @staticmethod
    def _tool_key(tool_name: str, tool_input: dict, prefix: str = PREFIX_TOOL) -> str:
        normalized = {
            k: (" ".join(str(v).strip().lower().split()) if isinstance(v, str) else v)
            for k, v in tool_input.items()
        }
        canonical = json.dumps(normalized, sort_keys=True, default=str)
        digest = hashlib.md5(
            f"{tool_name}:{canonical}".encode(), usedforsecurity=False
        ).hexdigest()
        return f"{prefix}{tool_name}:{digest}"

    @staticmethod
    def _tool_ttl(tool_name: str) -> int:
        return TOOL_TTL_SECONDS.get(tool_name, DEFAULT_TOOL_TTL)

    @staticmethod
    def _is_useful(text: str) -> bool:
        low = text.strip().lower()
        return bool(text) and not any(m in low[:120] for m in _NOT_USEFUL)

    @staticmethod
    def _stub_tool(cached_text: str):
        @tool
        def cached_lookup(
            place: str = "", latitude: float = 0.0, longitude: float = 0.0,
            topic: str = "", origin: str = "", destination: str = "",
            departure_date: str = "", cabin_class: str = "",
        ) -> str:
            """Return the cached result of an identical earlier tool call."""
            return cached_text

        return cached_lookup

    def reset(self, event: BeforeInvocationEvent) -> None:
        self.hits = 0
        self.executions = 0
        self._served = set()

    def serve(self, event: BeforeToolCallEvent) -> None:
        try:
            key = self._tool_key(event.tool_use["name"], event.tool_use["input"])
            cached = self._c.get(key)
            if cached is not None:
                event.selected_tool = self._stub_tool(_decode(cached))
                self.hits += 1
                self._served.add(event.tool_use.get("toolUseId"))
            else:
                self.executions += 1
        except Exception:
            logger.exception("tool cache lookup failed, running the real tool")

    def store(self, event: AfterToolCallEvent) -> None:
        try:
            name, args = event.tool_use["name"], event.tool_use["input"]
            if event.tool_use.get("toolUseId") in self._served:
                # record it in the trajectory only if the served result was useful,
                # so a negative-cached dead end never becomes a step in the plan
                served_texts = [b["text"] for b in event.result.get("content", [])
                                if "text" in b] if isinstance(event.result, dict) else []
                if served_texts and self._is_useful(" ".join(served_texts)):
                    event.invocation_state.setdefault("trajectory", []).append(
                        f"{name}({json.dumps(args, sort_keys=True)})")
                return
            if not isinstance(event.result, dict) or event.result.get("status") == "error":
                self._serve_stale(event, name, args)
                return
            texts = [b["text"] for b in event.result.get("content", []) if "text" in b]
            result_text = " ".join(texts)
            if not result_text:
                return
            key = self._tool_key(name, args)
            if not self._is_useful(result_text):
                self._c.set(key, result_text, ex=NEGATIVE_TTL_SECONDS)
                return
            ttl = self._tool_ttl(name)
            self._c.set(key, result_text, ex=ttl)
            self._c.set(self._tool_key(name, args, prefix=PREFIX_TOOL_STALE),
                        result_text, ex=ttl * STALE_RETENTION_FACTOR)
            event.invocation_state.setdefault("trajectory", []).append(
                f"{name}({json.dumps(args, sort_keys=True)})")
        except Exception:
            logger.exception("tool result store failed")

    def _serve_stale(self, event: AfterToolCallEvent, name: str, args: dict) -> None:
        stale = self._c.get(self._tool_key(name, args, prefix=PREFIX_TOOL_STALE))
        if stale is None or not isinstance(event.result, dict):
            return
        event.result["status"] = "success"
        event.result["content"] = [
            {"text": f"[stale cached value; live lookup failed] {_decode(stale)}"}
        ]


# ---------------------------------------------------------------------------
# ReasoningCache - the plan cache
# ---------------------------------------------------------------------------

class ReasoningCache(HookProvider):
    """Question -> tool plan. Injects a matching plan; stores the trajectory."""

    def __init__(self, client, cfg: ValkeyCacheConfig):
        self._c = client
        self._cfg = cfg
        self.question: str | None = None
        self.plan_used = False

    def _embed(self, text: str) -> bytes:
        return embedding_to_bytes(
            generate_embedding(text, self._cfg.embedding_model_id, self._cfg.region)
        )

    @staticmethod
    def _question_of(event) -> str | None:
        if not event.messages:
            return None
        texts = [b["text"] for b in event.messages[-1].get("content", []) if "text" in b]
        return " ".join(texts) if texts else None

    def register_hooks(self, registry: HookRegistry) -> None:
        registry.add_callback(BeforeInvocationEvent, self.inject_plan)
        registry.add_callback(AfterInvocationEvent, self.store_plan)

    def inject_plan(self, event: BeforeInvocationEvent) -> None:
        self.question = None
        self.plan_used = False
        event.invocation_state["trajectory"] = []
        if getattr(event, "cancel", False):          # response-cache hit already ended this
            return
        self.question = self._question_of(event)
        if not self.question:
            return
        try:
            result = self._c.execute_command(
                "FT.SEARCH", TRAJ_INDEX,
                "*=>[KNN 1 @embedding $vec AS score]",
                "PARAMS", "2", "vec", self._embed(self.question),
                "RETURN", "2", "entry_id", "score",
                "DIALECT", "2",
            )
        except Exception:
            logger.exception("trajectory lookup failed")
            return
        if not result or int(result[0]) == 0:
            return
        fields = result[2]
        doc = {_decode(fields[i]): _decode(fields[i + 1]) for i in range(0, len(fields), 2)}
        similarity = 1.0 - (float(doc["score"]) / 2.0)
        if similarity < self._cfg.similarity_threshold:
            return
        plan = self._c.get(f"{PREFIX_TRAJ_PLAN}{doc['entry_id']}")
        if not plan:
            return
        event.messages[-1]["content"].append({"text":
            "\n\n[cached plan] A similar question used these tool calls, "
            f"arguments already resolved: {_decode(plan)}. Call them in your "
            "first response, then answer."})
        self.plan_used = True

    def store_plan(self, event: AfterInvocationEvent) -> None:
        trajectory = event.invocation_state.get("trajectory", [])
        if not self.question or not trajectory or self.plan_used:
            return
        try:
            entry_id = "traj:" + hashlib.md5(
                self.question.encode(), usedforsecurity=False).hexdigest()
            ttl = self._cfg.trajectory_ttl_seconds
            self._c.hset(f"{PREFIX_TRAJ_VEC}{entry_id}", mapping={
                "embedding": self._embed(self.question),
                "entry_id": entry_id,
            })
            self._c.set(f"{PREFIX_TRAJ_PLAN}{entry_id}", ", ".join(trajectory), ex=ttl)
            self._c.expire(f"{PREFIX_TRAJ_VEC}{entry_id}", ttl)
        except Exception:
            logger.exception("trajectory store failed")
