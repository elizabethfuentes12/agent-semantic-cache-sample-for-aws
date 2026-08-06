"""In-loop reasoning cache for Strands agents — split-store design.

Two cooperating caches wired through Strands hooks, each on the store that
matches its access pattern:

1. TRAJECTORY cache (semantic) — NODE-BASED Valkey cluster, because KNN
   lookup needs FT.* vector search (not available on serverless).
   `BeforeInvocationEvent.messages` is writable (verified in SDK source);
   on a semantic hit for a similar past question, a plan hint is appended
   to the user message. The model picks the correct tools in its first
   cycle instead of exploring — that cuts reasoning cycles and tokens.

2. TOOL-RESULT cache (exact match) — ELASTICACHE SERVERLESS, because tool
   results are ephemeral, TTL-heavy key-value data with unpredictable
   volume; serverless scales that automatically and needs no node sizing.
   `BeforeToolCallEvent.selected_tool` is writable (documented Tool
   Interception pattern); on an exact (tool, args) hit the real tool is
   swapped for a stub returning the cached result.

Freshness policy (volatile data like prices/policies):
  - Per-tool TTLs declared next to the tools (TOOL_TTL_SECONDS) — stable
    data caches for weeks, volatile data for minutes.
  - Per-tool CACHE_VERSIONS in the key: bump to invalidate a tool's whole
    namespace on upstream changes.
  - Stale-on-error: every result is also kept in a longer-lived stale copy;
    if the real tool FAILS on a miss, the last known value is served with
    a [stale] marker instead of failing the request.

Both caches are populated by the After* events of a cold run. Everything
fails open: any cache error leaves the agent running normally.
"""

import hashlib
import json
import logging
import time

from strands import tool
from strands.hooks import (
    AfterInvocationEvent,
    AfterToolCallEvent,
    BeforeInvocationEvent,
    BeforeToolCallEvent,
    HookProvider,
    HookRegistry,
)
from valkey.exceptions import ResponseError

from embeddings import VECTOR_DIM, embedding_to_bytes, generate_embedding
from tools import CACHE_VERSIONS, DEFAULT_TOOL_TTL, TOOL_TTL_SECONDS

logger = logging.getLogger(__name__)

TRAJ_INDEX = "idx:trajcache"
PREFIX_TRAJ_VEC = "trajcache:vec:"
PREFIX_TRAJ_PLAN = "trajcache:plan:"
PREFIX_TOOL = "toolcache:"
PREFIX_TOOL_STALE = "toolstale:"
STALE_RETENTION_FACTOR = 4  # stale copy outlives the fresh one by this factor


def ensure_trajectory_index(client) -> None:
    """Create the trajectory HNSW index once. Idempotent."""
    try:
        client.execute_command(
            "FT.CREATE", TRAJ_INDEX,
            "ON", "HASH",
            "PREFIX", "1", PREFIX_TRAJ_VEC,
            "SCHEMA",
            "embedding", "VECTOR", "HNSW", "6",
                "TYPE", "FLOAT32",
                "DIM", str(VECTOR_DIM),
                "DISTANCE_METRIC", "COSINE",
            "entry_id", "TAG",
        )
    except ResponseError as e:
        if "already exists" not in str(e).lower():
            raise


def _normalize_args(tool_input: dict) -> dict:
    """B2 — canonicalize argument values before hashing so trivially
    different spellings share one cache entry ("Tokyo" / " tokyo ").
    Deterministic normalization then EXACT match — safer than fuzzy
    matching of args (arXiv:2602.19811: canonicalize-then-exact beats
    similarity thresholds on both hit rate and correctness)."""
    normalized = {}
    for key, value in tool_input.items():
        if isinstance(value, str):
            value = " ".join(value.strip().lower().split())
        normalized[key] = value
    return normalized


def _tool_cache_key(tool_name: str, tool_input: dict, prefix: str = PREFIX_TOOL) -> str:
    version = CACHE_VERSIONS.get(tool_name, "v1")
    canonical = json.dumps(_normalize_args(tool_input), sort_keys=True, default=str)
    digest = hashlib.md5(f"{tool_name}:{version}:{canonical}".encode()).hexdigest()
    return f"{prefix}{tool_name}:{version}:{digest}"


# B3 — negative caching: failure results are cached briefly so the agent
# does not hammer a tool that just failed with the same arguments. Short
# TTL keeps recovery fast. (Established distributed-systems pattern — AWS
# Builders' Library; no LLM-agent literature covers it yet.)
NEGATIVE_TTL_SECONDS = 300
_FAILURE_MARKERS = ("no wikipedia article found", "no location found",
                    "no flight offers found", "no data available",
                    "no climate data")


def _looks_like_failure(text: str) -> bool:
    lowered = text.strip().lower()
    return any(lowered.startswith(m) or m in lowered[:120] for m in _FAILURE_MARKERS)


def _tool_ttl(tool_name: str) -> int:
    return TOOL_TTL_SECONDS.get(tool_name, DEFAULT_TOOL_TTL)


def _make_cached_tool(cached_text: str):
    """Stub tool returning a cached result. All real tool parameters appear
    here as optional so the original tool_use input still validates."""

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


class ReasoningCacheHook(HookProvider):
    """Registers the four cache touchpoints on the agent's event loop.

    Args:
        client: node-based Valkey client (vector search — trajectories).
        tool_client: serverless Valkey client (exact-match tool results).
        threshold: min cosine similarity for a plan hint.
        ttl: TTL for trajectories (tool results use per-tool TTLs).
    """

    def __init__(self, client, tool_client, threshold: float, ttl: int):
        self.client = client
        self.tool_client = tool_client
        self.threshold = threshold
        self.ttl = ttl
        # Per-invocation scratch state (Lambda handles one request at a time).
        self._question = None
        self._trajectory = []
        self._served_from_cache = set()
        self.stats = {}
        # Flow timeline for the UI: ordered cache/loop touchpoints.
        self.flow = []

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

            self.flow.append({"step": "trajectory_lookup", "store": "node-based",
                              "detail": "KNN search for a similar past question"})
            plan, cold_tokens = self._lookup_trajectory(self._question)
            if not plan:
                self.flow.append({"step": "trajectory_miss", "kind": "miss",
                                  "detail": "no similar question above threshold — cold run"})
            if plan:
                self.stats["cold_baseline_tokens"] = cold_tokens
                hint = (
                    "\n\n[cached plan] A semantically similar question was "
                    "answered before with exactly these tool calls (arguments "
                    f"already resolved): {plan}. Issue ALL of these tool calls "
                    "together in your FIRST response — do not call one and "
                    "wait, the arguments above are already correct. Then "
                    "answer directly. Do not explore other tools."
                )
                # messages is a documented writable attribute of this event.
                content.append({"text": hint})
                self.stats["plan_hint"] = True
                self.flow.append({"step": "plan_hint_injected", "kind": "hit",
                                  "detail": plan[:120]})
        except Exception:
            logger.exception("plan hint lookup failed, continuing without it")

    def _lookup_trajectory(self, question: str) -> tuple[str | None, int]:
        """Returns (plan, cold_run_total_tokens) or (None, 0)."""
        query_vec = embedding_to_bytes(generate_embedding(question))
        result = self.client.execute_command(
            "FT.SEARCH", TRAJ_INDEX,
            "*=>[KNN 1 @embedding $vec AS score]",
            "PARAMS", "2", "vec", query_vec,
            "RETURN", "2", "entry_id", "score",
            "DIALECT", "2",
        )
        if not result or int(result[0]) == 0:
            return None, 0
        fields = result[2]
        doc = {}
        for i in range(0, len(fields), 2):
            k = fields[i].decode() if isinstance(fields[i], bytes) else fields[i]
            v = fields[i + 1].decode() if isinstance(fields[i + 1], bytes) else fields[i + 1]
            doc[k] = v
        similarity = 1.0 - (float(doc["score"]) / 2.0)
        if similarity < self.threshold:
            return None, 0
        plan = self.client.get(f"{PREFIX_TRAJ_PLAN}{doc['entry_id']}")
        if not plan:
            return None, 0
        tokens = self.client.get(f"{PREFIX_TRAJ_PLAN}{doc['entry_id']}:tokens")
        return plan.decode(), int(tokens or 0)

    # -- 2. Tool-execution savings: swap in a stub on an exact result hit --

    def serve_cached_tool(self, event: BeforeToolCallEvent) -> None:
        try:
            name = event.tool_use["name"]
            args = event.tool_use["input"]
            cached = self.tool_client.get(_tool_cache_key(name, args))
            if cached is not None:
                # Documented interception pattern: replace the tool instance.
                event.selected_tool = _make_cached_tool(cached.decode())
                self.stats["tool_cache_hits"] += 1
                self._served_from_cache.add(event.tool_use.get("toolUseId"))
                self.flow.append({"step": "tool_cache_hit", "kind": "hit",
                                  "store": "serverless", "tool": name,
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
            # Results served from the cache stub are not fresh executions:
            # don't count them and don't re-store them.
            if event.tool_use.get("toolUseId") in self._served_from_cache:
                return
            if isinstance(event.result, Exception) or (
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
            if _looks_like_failure(text):
                # B3 — negative cache: remember the failure briefly so the
                # loop doesn't re-call the same failing (tool, args).
                self.tool_client.set(
                    _tool_cache_key(name, args), text, ex=NEGATIVE_TTL_SECONDS
                )
                self.flow.append({"step": "negative_cached", "kind": "store",
                                  "store": "serverless", "tool": name,
                                  "detail": f"failure cached for {NEGATIVE_TTL_SECONDS}s"})
                return
            ttl = _tool_ttl(name)
            self.tool_client.set(_tool_cache_key(name, args), text, ex=ttl)
            self.flow.append({"step": "tool_result_stored", "kind": "store",
                              "store": "serverless", "tool": name,
                              "detail": f"cached for {ttl}s"})
            # Longer-lived stale copy: served only if the real tool fails.
            self.tool_client.set(
                _tool_cache_key(name, args, prefix=PREFIX_TOOL_STALE),
                text,
                ex=ttl * STALE_RETENTION_FACTOR,
            )
        except Exception:
            logger.exception("tool result store failed")

    def _serve_stale(self, event: AfterToolCallEvent, name: str, args: dict) -> None:
        """Freshness policy, availability leg: the fresh entry expired AND the
        real tool just failed — fall back to the last known value, marked
        stale, instead of surfacing the failure to the model."""
        stale = self.tool_client.get(
            _tool_cache_key(name, args, prefix=PREFIX_TOOL_STALE)
        )
        if stale is None or not isinstance(event.result, dict):
            return
        event.result["status"] = "success"
        event.result["content"] = [{
            "text": f"[stale cached value; live lookup failed] {stale.decode()}"
        }]
        self.stats["stale_served"] = self.stats.get("stale_served", 0) + 1

    # -- 4. Capture: store the question -> trajectory mapping semantically --

    def store_trajectory(self, event: AfterInvocationEvent) -> None:
        try:
            # Only store fresh, complete trajectories from questions that did
            # not already run on a hint — hint runs would re-store the same plan.
            if not self._question or not self._trajectory or self.stats["plan_hint"]:
                return
            entry_id = hashlib.md5(self._question.encode()).hexdigest()
            embedding = embedding_to_bytes(generate_embedding(self._question))
            self.client.hset(f"{PREFIX_TRAJ_VEC}{entry_id}", mapping={
                "embedding": embedding,
                "entry_id": entry_id,
                "timestamp": str(time.time()),
            })
            self.client.set(
                f"{PREFIX_TRAJ_PLAN}{entry_id}",
                ", ".join(self._trajectory),
                ex=self.ttl,
            )
            # Cold-run token cost, the baseline a later warm run saves against.
            cold_tokens = 0
            if event.result is not None:
                try:
                    cold_tokens = int(
                        event.result.metrics.accumulated_usage["totalTokens"]
                    )
                except (AttributeError, KeyError, TypeError):
                    cold_tokens = 0
            self.client.set(
                f"{PREFIX_TRAJ_PLAN}{entry_id}:tokens", str(cold_tokens), ex=self.ttl
            )
            self.client.expire(f"{PREFIX_TRAJ_VEC}{entry_id}", self.ttl)
            self.flow.append({"step": "trajectory_stored", "kind": "store",
                              "store": "node-based",
                              "detail": f"question + tool plan saved ({len(self._trajectory)} calls)"})
        except Exception:
            logger.exception("trajectory store failed")
