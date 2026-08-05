"""In-loop reasoning cache for Strands agents, backed by Valkey.

Two cooperating caches wired through Strands hooks:

1. TRAJECTORY cache (semantic, vector search) — saves REASONING tokens.
   `BeforeInvocationEvent.messages` is writable (verified in SDK source);
   on a semantic hit for a similar past question, a plan hint is appended
   to the user message: "for questions like this, the right tools are X(args)".
   The model picks the correct tools in its first cycle instead of exploring,
   which cuts event-loop cycles and the deliberation tokens they cost.

2. TOOL-RESULT cache (exact match) — saves TOOL EXECUTION.
   `BeforeToolCallEvent.selected_tool` is writable (documented Tool
   Interception pattern); on an exact (tool, args) hit the real tool is
   swapped for a stub that returns the cached result, so the tool never
   executes.

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

logger = logging.getLogger(__name__)

TRAJ_INDEX = "idx:trajcache"
PREFIX_TRAJ_VEC = "trajcache:vec:"
PREFIX_TRAJ_PLAN = "trajcache:plan:"
PREFIX_TOOL = "toolcache:"


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


def _tool_cache_key(tool_name: str, tool_input: dict) -> str:
    canonical = json.dumps(tool_input, sort_keys=True, default=str)
    digest = hashlib.md5(f"{tool_name}:{canonical}".encode()).hexdigest()
    return f"{PREFIX_TOOL}{tool_name}:{digest}"


def _make_cached_tool(cached_text: str):
    """Stub tool returning a cached result. All real tool parameters appear
    here as optional so the original tool_use input still validates."""

    @tool
    def cached_lookup(
        place: str = "",
        latitude: float = 0.0,
        longitude: float = 0.0,
        topic: str = "",
    ) -> str:
        """Return the cached result of a previous identical tool call."""
        return cached_text

    return cached_lookup


class ReasoningCacheHook(HookProvider):
    """Registers the four cache touchpoints on the agent's event loop."""

    def __init__(self, client, threshold: float, ttl: int):
        self.client = client
        self.threshold = threshold
        self.ttl = ttl
        # Per-invocation scratch state (Lambda handles one request at a time).
        self._question = None
        self._trajectory = []
        self._served_from_cache = set()
        self.stats = {}

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

        try:
            if not event.messages:
                return
            content = event.messages[-1].get("content", [])
            texts = [b["text"] for b in content if "text" in b]
            if not texts:
                return
            self._question = " ".join(texts)

            plan = self._lookup_trajectory(self._question)
            if plan:
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
        except Exception:
            logger.exception("plan hint lookup failed, continuing without it")

    def _lookup_trajectory(self, question: str) -> str | None:
        query_vec = embedding_to_bytes(generate_embedding(question))
        result = self.client.execute_command(
            "FT.SEARCH", TRAJ_INDEX,
            "*=>[KNN 1 @embedding $vec AS score]",
            "PARAMS", "2", "vec", query_vec,
            "RETURN", "2", "entry_id", "score",
            "DIALECT", "2",
        )
        if not result or int(result[0]) == 0:
            return None
        fields = result[2]
        doc = {}
        for i in range(0, len(fields), 2):
            k = fields[i].decode() if isinstance(fields[i], bytes) else fields[i]
            v = fields[i + 1].decode() if isinstance(fields[i + 1], bytes) else fields[i + 1]
            doc[k] = v
        similarity = 1.0 - (float(doc["score"]) / 2.0)
        if similarity < self.threshold:
            return None
        plan = self.client.get(f"{PREFIX_TRAJ_PLAN}{doc['entry_id']}")
        return plan.decode() if plan else None

    # -- 2. Tool-execution savings: swap in a stub on an exact result hit --

    def serve_cached_tool(self, event: BeforeToolCallEvent) -> None:
        try:
            key = _tool_cache_key(event.tool_use["name"], event.tool_use["input"])
            cached = self.client.get(key)
            if cached is not None:
                # Documented interception pattern: replace the tool instance.
                event.selected_tool = _make_cached_tool(cached.decode())
                self.stats["tool_cache_hits"] += 1
                self._served_from_cache.add(event.tool_use.get("toolUseId"))
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
            if isinstance(event.result, Exception):
                return
            content = event.result.get("content", [])
            texts = [b["text"] for b in content if "text" in b]
            if not texts:
                return
            self.stats["tool_executions"] += 1
            self.client.set(
                _tool_cache_key(name, args), " ".join(texts), ex=self.ttl
            )
        except Exception:
            logger.exception("tool result store failed")

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
            self.client.expire(f"{PREFIX_TRAJ_VEC}{entry_id}", self.ttl)
        except Exception:
            logger.exception("trajectory store failed")
