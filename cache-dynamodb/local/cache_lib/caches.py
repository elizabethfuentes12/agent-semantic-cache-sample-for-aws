"""The three cache layers, each a Strands hook, on one DynamoDB table.

This is the packaged version of what the notebook builds inline. All three are
independent HookProviders on a single agent; they never talk to the model about
caching, and they share the tool trajectory through ``invocation_state``.

- ResponseCache: BeforeInvocationEvent looks up the question; on a hit it sets
  ``event.cancel`` to the stored answer so the model never runs (0 tokens).
  AfterInvocationEvent stores a freshly generated answer.
- ToolResultCache: BeforeToolCallEvent serves an exact repeated (tool, args)
  result via a stub; AfterToolCallEvent stores fresh results (negative-caching
  the not-useful ones) and records the call in the shared trajectory.
- ReasoningCache: BeforeInvocationEvent injects a matching past tool plan;
  AfterInvocationEvent stores this question's trajectory as its plan.

Everything is keyed/scoped by a ``kind`` attribute on one table, matching
``table.py``. Everything fails open: a store or lookup error is logged and
treated as a miss.
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
    KIND_ANSWER,
    KIND_TOOL,
    KIND_TRAJECTORY,
    NEGATIVE_TTL_SECONDS,
    TOOL_TTL_SECONDS,
    CacheConfig,
)
from cache_lib.embeddings import generate_embedding, to_ddb_vector

logger = logging.getLogger(__name__)

# Results that succeeded technically but found nothing useful. These are
# negative-cached briefly and kept out of the reasoning trajectory. The Duffel
# "no API key" message is included so a missing key is not cached as a success.
_NOT_USEFUL = (
    "no location found", "no wikipedia article found", "no summary available",
    "no flight offers found", "no climate data", "no data available",
    "no duffel api key",
)


# ---------------------------------------------------------------------------
# ResponseCache - level 1
# ---------------------------------------------------------------------------

class ResponseCache(HookProvider):
    """Question -> answer. On a hit, cancels the invocation (0 tokens)."""

    def __init__(self, ddb, cfg: CacheConfig):
        self._ddb = ddb
        self._cfg = cfg
        self.question: str | None = None
        self.hit: dict | None = None

    def _embed(self, text):
        return generate_embedding(text, self._cfg.embedding_model_id, self._cfg.region)

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
            resp = self._ddb.search_vectors(
                TableName=self._cfg.table_name,
                IndexName=self._cfg.vector_index_name,
                SearchVector=to_ddb_vector(self._embed(question)),
                TopK=1,
                SearchConditionExpression="kind = :k",
                ExpressionAttributeValues={":k": {"S": KIND_ANSWER}},
            )
        except Exception:
            logger.exception("response cache lookup failed, treating as miss")
            return None
        results = resp.get("SearchResults", [])
        if not results:
            return None
        similarity = 1.0 - results[0]["Score"] / 2.0
        if similarity < self._cfg.similarity_threshold:
            return None
        item = results[0]["Item"]
        # dates/numbers must match exactly even on a high-similarity hit
        if self._critical_params(question) != self._critical_params(item.get("question", {}).get("S", "")):
            return None
        return {
            "answer": item["answer"]["S"],
            "similarity": round(similarity, 4),
            "tokens_saved": int(item.get("tokens", {}).get("N", "0")),
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
            self._ddb.put_item(TableName=self._cfg.table_name, Item={
                "entry_id": {"S": str(uuid.uuid4())},
                "kind": {"S": KIND_ANSWER},
                "question": {"S": self.question},
                "answer": {"S": str(event.result)},
                "tokens": {"N": str(tokens)},
                "ttl": {"N": str(int(time.time()) + ttl)},
                "embedding": {"L": to_ddb_vector(self._embed(self.question))},
            })
        except Exception:
            logger.exception("response cache store failed")


# ---------------------------------------------------------------------------
# ToolResultCache - the tool-result cache
# ---------------------------------------------------------------------------

class ToolResultCache(HookProvider):
    """Exact (tool, args) -> result. Serves via a stub; negative-caches misses."""

    def __init__(self, ddb, cfg: CacheConfig):
        self._ddb = ddb
        self._cfg = cfg
        self.hits = 0
        self.executions = 0
        self._served: set = set()

    def register_hooks(self, registry: HookRegistry) -> None:
        registry.add_callback(BeforeInvocationEvent, self.reset)
        registry.add_callback(BeforeToolCallEvent, self.serve)
        registry.add_callback(AfterToolCallEvent, self.store)

    @staticmethod
    def _tool_key(tool_name: str, tool_input: dict) -> str:
        normalized = {
            k: (" ".join(str(v).strip().lower().split()) if isinstance(v, str) else v)
            for k, v in tool_input.items()
        }
        canonical = json.dumps(normalized, sort_keys=True, default=str)
        digest = hashlib.md5(
            f"{tool_name}:{canonical}".encode(), usedforsecurity=False
        ).hexdigest()
        return f"toolcall:{digest}"

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
            item = self._ddb.get_item(TableName=self._cfg.table_name,
                                      Key={"entry_id": {"S": key}}).get("Item")
            if item and int(item.get("ttl", {}).get("N", "0")) >= int(time.time()):
                event.selected_tool = self._stub_tool(item["result"]["S"])
                self.hits += 1
                self._served.add(event.tool_use.get("toolUseId"))
            else:
                self.executions += 1
        except Exception:
            logger.exception("tool cache lookup failed, running the real tool")

    def store(self, event: AfterToolCallEvent) -> None:
        try:
            name, args = event.tool_use["name"], event.tool_use["input"]
            # A served hit still fires AfterToolCallEvent. Do NOT re-store it, or
            # the TTL would refresh on every hit and a volatile result (a flight
            # price) would live forever. Record it in the trajectory only if the
            # served result was useful, so a negative-cached dead end (a served
            # "no location found") never becomes a step in the stored plan.
            if event.tool_use.get("toolUseId") in self._served:
                served_texts = [b["text"] for b in event.result.get("content", [])
                                if "text" in b] if isinstance(event.result, dict) else []
                if served_texts and self._is_useful(" ".join(served_texts)):
                    event.invocation_state.setdefault("trajectory", []).append(
                        f"{name}({json.dumps(args, sort_keys=True)})")
                return
            if not isinstance(event.result, dict) or event.result.get("status") == "error":
                return
            texts = [b["text"] for b in event.result.get("content", []) if "text" in b]
            result_text = " ".join(texts)
            if not result_text:
                return
            key = self._tool_key(name, args)
            if not self._is_useful(result_text):
                self._ddb.put_item(TableName=self._cfg.table_name, Item={
                    "entry_id": {"S": key},
                    "kind": {"S": KIND_TOOL},
                    "result": {"S": result_text},
                    "ttl": {"N": str(int(time.time()) + NEGATIVE_TTL_SECONDS)}})
                return
            self._ddb.put_item(TableName=self._cfg.table_name, Item={
                "entry_id": {"S": key},
                "kind": {"S": KIND_TOOL},
                "result": {"S": result_text},
                "ttl": {"N": str(int(time.time()) + self._tool_ttl(name))}})
            event.invocation_state.setdefault("trajectory", []).append(
                f"{name}({json.dumps(args, sort_keys=True)})")
        except Exception:
            logger.exception("tool result store failed")


# ---------------------------------------------------------------------------
# ReasoningCache - the plan cache
# ---------------------------------------------------------------------------

class ReasoningCache(HookProvider):
    """Question -> tool plan. Injects a matching plan; stores the trajectory."""

    def __init__(self, ddb, cfg: CacheConfig):
        self._ddb = ddb
        self._cfg = cfg
        self.question: str | None = None
        self.plan_used = False

    def _embed(self, text):
        return generate_embedding(text, self._cfg.embedding_model_id, self._cfg.region)

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
            resp = self._ddb.search_vectors(
                TableName=self._cfg.table_name,
                IndexName=self._cfg.vector_index_name,
                SearchVector=to_ddb_vector(self._embed(self.question)),
                TopK=1,
                SearchConditionExpression="kind = :k",
                ExpressionAttributeValues={":k": {"S": KIND_TRAJECTORY}},
            )
        except Exception:
            logger.exception("trajectory lookup failed")
            return
        results = resp.get("SearchResults", [])
        if results and 1.0 - results[0]["Score"] / 2.0 >= self._cfg.similarity_threshold:
            plan = results[0]["Item"]["plan"]["S"]
            event.messages[-1]["content"].append({"text":
                "\n\n[cached plan] A similar question used these tool calls, "
                f"arguments already resolved: {plan}. Call them in your first "
                "response, then answer."})
            self.plan_used = True

    def store_plan(self, event: AfterInvocationEvent) -> None:
        trajectory = event.invocation_state.get("trajectory", [])
        if not self.question or not trajectory or self.plan_used:
            return
        try:
            self._ddb.put_item(TableName=self._cfg.table_name, Item={
                "entry_id": {"S": "traj:" + hashlib.md5(self.question.encode()).hexdigest()},
                "kind": {"S": KIND_TRAJECTORY},
                "plan": {"S": ", ".join(trajectory)},
                "ttl": {"N": str(int(time.time()) + self._cfg.trajectory_ttl_seconds)},
                "embedding": {"L": to_ddb_vector(self._embed(self.question))},
            })
        except Exception:
            logger.exception("trajectory store failed")
