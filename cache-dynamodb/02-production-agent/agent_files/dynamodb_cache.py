"""DynamoDB-backed agent cache — all patterns in one module.

Replaces semantic_cache.py + reasoning_cache.py from the Valkey implementation.

Single table design: one DynamoDB table holds every cache pattern distinguished
by the ``entry_type`` attribute, which is also declared as an INLINE_FILTER on
the vector index so search_vectors() can scope KNN to one pattern.

entry_type values
-----------------
response      Semantic response cache (level-1, question -> answer)
plan          Plan template cache (A1)
tool_result   Tool result exact-match cache (no embedding)

DynamoDB vector search facts (from official AWS docs)
------------------------------------------------------
- SearchVector: plain list of {"N": "float_str"} — NOT wrapped in L type
- Score (COSINE): 0 = identical, 2 = opposite → similarity = 1 - score/2
- search_vectors() SearchConditionExpression supports equality (=) only
- TTL is eventually consistent — always verify ttl attribute on volatile reads
- Vector index is created at deploy time; no runtime index creation needed

References
----------
arXiv:2602.13165  near-miss promotion (Krites pattern)
arXiv:2602.19811  canonicalize-then-exact arg matching
arXiv:2605.20630  temporal-caching failure modes (critical-param guard)
arXiv:2606.15017  budget-matched savings accounting
"""

import hashlib
import json
import logging
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

from embeddings import generate_embedding
from tools import CACHE_VERSIONS, DEFAULT_TOOL_TTL, TOOL_TTL_SECONDS

logger = logging.getLogger(__name__)

# entry_type constants
ENTRY_RESPONSE = "response"
ENTRY_PLAN = "plan"
ENTRY_TOOL = "tool_result"

STALE_RETENTION_FACTOR = 4
NEGATIVE_TTL_SECONDS = 300

_FAILURE_MARKERS = (
    "no wikipedia article found", "no location found",
    "no flight offers found", "no data available", "no climate data",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _to_ddb_vector(embedding: list) -> list:
    """Convert a float list to the DynamoDB SearchVector / L attribute format."""
    return [{"N": str(v)} for v in embedding]


def _critical_params(text: str) -> set:
    """B5/B2 guard: extract dates/numbers that must match exactly.

    Embeddings score 'flights on 2026-09-15' vs 'flights on 2026-12-15' at
    ~0.97 cosine (arXiv:2605.20630), so similarity alone cannot separate them.
    """
    params = set(re.findall(r"\d{4}-\d{2}-\d{2}", text))
    params.update(re.findall(r"\b\d{1,2}/\d{1,2}(?:/\d{2,4})?\b", text))
    params.update(re.findall(r"\b\d+\b", text))
    return params


def _looks_like_failure(text: str) -> bool:
    lowered = text.strip().lower()
    return any(lowered.startswith(m) or m in lowered[:120] for m in _FAILURE_MARKERS)


def _tool_cache_key(tool_name: str, tool_input: dict) -> str:
    """B2 — canonicalize then hash for the tool result cache key."""
    normalized = {
        k: (" ".join(str(v).strip().lower().split()) if isinstance(v, str) else v)
        for k, v in tool_input.items()
    }
    version = CACHE_VERSIONS.get(tool_name, "v1")
    canonical = json.dumps(normalized, sort_keys=True, default=str)
    digest = hashlib.md5(
        f"{tool_name}:{version}:{canonical}".encode(), usedforsecurity=False
    ).hexdigest()
    return f"{tool_name}:{version}:{digest}"


def _tool_ttl(tool_name: str) -> int:
    return TOOL_TTL_SECONDS.get(tool_name, DEFAULT_TOOL_TTL)


def _make_cached_tool(cached_text: str):
    """Stub tool that returns a cached result without executing the real tool."""

    @tool
    def cached_lookup(
        place: str = "",
        latitude: float = 0.0,
        longitude: float = 0.0,
        topic: str = "",
        origin: str = "",
        destination: str = "",
        departure_date: str = "",
        cabin_class: str = "",
    ) -> str:
        """Return the cached result of a previous identical tool call."""
        return cached_text

    return cached_lookup


def flush_all(ddb_client, table_name: str) -> int:
    """Scan and delete every item in the table. Returns the count deleted."""
    count = 0
    paginator = ddb_client.get_paginator("scan")
    keys_to_delete = []
    for page in paginator.paginate(TableName=table_name, Select="SPECIFIC_ATTRIBUTES",
                                   ProjectionExpression="entry_id"):
        for item in page.get("Items", []):
            keys_to_delete.append({"entry_id": item["entry_id"]})
    # batch_write_item accepts at most 25 requests per call
    for i in range(0, len(keys_to_delete), 25):
        batch = keys_to_delete[i:i + 25]
        ddb_client.batch_write_item(
            RequestItems={
                table_name: [{"DeleteRequest": {"Key": k}} for k in batch]
            }
        )
        count += len(batch)
    return count


# ---------------------------------------------------------------------------
# SemanticResponseCache  (replaces semantic_cache.SemanticCache)
# ---------------------------------------------------------------------------

class SemanticResponseCache:
    """Level-1 cache: question → answer, searched by cosine similarity.

    All failures are logged and treated as misses (fail-open).
    """

    def __init__(
        self,
        ddb_client,
        table_name: str,
        vector_index: str,
        model_id: str,
        threshold: float,
        ttl: int,
        prompt_hash: str = "",
    ):
        self._ddb = ddb_client
        self._table = table_name
        self._index = vector_index
        self._model_id = model_id
        self._threshold = threshold
        self._ttl = ttl
        self._prompt_hash = prompt_hash
        self._last_near_miss = None

    def lookup(self, question: str) -> dict | None:
        try:
            qvec = _to_ddb_vector(generate_embedding(question))
            resp = self._ddb.search_vectors(
                TableName=self._table,
                IndexName=self._index,
                SearchVector=qvec,
                TopK=1,
                SearchConditionExpression="entry_type = :et AND model_id = :m",
                ExpressionAttributeValues={
                    ":et": {"S": ENTRY_RESPONSE},
                    ":m":  {"S": self._model_id},
                },
            )
        except Exception:
            logger.exception("response cache lookup failed, treating as miss")
            return None

        results = resp.get("SearchResults", [])
        if not results:
            return None

        score = results[0]["Score"]
        similarity = 1.0 - (score / 2.0)
        item = results[0]["Item"]
        entry_id = item.get("entry_id", {}).get("S", "")

        if similarity < self._threshold:
            logger.info(json.dumps({
                "cache_miss_best_similarity": round(similarity, 4),
                "threshold": self._threshold,
            }))
            if similarity >= self._threshold - 0.10:
                self._last_near_miss = {"entry_id": entry_id, "similarity": round(similarity, 4)}
            else:
                self._last_near_miss = None
            return None
        self._last_near_miss = None

        # Critical-parameter guard (arXiv:2605.20630)
        cached_question = item.get("question", {}).get("S", "")
        if _critical_params(question) != _critical_params(cached_question):
            logger.info(json.dumps({"cache_param_mismatch": True, "similarity": round(similarity, 4)}))
            self._last_near_miss = None
            return None

        return {
            "answer":       item.get("answer", {}).get("S", ""),
            "similarity":   round(similarity, 4),
            "tokens_saved": int(item.get("total_tokens", {}).get("N", "0")),
            "entry_id":     entry_id,
            "prompt_current": item.get("prompt_hash", {}).get("S", "") == self._prompt_hash,
        }

    @property
    def near_miss(self) -> dict | None:
        return self._last_near_miss

    def promote_near_miss(self, question: str, fresh_answer: str) -> bool:
        """B1 — verified near-miss promotion (Krites pattern, arXiv:2602.13165)."""
        candidate = self.near_miss
        if not candidate:
            return False
        try:
            resp = self._ddb.get_item(
                TableName=self._table,
                Key={"entry_id": {"S": candidate["entry_id"]}},
            )
            cached_item = resp.get("Item")
            if not cached_item:
                return False
            cached_answer = cached_item.get("answer", {}).get("S", "")
            vec_a = generate_embedding(fresh_answer[:1500])
            vec_b = generate_embedding(cached_answer[:1500])
            dot = sum(x * y for x, y in zip(vec_a, vec_b))
            norm = (sum(x * x for x in vec_a) ** 0.5) * (sum(y * y for y in vec_b) ** 0.5)
            agreement = dot / norm if norm else 0.0
            if agreement < 0.90:
                return False
            alias_id = str(uuid.uuid4())
            self._ddb.put_item(
                TableName=self._table,
                Item={
                    "entry_id":   {"S": alias_id},
                    "entry_type": {"S": ENTRY_RESPONSE},
                    "model_id":   {"S": self._model_id},
                    "question":   {"S": question},
                    "answer":     {"S": cached_item.get("answer", {}).get("S", "")},
                    "prompt_hash":{"S": self._prompt_hash},
                    "total_tokens":{"N": cached_item.get("total_tokens", {}).get("N", "0")},
                    "created_at": {"N": str(int(time.time()))},
                    "ttl":        {"N": str(int(time.time()) + self._ttl)},
                    "embedding":  {"L": _to_ddb_vector(generate_embedding(question))},
                },
            )
            logger.info(json.dumps({
                "near_miss_promoted": True,
                "similarity": candidate["similarity"],
                "answer_agreement": round(agreement, 4),
            }))
            return True
        except Exception:
            logger.exception("near-miss promotion failed")
            return False

    def refresh(self, entry_id: str, answer: str) -> None:
        try:
            self._ddb.update_item(
                TableName=self._table,
                Key={"entry_id": {"S": entry_id}},
                UpdateExpression="SET answer = :a, prompt_hash = :ph",
                ExpressionAttributeValues={
                    ":a":  {"S": answer},
                    ":ph": {"S": self._prompt_hash},
                },
            )
        except Exception:
            logger.exception("cache refresh failed")

    def store(self, question: str, answer: str, usage: dict) -> None:
        try:
            entry_id = str(uuid.uuid4())
            import random
            ttl = self._ttl + random.randint(0, max(1, self._ttl // 10))  # nosec B311 - random only for TTL jitter, not security
            self._ddb.put_item(
                TableName=self._table,
                Item={
                    "entry_id":    {"S": entry_id},
                    "entry_type":  {"S": ENTRY_RESPONSE},
                    "model_id":    {"S": self._model_id},
                    "question":    {"S": question},
                    "answer":      {"S": answer},
                    "prompt_hash": {"S": self._prompt_hash},
                    "input_tokens": {"N": str(usage.get("inputTokens", 0))},
                    "output_tokens":{"N": str(usage.get("outputTokens", 0))},
                    "total_tokens": {"N": str(usage.get("totalTokens", 0))},
                    "created_at":  {"N": str(int(time.time()))},
                    "ttl":         {"N": str(int(time.time()) + ttl)},
                    "embedding":   {"L": _to_ddb_vector(generate_embedding(question))},
                },
            )
        except Exception:
            logger.exception("response cache store failed")


# ---------------------------------------------------------------------------
# ToolResultCache  (replaces serverless Valkey exact-match cache)
# ---------------------------------------------------------------------------

class ToolResultCache:
    """Exact-match cache for tool results keyed by hash(tool_name + args).

    DynamoDB TTL is eventually consistent. For volatile data (search_flights,
    5-minute TTL), the ttl attribute is verified manually on every read to
    guarantee freshness (arXiv note: standard defensive pattern for DDB TTL).
    """

    def __init__(self, ddb_client, table_name: str):
        self._ddb = ddb_client
        self._table = table_name

    def get(self, cache_key: str) -> str | None:
        try:
            resp = self._ddb.get_item(
                TableName=self._table,
                Key={"entry_id": {"S": cache_key}},
            )
            item = resp.get("Item")
            if not item:
                return None
            # Manual TTL check — DDB TTL deletion can lag by minutes/hours
            if int(item.get("ttl", {}).get("N", "0")) < int(time.time()):
                return None
            return item.get("result", {}).get("S")
        except Exception:
            logger.exception("tool cache get failed")
            return None

    def set(self, cache_key: str, result: str, ttl_seconds: int) -> None:
        try:
            self._ddb.put_item(
                TableName=self._table,
                Item={
                    "entry_id":   {"S": cache_key},
                    "entry_type": {"S": ENTRY_TOOL},
                    "result":     {"S": result},
                    "created_at": {"N": str(int(time.time()))},
                    "ttl":        {"N": str(int(time.time()) + ttl_seconds)},
                },
            )
        except Exception:
            logger.exception("tool cache set failed")

    def set_stale(self, cache_key: str, result: str, stale_ttl: int) -> None:
        try:
            self._ddb.put_item(
                TableName=self._table,
                Item={
                    "entry_id":   {"S": f"stale:{cache_key}"},
                    "entry_type": {"S": ENTRY_TOOL},
                    "result":     {"S": result},
                    "created_at": {"N": str(int(time.time()))},
                    "ttl":        {"N": str(int(time.time()) + stale_ttl)},
                },
            )
        except Exception:
            logger.exception("stale tool cache set failed")

    def get_stale(self, cache_key: str) -> str | None:
        try:
            resp = self._ddb.get_item(
                TableName=self._table,
                Key={"entry_id": {"S": f"stale:{cache_key}"}},
            )
            item = resp.get("Item")
            if not item:
                return None
            return item.get("result", {}).get("S")
        except Exception:
            logger.exception("stale tool cache get failed")
            return None


# ---------------------------------------------------------------------------
# PlanTemplateCache  (A1 — replaces plancache:* Valkey keys)
# ---------------------------------------------------------------------------

class PlanTemplateCache:

    def __init__(self, ddb_client, table_name: str, vector_index: str,
                 threshold: float = 0.85, ttl: int = 86400):
        self._ddb = ddb_client
        self._table = table_name
        self._index = vector_index
        self._threshold = threshold
        self._ttl = ttl

    def lookup(self, question: str) -> tuple[str | None, int]:
        """Returns (template_json_str, cold_tokens) or (None, 0)."""
        try:
            qvec = _to_ddb_vector(generate_embedding(question))
            resp = self._ddb.search_vectors(
                TableName=self._table,
                IndexName=self._index,
                SearchVector=qvec,
                TopK=1,
                SearchConditionExpression="entry_type = :et",
                ExpressionAttributeValues={":et": {"S": ENTRY_PLAN}},
            )
        except Exception:
            logger.exception("plan cache lookup failed")
            return None, 0

        results = resp.get("SearchResults", [])
        if not results:
            return None, 0

        score = results[0]["Score"]
        similarity = 1.0 - (score / 2.0)
        if similarity < self._threshold:
            return None, 0

        item = results[0]["Item"]
        template_str = item.get("template", {}).get("S")
        cold_tokens = int(item.get("cold_tokens", {}).get("N", "0"))
        if not template_str:
            return None, 0
        return template_str, cold_tokens

    def store(self, question: str, template: dict, cold_tokens: int) -> None:
        try:
            entry_id = str(uuid.uuid4())
            self._ddb.put_item(
                TableName=self._table,
                Item={
                    "entry_id":    {"S": entry_id},
                    "entry_type":  {"S": ENTRY_PLAN},
                    "question":    {"S": question},
                    "template":    {"S": json.dumps(template)},
                    "cold_tokens": {"N": str(cold_tokens)},
                    "created_at":  {"N": str(int(time.time()))},
                    "ttl":         {"N": str(int(time.time()) + self._ttl)},
                    "embedding":   {"L": _to_ddb_vector(generate_embedding(question))},
                },
            )
        except Exception:
            logger.exception("plan cache store failed")

    def flush(self) -> int:
        """Delete all plan entries. Returns count deleted."""
        count = 0
        try:
            paginator = self._ddb.get_paginator("query")
            for page in paginator.paginate(
                TableName=self._table,
                IndexName="entry-type-index",
                KeyConditionExpression="entry_type = :et",
                ExpressionAttributeValues={":et": {"S": ENTRY_PLAN}},
                Select="SPECIFIC_ATTRIBUTES",
                ProjectionExpression="entry_id",
            ):
                keys = [{"entry_id": item["entry_id"]} for item in page.get("Items", [])]
                for i in range(0, len(keys), 25):
                    self._ddb.batch_write_item(
                        RequestItems={
                            self._table: [{"DeleteRequest": {"Key": k}} for k in keys[i:i + 25]]
                        }
                    )
                    count += len(keys[i:i + 25])
        except Exception:
            logger.exception("plan cache flush failed")
        return count


# ---------------------------------------------------------------------------
# ReasoningCacheHook  (replaces reasoning_cache.ReasoningCacheHook)
# ---------------------------------------------------------------------------

class ReasoningCacheHook(HookProvider):
    """DynamoDB-backed in-loop reasoning cache wired through Strands hooks.

    Registers the same four hook events as the Valkey version:

    1. BeforeInvocationEvent  — KNN lookup for a similar past question's
       tool trajectory; on a hit a plan hint is appended to the user message.
    2. BeforeToolCallEvent    — exact-match tool result lookup; on a hit
       the real tool is swapped for a stub returning the cached result.
    3. AfterToolCallEvent     — store fresh tool results; record trajectory.
    4. AfterInvocationEvent   — store the question → trajectory mapping.

    Both lookup failures and store failures are logged and ignored (fail-open).
    """

    def __init__(
        self,
        ddb_client,
        table_name: str,
        vector_index: str,
        entry_type_gsi: str,
        threshold: float = 0.85,
        ttl: int = 86400,
    ):
        self._tool_cache = ToolResultCache(ddb_client, table_name)
        self._ddb = ddb_client
        self._table = table_name
        self._index = vector_index
        self._gsi = entry_type_gsi
        self._threshold = threshold
        self._ttl = ttl
        # Per-invocation scratch state
        self._question = None
        self._trajectory: list = []
        self._served_from_cache: set = set()
        self.stats: dict = {}
        self.flow: list = []

    def register_hooks(self, registry: HookRegistry) -> None:
        registry.add_callback(BeforeInvocationEvent, self.inject_plan_hint)
        registry.add_callback(BeforeToolCallEvent, self.serve_cached_tool)
        registry.add_callback(AfterToolCallEvent, self.capture_tool_result)
        registry.add_callback(AfterInvocationEvent, self.store_trajectory)

    # -- 1. Reasoning savings: plan hint on a semantically similar question --

    def inject_plan_hint(self, event: BeforeInvocationEvent) -> None:
        self._trajectory = []
        self._served_from_cache = set()
        self.stats = {"plan_hint": False, "tool_cache_hits": 0, "tool_executions": 0}
        self._question = None
        self.flow = []

        try:
            if not event.messages:
                return
            content = event.messages[-1].get("content", [])
            texts = [b["text"] for b in content if "text" in b]
            if not texts:
                return
            self._question = " ".join(texts)

            self.flow.append({"step": "trajectory_lookup", "store": "dynamodb",
                              "detail": "KNN search for a similar past question"})
            plan, cold_tokens = self._lookup_trajectory(self._question)
            if not plan:
                self.flow.append({"step": "trajectory_miss", "kind": "miss",
                                  "detail": "no similar question above threshold — cold run"})
                return
            self.stats["cold_baseline_tokens"] = cold_tokens
            hint = (
                "\n\n[cached plan] A semantically similar question was "
                "answered before with exactly these tool calls (arguments "
                f"already resolved): {plan}. Issue ALL of these tool calls "
                "together in your FIRST response — do not call one and "
                "wait, the arguments above are already correct. Then "
                "answer directly. Do not explore other tools."
            )
            content.append({"text": hint})
            self.stats["plan_hint"] = True
            self.flow.append({"step": "plan_hint_injected", "kind": "hit",
                              "detail": plan[:120]})
        except Exception:
            logger.exception("plan hint lookup failed, continuing without it")

    def _lookup_trajectory(self, question: str) -> tuple[str | None, int]:
        """Search for a similar past trajectory; returns (plan_str, cold_tokens)."""
        try:
            qvec = _to_ddb_vector(generate_embedding(question))
            resp = self._ddb.search_vectors(
                TableName=self._table,
                IndexName=self._index,
                SearchVector=qvec,
                TopK=1,
                SearchConditionExpression="entry_type = :et",
                ExpressionAttributeValues={":et": {"S": "trajectory"}},
            )
        except Exception:
            logger.exception("trajectory KNN lookup failed")
            return None, 0

        results = resp.get("SearchResults", [])
        if not results:
            return None, 0

        score = results[0]["Score"]
        similarity = 1.0 - (score / 2.0)
        if similarity < self._threshold:
            return None, 0

        item = results[0]["Item"]
        plan = item.get("plan", {}).get("S")
        cold_tokens = int(item.get("cold_tokens", {}).get("N", "0"))
        if not plan:
            return None, 0
        return plan, cold_tokens

    # -- 2. Tool-execution savings: swap in a stub on an exact result hit --

    def serve_cached_tool(self, event: BeforeToolCallEvent) -> None:
        try:
            name = event.tool_use["name"]
            args = event.tool_use["input"]
            key = _tool_cache_key(name, args)
            cached = self._tool_cache.get(key)
            if cached is not None:
                event.selected_tool = _make_cached_tool(cached)
                self.stats["tool_cache_hits"] += 1
                self._served_from_cache.add(event.tool_use.get("toolUseId"))
                self.flow.append({"step": "tool_cache_hit", "kind": "hit",
                                  "store": "dynamodb", "tool": name,
                                  "detail": "result served from cache — tool NOT executed"})
            else:
                self.flow.append({"step": "tool_executed", "kind": "miss",
                                  "tool": name,
                                  "detail": "no cached result — real API called"})
        except Exception:
            logger.exception("tool cache lookup failed, running the real tool")

    # -- 3. Capture: store tool results and record the trajectory --

    def capture_tool_result(self, event: AfterToolCallEvent) -> None:
        name = event.tool_use["name"]
        args = event.tool_use["input"]
        self._trajectory.append(f"{name}({json.dumps(args, sort_keys=True)})")
        try:
            if event.tool_use.get("toolUseId") in self._served_from_cache:
                return
            if (event.exception is not None) or (
                isinstance(event.result, dict)
                and event.result.get("status") == "error"
            ):
                self._serve_stale(event, name, args)
                return
            content = event.result.get("content", [])
            texts = [b["text"] for b in content if "text" in b]
            if not texts:
                return
            self.stats["tool_executions"] += 1
            text = " ".join(texts)
            key = _tool_cache_key(name, args)
            if _looks_like_failure(text):
                # B3 — negative caching
                self._tool_cache.set(key, text, NEGATIVE_TTL_SECONDS)
                self.flow.append({"step": "negative_cached", "kind": "store",
                                  "store": "dynamodb", "tool": name,
                                  "detail": f"failure cached for {NEGATIVE_TTL_SECONDS}s"})
                return
            ttl = _tool_ttl(name)
            self._tool_cache.set(key, text, ttl)
            self._tool_cache.set_stale(key, text, ttl * STALE_RETENTION_FACTOR)
            self.flow.append({"step": "tool_result_stored", "kind": "store",
                              "store": "dynamodb", "tool": name,
                              "detail": f"cached for {ttl}s"})
        except Exception:
            logger.exception("tool result capture failed")

    def _serve_stale(self, event: AfterToolCallEvent, name: str, args: dict) -> None:
        stale = self._tool_cache.get_stale(_tool_cache_key(name, args))
        if stale is None or not isinstance(event.result, dict):
            return
        event.result["status"] = "success"
        event.result["content"] = [{"text": f"[stale cached value; live lookup failed] {stale}"}]
        self.stats["stale_served"] = self.stats.get("stale_served", 0) + 1

    # -- 4. Capture: store the question -> trajectory mapping --

    def store_trajectory(self, event: AfterInvocationEvent) -> None:
        try:
            if not self._question or not self._trajectory or self.stats["plan_hint"]:
                return
            entry_id = hashlib.md5(self._question.encode(), usedforsecurity=False).hexdigest()
            cold_tokens = 0
            if event.result is not None:
                try:
                    cold_tokens = int(event.result.metrics.accumulated_usage["totalTokens"])
                except (AttributeError, KeyError, TypeError):
                    pass
            self._ddb.put_item(
                TableName=self._table,
                Item={
                    "entry_id":    {"S": entry_id},
                    "entry_type":  {"S": "trajectory"},
                    "question":    {"S": self._question},
                    "plan":        {"S": ", ".join(self._trajectory)},
                    "cold_tokens": {"N": str(cold_tokens)},
                    "created_at":  {"N": str(int(time.time()))},
                    "ttl":         {"N": str(int(time.time()) + self._ttl)},
                    "embedding":   {"L": _to_ddb_vector(generate_embedding(self._question))},
                },
            )
            self.flow.append({"step": "trajectory_stored", "kind": "store",
                              "store": "dynamodb",
                              "detail": f"question + tool plan saved ({len(self._trajectory)} calls)"})
        except Exception:
            logger.exception("trajectory store failed")
