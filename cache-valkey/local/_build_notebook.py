#!/usr/bin/env python3
"""Generate 01_deploy_and_test.ipynb for the Valkey local track.

Teaching tutorial: the Strands agent, the tools, and both cache levels (as
Strands hooks) are written inline. cache_lib holds the same logic for the
Streamlit app. Run:
    python3 _build_notebook.py
"""
import json
import pathlib

cells = []


def md(text):
    cells.append({"cell_type": "markdown", "metadata": {}, "source": text.splitlines(keepends=True)})


def code(text):
    cells.append({"cell_type": "code", "metadata": {}, "execution_count": None,
                  "outputs": [], "source": text.splitlines(keepends=True)})


md("""# Cache a Strands agent with hooks, on local Valkey

This is a hands-on tutorial. By the end you will have built, in plain Python:

1. a travel agent with [Strands Agents](https://strandsagents.com/?trk=87c4c426-cddf-4799-a299-273337552ad8&sc_channel=el) and [Amazon Bedrock](https://aws.amazon.com/bedrock/?trk=87c4c426-cddf-4799-a299-273337552ad8&sc_channel=el),
2. two caches wired into the agent as [Strands hooks](https://strandsagents.com/docs/user-guide/concepts/agents/hooks/?trk=87c4c426-cddf-4799-a299-273337552ad8&sc_channel=el), backed by a local [Valkey](https://valkey.io/) with vector search,
3. proof that repeated or similar questions come back for zero tokens.

The difference from the DynamoDB version is where the cache lives: here it runs
in a Valkey container on your machine, with no
[Amazon ElastiCache](https://aws.amazon.com/elasticache/?trk=87c4c426-cddf-4799-a299-273337552ad8&sc_channel=el)
and no VPC. Only the cache is local; the embeddings and the model are real calls
to Amazon Bedrock. The two caches are both hooks on one agent, so there is no
wrapper code around it.

Valkey does vector search through its `search` module, which the
[valkey/valkey-bundle](https://hub.docker.com/r/valkey/valkey-bundle) image
ships. Plain `valkey/valkey` does not have it.

### What you need

* [Docker](https://www.docker.com/) running (or [colima](https://github.com/abiosoft/colima)). If Docker Desktop asks you to sign in with an organization, run `colima start` instead.
* AWS credentials with Bedrock access, and the models [Amazon Nova Lite](https://aws.amazon.com/ai/generative-ai/nova/?trk=87c4c426-cddf-4799-a299-273337552ad8&sc_channel=el) and [Titan Text Embeddings V2](https://docs.aws.amazon.com/bedrock/latest/userguide/titan-embedding-models.html?trk=87c4c426-cddf-4799-a299-273337552ad8&sc_channel=el) enabled in your region (default `us-east-1`).
* Optional: a [Duffel](https://duffel.com) sandbox key for the flight tool.
""")

# ---------------------------------------------------------------------------
md("""## 1. Setup

Install the dependencies and open a Bedrock client. If you see `pip` warnings
about unrelated packages, they come from a shared Python and do not affect this
demo.""")
code("""import sys
!{sys.executable} -m pip install -q -r requirements.txt""")

code('''import json
import boto3

REGION = "us-east-1"
AGENT_MODEL = "us.amazon.nova-lite-v1:0"
EMBED_MODEL = "amazon.titan-embed-text-v2:0"
PORT = 6380                                   # 6379 is often taken by a native Valkey

bedrock = boto3.client("bedrock-runtime", region_name=REGION)
print("Bedrock client ready in", REGION)''')

# ---------------------------------------------------------------------------
md("""## 2. Start Valkey with vector search

We run the `valkey/valkey-bundle` image and connect to it. The port is 6380
because a native Valkey or Redis often already sits on 6379 (and that one has no
vector search). `FT._LIST` answers only when the search module is loaded, so we
use it to wait until Valkey is ready.""")
code('''import subprocess, time
from valkey import Valkey

subprocess.run(["docker", "rm", "-f", "valkey-cache-local"], capture_output=True, text=True)
subprocess.run(["docker", "run", "-d", "--name", "valkey-cache-local",
                "-p", f"{PORT}:6379", "valkey/valkey-bundle:latest"],
               capture_output=True, text=True)

client = Valkey(host="localhost", port=PORT)
for _ in range(20):
    try:
        client.execute_command("FT._LIST")
        break
    except Exception:
        time.sleep(1.5)

print("ping:", client.ping())
print("vector search module loaded:", "search" in
      [m[b"name"].decode() for m in client.execute_command("MODULE LIST")])''')

# ---------------------------------------------------------------------------
md("""## 3. Turn text into a vector with Titan

A semantic cache finds answers by meaning, not exact text. Titan Text Embeddings
V2 gives a 1024-number vector and is multilingual (100+ languages), so a question
in another language lands close to the same question in English. That is what
makes cross-language cache hits work, with no language detection on our side.

Valkey stores vectors as raw float32 bytes, so we pack the list with `struct`.""")
code('''import struct

def embed(text):
    """Return a 1024-dim embedding for a piece of text."""
    resp = bedrock.invoke_model(
        modelId=EMBED_MODEL,
        body=json.dumps({"inputText": text, "dimensions": 1024}),
    )
    return json.loads(resp["body"].read())["embedding"]

def to_bytes(vector):
    """Pack a float list as the float32 bytes Valkey vectors expect."""
    return struct.pack(f"{len(vector)}f", *vector)

print("embedding length:", len(embed("best time to visit Japan")))''')

# ---------------------------------------------------------------------------
md("""## 4. Write a tool for the agent

A Strands tool is a Python function with the `@tool` decorator. The docstring and
type hints are what the model reads to decide when to call it.""")
code('''import urllib.parse, urllib.request
from strands import tool

def _get_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "cache-tutorial/1.0"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.load(r)

@tool
def geocode_destination(place: str) -> str:
    """Look up the coordinates and country of a destination.

    Args:
        place: A city or country name, for example 'Tokyo' or 'Japan'.
    """
    url = "https://geocoding-api.open-meteo.com/v1/search?" + urllib.parse.urlencode(
        {"name": place, "count": 1})
    results = _get_json(url).get("results")
    if not results:
        return f"No location found for '{place}'."
    r = results[0]
    return json.dumps({"name": r.get("name"), "country": r.get("country"),
                       "latitude": r.get("latitude"), "longitude": r.get("longitude")})

print(geocode_destination("Tokyo"))''')

md("""The demo agent uses four tools like this one. They already live in
`cache_lib/tools.py`, so we import that list.""")
code('''from cache_lib.tools import ALL_TOOLS
print("tools the agent can use:", [t.tool_name for t in ALL_TOOLS])''')

# ---------------------------------------------------------------------------
md("""## 5. Create the Strands agent

A Strands `Agent` needs a model provider and, optionally, a system prompt and
tools. The provider is
[Amazon Bedrock](https://aws.amazon.com/bedrock/?trk=87c4c426-cddf-4799-a299-273337552ad8&sc_channel=el)
through `BedrockModel`, pointed at Nova Lite. No cache yet.""")
code('''from strands import Agent
from strands.models import BedrockModel

SYSTEM_PROMPT = (
    "You are a travel research specialist. Ground every claim in data you "
    "retrieve with the available tools rather than prior knowledge, and resolve "
    "each tool's inputs from earlier results before calling it. If a tool returns "
    "nothing useful, do not retry it with small variations; answer with what you "
    "have and state what is missing. Be direct: at most 4 sentences, plain text, "
    "in the user's language."
)

model = BedrockModel(model_id=AGENT_MODEL, region_name=REGION)
agent = Agent(model=model, system_prompt=SYSTEM_PROMPT, tools=ALL_TOOLS)

result = agent("What is the best time of year to visit Japan and do I need a visa?")
print("\\ntokens used:", result.metrics.accumulated_usage["totalTokens"],
      "| cycles:", result.metrics.cycle_count)''')

md("""### Using a different model provider

Bedrock is just the model provider. Strands supports others, so you can swap it
without touching the agent, the tools, or the caches. Only the two lines that
build `model` change. For example, with
[OpenAI](https://strandsagents.com/latest/documentation/docs/user-guide/concepts/model-providers/openai/?trk=87c4c426-cddf-4799-a299-273337552ad8&sc_channel=el):

```python
from strands.models.openai import OpenAIModel

model = OpenAIModel(client_args={"api_key": "<key>"}, model_id="gpt-4o")
agent = Agent(model=model, system_prompt=SYSTEM_PROMPT, tools=ALL_TOOLS)
```

Strands also ships providers for
[Anthropic](https://strandsagents.com/latest/documentation/docs/user-guide/concepts/model-providers/anthropic/?trk=87c4c426-cddf-4799-a299-273337552ad8&sc_channel=el)
and [Ollama](https://strandsagents.com/latest/documentation/docs/user-guide/concepts/model-providers/ollama/?trk=87c4c426-cddf-4799-a299-273337552ad8&sc_channel=el).
The embeddings still come from Titan, which is what decides cache hits.""")

# ---------------------------------------------------------------------------
md("""## 5b. Prompt caching: what the model provider already gives you

Before we build our own caches, it is worth seeing the cache the model provider
ships, so the difference is concrete. **Prompt caching** reuses the processing of
a repeated *input prefix* (your `tools`, `system` prompt, and `messages`, in that
order). It is a model-side feature about the tokens you send, not about what the
model knows and not about your agent's logic. In Anthropic's own words: *"Prompt
caching has no effect on output token generation. The response you receive is
identical to what you would get if prompt caching were not used"*
([Anthropic docs](https://platform.claude.com/docs/en/build-with-claude/prompt-caching)).
The model still generates every answer; only the re-processing of the repeated
input is skipped.

Strands turns it on for you with one parameter:
`BedrockModel(..., cache_config=CacheConfig(strategy="auto"))`, which appends a
cache point at the end of the static system prompt on every request
([Strands docs](https://strandsagents.com/docs/user-guide/concepts/model-providers/amazon-bedrock/?trk=87c4c426-cddf-4799-a299-273337552ad8&sc_channel=el)).
Two caveats decide whether you see a hit: it needs a model that supports it
(Anthropic Claude and OpenAI GPT-5.6 support the explicit cache points Strands
uses; Amazon Nova does implicit caching only, so `cache_config` is a no-op on
Nova and the agent for this tutorial keeps running on Nova Lite), and the cached
prefix must exceed a per-model minimum (1,024 tokens for Claude Sonnet, 4,096 for
Claude Haiku). We use Claude Sonnet 4.5 here with a padded system prompt purely
to clear that minimum and make the effect visible.""")
code('''# This cell needs Bedrock access to Claude Sonnet 4.5. It is a side demo of the
# model-provider cache; the rest of the notebook runs on Nova Lite as configured.
from strands.models import CacheConfig

# a static system prompt padded past Claude Sonnet's 1,024-token minimum
CACHE_DEMO_SYSTEM = ("You are a travel research specialist. "
                     + "Provide grounded, concise, accurate answers. " * 120)

cache_model = BedrockModel(
    model_id="us.anthropic.claude-sonnet-4-5-20250929-v1:0",
    region_name=REGION,
    cache_config=CacheConfig(strategy="auto"),   # Strands adds the cache point
)
cache_demo_agent = Agent(model=cache_model, system_prompt=CACHE_DEMO_SYSTEM)

r1 = cache_demo_agent("Name one city in Japan. One word.")
u1 = r1.metrics.accumulated_usage
print("Request 1 (cold):")
print(f"  cache WRITE tokens: {u1.get('cacheWriteInputTokens')}  "
      f"cache READ tokens: {u1.get('cacheReadInputTokens')}")

r2 = cache_demo_agent("Name one city in France. One word.")
u2 = r2.metrics.accumulated_usage
print("Request 2 (same static system prompt):")
print(f"  cache WRITE tokens: {u2.get('cacheWriteInputTokens')}  "
      f"cache READ tokens: {u2.get('cacheReadInputTokens')}")
print()
print("The system prompt was READ from cache on request 2 (cheaper input), but")
print("each answer was still generated fresh. That is the ceiling of prompt")
print("caching: it discounts repeated INPUT, it never returns a stored answer.")''')

md("""That is the difference this whole notebook is about. Prompt caching made the
repeated *input* cheaper, but the model still ran and generated both answers. The
three caches we build next work at the application level and remove the work
entirely: on a hit the model does not run at all (response cache), skips
exploration cycles (reasoning cache), or skips the real API call (tool-result
cache). They stack with prompt caching; they do not replace it.""")

# ---------------------------------------------------------------------------
md("""## 6. Three caches, three Strands hooks

A [hook](https://strandsagents.com/docs/user-guide/concepts/agents/hooks/?trk=87c4c426-cddf-4799-a299-273337552ad8&sc_channel=el)
is a callback you register for a point in the agent's lifecycle. The caches live
inside the agent loop through these events, so the model never sees them: from
its point of view it just asks questions and calls tools. Each cache saves
something different, and each one fires on a different event:

| Cache | Fires on | What it saves |
|---|---|---|
| Response | `BeforeInvocationEvent` (once, before the loop) | the whole LLM run: 0 tokens, the model never starts |
| Reasoning (plan) | `BeforeInvocationEvent` (once, before the model thinks) | the model's tokens: it does not reason out which tools to call |
| Tool result | `BeforeToolCallEvent` (every time a tool is about to run) | the tool call itself: no time and no real API hit |

Note the different triggers. The response and reasoning caches act once per
question, before the loop starts. The tool-result cache acts on every single
tool call the model makes.

We write each cache as its **own** `HookProvider` and pass all three to the
agent. Strands lets several hooks subscribe to the same event and stack without
interfering. Keeping them separate is decoupling in practice, one of the
Well-Architected principles: each cache has a single responsibility and none
reaches into another's internals, so you can read, test, or remove one without
touching the others.

> For this demo we keep the three caches in separate classes so each one is easy
> to explain. In production you may prefer to combine the reasoning and
> tool-result caches into one hook, since they share the tool trajectory; that is
> also supported. Here we favour clarity.

The reasoning cache needs to know which tools ran, and the tool-result cache is
what sees them. They share that list through `invocation_state`, a per-invocation
dict Strands passes to every hook and tool, so the two classes cooperate without
being coupled.""")

# ---------------------------------------------------------------------------
md("""## 7. Cache 1: the response cache

Answers are Valkey hashes under `answer:` keys, indexed by `idx:answers`. `store`
writes the question, answer, token count and embedding. `lookup` runs a KNN
search with `FT.SEARCH` for the closest answer and turns the cosine distance into
a similarity.

The hook wraps those two. On `BeforeInvocationEvent`, a hit sets `event.cancel`
so the model never runs; on `AfterInvocationEvent`, a miss stores the new answer.

Two settings control it. **THRESHOLD** (0 to 1) is how similar a new question
must be to a stored one to count as a hit. Similarity is cosine similarity
between the two question embeddings: 1.0 is identical in meaning, 0.0 is
unrelated. At 0.85 a reworded or translated question still hits, but an unrelated
one does not. **TTL_SECONDS** is how long a stored answer lives before it expires
on its own; 86400 is one day (60 * 60 * 24).""")
code('''import time
from valkey.exceptions import ResponseError
from strands.hooks import (
    HookProvider, HookRegistry, BeforeInvocationEvent, AfterInvocationEvent,
)

THRESHOLD = 0.85          # min cosine similarity (0-1) for a cache hit; higher is stricter
TTL_SECONDS = 86400       # how long a cached answer lives, in seconds (86400 = 1 day)

def create_answer_index():
    try:
        client.execute_command(
            "FT.CREATE", "idx:answers", "ON", "HASH", "PREFIX", "1", "answer:",
            "SCHEMA", "embedding", "VECTOR", "HNSW", "6",
            "TYPE", "FLOAT32", "DIM", "1024", "DISTANCE_METRIC", "COSINE")
        return "answer index created"
    except ResponseError as e:
        if "already exists" in str(e).lower():
            return "answer index already exists"
        raise

print(create_answer_index())

class ResponseCache(HookProvider):
    """The response cache, entirely inside the agent as a Strands hook.

    Everything the cache does lives in this HookProvider. The only thing you
    call is agent(question); Strands fires check() before the loop and store()
    after it. On a hit, check() sets event.cancel and the model never runs, so
    the question text never even reaches the LLM. There is no cache function to
    call from outside the agent."""
    hit = None

    def register_hooks(self, registry: HookRegistry) -> None:
        registry.add_callback(BeforeInvocationEvent, self.check)
        registry.add_callback(AfterInvocationEvent, self.store)

    @staticmethod
    def _question_of(event):
        if not event.messages:
            return None
        texts = [b["text"] for b in event.messages[-1].get("content", []) if "text" in b]
        return " ".join(texts) if texts else None

    def _lookup(self, question):
        res = client.execute_command(
            "FT.SEARCH", "idx:answers", "*=>[KNN 1 @embedding $vec AS score]",
            "PARAMS", "2", "vec", to_bytes(embed(question)),
            "RETURN", "3", "score", "answer", "tokens", "DIALECT", "2")
        if not res or int(res[0]) == 0:
            return None
        f = res[2]
        doc = {f[i].decode(): f[i + 1] for i in range(0, len(f), 2)}
        similarity = 1.0 - float(doc["score"]) / 2.0     # cosine distance -> similarity
        if similarity < THRESHOLD:
            return None
        return {"answer": doc["answer"].decode(), "similarity": round(similarity, 4),
                "tokens_saved": int(doc["tokens"])}

    def _store(self, question, answer, tokens):
        key = "answer:" + str(int(time.time() * 1000))
        client.hset(key, mapping={"question": question, "answer": answer,
                                  "tokens": str(tokens), "embedding": to_bytes(embed(question))})
        client.expire(key, TTL_SECONDS)

    def check(self, event: BeforeInvocationEvent):
        # fires before the loop: look up the question, and on a hit cancel the
        # whole invocation so the model never runs
        self.question = self._question_of(event)
        ResponseCache.hit = None
        if not self.question:
            return
        hit = self._lookup(self.question)
        if hit:
            ResponseCache.hit = hit
            event.cancel = hit["answer"]        # model never runs; this is the answer

    def store(self, event: AfterInvocationEvent):
        # fires after a miss: persist what the agent just generated
        if ResponseCache.hit or not self.question or event.result is None:
            return
        self._store(self.question, str(event.result),
                    event.result.metrics.accumulated_usage["totalTokens"])

print("ResponseCache ready")''')

# ---------------------------------------------------------------------------
md("""## 8. Cache 2: the tool-result cache

This cache stores what each tool call returned, in plain `toolcall:` keys keyed
by a hash of the tool name and its arguments. It fires on every tool call:

* `BeforeToolCallEvent`: if this exact (tool, arguments) is in Valkey, swap the real tool for a stub that returns the stored text (`event.selected_tool`). The real API is never called.
* `AfterToolCallEvent`: store a fresh result, and record the call in the shared trajectory (in `invocation_state`) so the reasoning cache can save it.

A cache is only worth keeping if the tool was useful. A tool can return
`status = success` and still say "No location found". Caching that with the
normal TTL would replay a dead end, so a not-useful result is negative-cached for
only 5 minutes and is not added to the trajectory.""")
code('''import hashlib
from strands.hooks import BeforeToolCallEvent, AfterToolCallEvent
from strands import tool

NEGATIVE_TTL = 300        # not-useful tool results live only 5 minutes
# Per-tool TTLs by how fast the data goes stale. A flight price is volatile, so
# 5 minutes; coordinates are effectively immutable, so 30 days. This is the point
# of a tool-result cache: cache each result for exactly as long as it stays true.
TOOL_TTL = {
    "geocode_destination": 30 * 24 * 3600,   # coordinates: effectively immutable
    "climate_summary": 7 * 24 * 3600,        # historical climate: monthly refresh
    "wikipedia_summary": 24 * 3600,          # policies change without notice
    "search_flights": 300,                   # prices: volatile, minutes only
}
_NOT_USEFUL = ("no location found", "no wikipedia article found",
               "no summary available", "no flight offers found",
               "no climate data", "no data available")

class ToolResultCache(HookProvider):
    """The tool-result cache, entirely inside the agent as a Strands hook.

    Every read and write of the cache is a method here; nothing is called from
    outside the agent. serve() runs before each tool call and swaps in a stub on
    a hit, store() runs after and persists a fresh result plus the trajectory."""
    hits = 0
    executions = 0
    served = set()

    def register_hooks(self, registry: HookRegistry) -> None:
        registry.add_callback(BeforeInvocationEvent, self.reset)
        registry.add_callback(BeforeToolCallEvent, self.serve)
        registry.add_callback(AfterToolCallEvent, self.store)

    @staticmethod
    def _tool_ttl(name):
        return TOOL_TTL.get(name, 3600)

    @staticmethod
    def _is_useful(text):
        low = text.strip().lower()
        return bool(text) and not any(m in low[:120] for m in _NOT_USEFUL)

    @staticmethod
    def _tool_key(name, args):
        return "toolcall:" + hashlib.md5(f"{name}:{json.dumps(args, sort_keys=True)}".encode()).hexdigest()

    @staticmethod
    def _stub_tool(result_text):
        @tool
        def cached_lookup(place: str = "", latitude: float = 0.0, longitude: float = 0.0,
                          topic: str = "", origin: str = "", destination: str = "",
                          departure_date: str = "", cabin_class: str = "") -> str:
            """Return the cached result of an identical earlier tool call."""
            return result_text
        return cached_lookup

    def _lookup(self, name, args):
        return client.get(self._tool_key(name, args))

    def _store(self, name, args, result_text, ttl):
        client.set(self._tool_key(name, args), result_text, ex=ttl)

    def reset(self, event: BeforeInvocationEvent):
        # zero the counters at the start of each invocation so they report
        # this question only, not an accumulation across calls
        ToolResultCache.hits = 0
        ToolResultCache.executions = 0
        ToolResultCache.served = set()

    def serve(self, event: BeforeToolCallEvent):
        cached = self._lookup(event.tool_use["name"], event.tool_use["input"])
        if cached is not None:
            event.selected_tool = self._stub_tool(cached.decode())
            ToolResultCache.hits += 1
            ToolResultCache.served.add(event.tool_use.get("toolUseId"))
        else:
            ToolResultCache.executions += 1

    def store(self, event: AfterToolCallEvent):
        name, args = event.tool_use["name"], event.tool_use["input"]
        # A served hit still fires AfterToolCallEvent. Skip the write, or the TTL
        # would refresh on every hit and a volatile result (a flight price) would
        # never expire. Just record it in the trajectory.
        if event.tool_use.get("toolUseId") in ToolResultCache.served:
            # record in the trajectory only if the served result was useful, so a
            # negative-cached dead end never becomes a step in the stored plan
            served = [b["text"] for b in event.result.get("content", []) if "text" in b] \
                if isinstance(event.result, dict) else []
            if served and self._is_useful(" ".join(served)):
                event.invocation_state.setdefault("trajectory", []).append(
                    f"{name}({json.dumps(args, sort_keys=True)})")
            return
        if not isinstance(event.result, dict) or event.result.get("status") == "error":
            return
        texts = [b["text"] for b in event.result.get("content", []) if "text" in b]
        result_text = " ".join(texts)
        if not result_text:
            return
        if not self._is_useful(result_text):
            self._store(name, args, result_text, NEGATIVE_TTL)
            return
        # useful: cache with the tool's TTL and record it in the shared trajectory
        self._store(name, args, result_text, self._tool_ttl(name))
        event.invocation_state.setdefault("trajectory", []).append(
            f"{name}({json.dumps(args, sort_keys=True)})")

print("ToolResultCache ready")''')

# ---------------------------------------------------------------------------
md("""## 9. Cache 3: the reasoning cache

This cache stores the tool plan a question ended up using in its own index,
`idx:traj` over `traj:` keys, so it does not mix with the answers. It fires once
per question:

* `BeforeInvocationEvent`: find a similar past question and append its tool plan to the message, so the model calls the right tools on its first try. It only adds text; it does not touch the tool cache.
* `AfterInvocationEvent`: read the trajectory the tool-result cache collected in `invocation_state` and store it as this question's plan.

If a response-cache hit already cancelled the invocation, this hook returns
early.""")
code('''def create_traj_index():
    try:
        client.execute_command(
            "FT.CREATE", "idx:traj", "ON", "HASH", "PREFIX", "1", "traj:",
            "SCHEMA", "embedding", "VECTOR", "HNSW", "6",
            "TYPE", "FLOAT32", "DIM", "1024", "DISTANCE_METRIC", "COSINE")
        return "trajectory index created"
    except ResponseError as e:
        if "already exists" in str(e).lower():
            return "trajectory index already exists"
        raise

print(create_traj_index())

class ReasoningCache(HookProvider):
    """The reasoning (plan) cache, entirely inside the agent as a Strands hook.

    The lookup and store of the tool plan are methods here; nothing is called
    from outside the agent. inject_plan() runs before the model thinks and
    appends a matching plan, store_plan() runs after and persists the trajectory
    the tool-result cache collected."""
    plan_used = False

    def register_hooks(self, registry: HookRegistry) -> None:
        registry.add_callback(BeforeInvocationEvent, self.inject_plan)
        registry.add_callback(AfterInvocationEvent, self.store_plan)

    @staticmethod
    def _question_of(event):
        if not event.messages:
            return None
        texts = [b["text"] for b in event.messages[-1].get("content", []) if "text" in b]
        return " ".join(texts) if texts else None

    def _lookup_plan(self, question):
        res = client.execute_command(
            "FT.SEARCH", "idx:traj", "*=>[KNN 1 @embedding $vec AS score]",
            "PARAMS", "2", "vec", to_bytes(embed(question)),
            "RETURN", "2", "score", "plan", "DIALECT", "2")
        if not res or int(res[0]) == 0:
            return None
        f = res[2]
        doc = {f[i].decode(): f[i + 1] for i in range(0, len(f), 2)}
        if 1.0 - float(doc["score"]) / 2.0 < THRESHOLD:
            return None
        return doc["plan"].decode()

    def _store_plan(self, question, plan):
        key = "traj:" + hashlib.md5(question.encode()).hexdigest()
        client.hset(key, mapping={"plan": plan,
                                  "embedding": to_bytes(embed(question))})
        client.expire(key, TTL_SECONDS)

    def inject_plan(self, event: BeforeInvocationEvent):
        self.question = None
        ReasoningCache.plan_used = False
        event.invocation_state["trajectory"] = []      # fresh list the tool cache appends to
        if getattr(event, "cancel", False):            # response-cache hit already ended this
            return
        self.question = self._question_of(event)
        if not self.question:
            return
        plan = self._lookup_plan(self.question)
        if plan:
            event.messages[-1]["content"].append({"text":
                f"\\n\\n[cached plan] A similar question used these tool calls, "
                f"arguments already resolved: {plan}. Call them "
                f"in your first response, then answer."})
            ReasoningCache.plan_used = True

    def store_plan(self, event: AfterInvocationEvent):
        trajectory = event.invocation_state.get("trajectory", [])
        if not self.question or not trajectory or ReasoningCache.plan_used:
            return
        self._store_plan(self.question, ", ".join(trajectory))

print("ReasoningCache ready")''')

# ---------------------------------------------------------------------------
md("""## 9b. One agent, three hooks

We attach all three caches to one agent. `ResponseCache` is listed first so it
runs first and can cancel before the others do any work.""")
code('''cached_agent = Agent(
    model=model, system_prompt=SYSTEM_PROMPT, tools=ALL_TOOLS,
    hooks=[ResponseCache(), ToolResultCache(), ReasoningCache()],
)
print("agent ready with the three cache hooks")''')
# ---------------------------------------------------------------------------
md("""## 10. Cold start: the first question runs the agent

The cache is empty, so the agent does the full loop and the hooks store what it
produced. The helper below prints each answer with a clear label so it is easy
to see what happened.""")
code('''def show(label, result):
    """Print a result in a readable block: where it came from and the answer.

    On a hit the model never ran, so this run cost 0 tokens; we also show how
    many tokens the cached answer saved (what the original run had spent)."""
    hit = ResponseCache.hit
    print("=" * 70)
    print(f"{label}")
    if hit:
        print(f"  source       : RESPONSE CACHE HIT (similarity {hit['similarity']})")
        print(f"  tokens (now) : 0   cycles: 0   (the model never ran)")
        print(f"  tokens saved : {hit['tokens_saved']}   (what the first run had spent)")
    else:
        print(f"  source       : AGENT RAN")
        print(f"  tokens (now) : {result.metrics.accumulated_usage['totalTokens']}"
              f"   cycles: {result.metrics.cycle_count}")
    print(f"  answer       : {str(result).strip()}")
    print("=" * 70)

cold = cached_agent("What is the best time of year to visit Japan and do I need a visa?")
show("COLD  (first time, agent runs)", cold)''')

md("""## 11. Same question again: a response-cache hit for zero tokens

The response cache finds the stored answer and sets `event.cancel`, so the agent
returns it without calling the model. Tokens are zero, and the answer is the same
stored text.""")
code('''warm = cached_agent("What is the best time of year to visit Japan and do I need a visa?")
show("WARM  (same question, served from cache)", warm)''')

md("""## 12. Reworded, and in another language

A different wording still hits, because the match is on meaning. And because
Titan is multilingual, a question in another language matches the English answer
too, with no language detection on our side. Both come back for zero tokens and
return the stored answer.""")
code('''reworded = cached_agent("When should I go to Japan, and are visas needed for tourists?")
show("REWORDED  (different words, same meaning)", reworded)

other = cached_agent("¿Cuál es la mejor época para visitar Japón y necesito visa?")
show("OTHER LANGUAGE  (Spanish question, English answer stored)", other)''')

md("""Both hit at zero tokens and return the stored answer, in English, even to
the Spanish question. The embedding did the *matching*; it did not translate.
The next section fixes that.

## 12b. Answering in the question's language (cross-language rewrite)

To return the answer in the asker's language, we pass the stored answer through
one call to a cheap model (Nova Lite) and ask it to express that already-verified
answer in the question's language. We do not re-research: the facts are fixed, we
only change the language. This is what `cache_lib/rewrite.py` does for the app,
and it uses Strands
[structured output](https://strandsagents.com/docs/user-guide/concepts/agents/structured-output/?trk=87c4c426-cddf-4799-a299-273337552ad8&sc_channel=el)
so the model returns a typed `Localized(same_language, answer)`: it reports
whether a translation was needed and gives back the localized text, with no
fragile string parsing.

Below is the same Spanish hit as above, shown two ways so the difference is
clear: first WITHOUT the rewrite (the stored English answer), then WITH it (the
same answer in Spanish).""")
code('''from cache_lib.rewrite import rewrite_to_question_language

ES_QUESTION = "¿Cuál es la mejor época para visitar Japón y necesito visa?"
stored_answer = str(other).strip()   # the English answer served on the hit above

print("WITHOUT rewrite (stored answer served as-is):")
print("  ", stored_answer[:300])
print()

# one cheap call: translate only, using the cheap model and structured output
rw = rewrite_to_question_language(
    ES_QUESTION, stored_answer,
    model_id="us.amazon.nova-lite-v1:0", region=REGION)
print("WITH rewrite (option 2, cheap model):")
print(f"   rewritten={rw['rewritten']}  tokens={rw['tokens']}  (vs a full re-run)")
print("  ", rw["answer"][:300])''')

md("""The rewrite spent a few hundred tokens instead of the full generation, and
the answer now matches the question's language. The packaged `CachedTravelAgent`
in `cache_lib` wires this in automatically: on a hit it reports
`source="cache-rewrite"` and a `rewrite_tokens` count when it actually
translates, and serves a same-language hit verbatim (0 tokens) when the wording
is nearly identical (above `VERBATIM_SIMILARITY`).""")

# ---------------------------------------------------------------------------
md("""## 13. Watching the reasoning and tool-result caches

The response cache is so effective that it hides the other two: two similar
questions both become response-cache hits, so the agent never runs. To see the
reasoning and tool-result caches on their own, build an agent with just those two
hooks (no response cache). Ask about a fresh destination (the agent runs and
stores its plan and tool results), then a similar question: the reasoning cache
adds the plan so the model skips the thinking, and the tool-result cache serves
the tools so the real APIs are not called. The warm run should use fewer cycles
and fewer tokens than the cold one; the exact numbers vary because the model
drives the loop.""")
code('''# One fresh agent per question, which is how it runs in production (each
# request starts a clean agent). Reusing one agent across turns would pile the
# first conversation onto the second and inflate the warm token count.
# We attach the reasoning and tool-result caches, but not the response cache,
# so the agent actually runs and we can watch those two work.
def reasoning_agent():
    return Agent(model=model, system_prompt=SYSTEM_PROMPT,
                 tools=ALL_TOOLS, hooks=[ToolResultCache(), ReasoningCache()])

cold_r = reasoning_agent()("What is the weather like in Oslo and do I need a visa?")
print("cold: cycles", cold_r.metrics.cycle_count,
      "tokens", cold_r.metrics.accumulated_usage["totalTokens"],
      "plan_used", ReasoningCache.plan_used)

warm_r = reasoning_agent()("Tell me about the climate in Oslo and visa requirements.")
print("warm: cycles", warm_r.metrics.cycle_count,
      "tokens", warm_r.metrics.accumulated_usage["totalTokens"],
      "plan_used", ReasoningCache.plan_used)
print("tool cache hits:", ToolResultCache.hits, "(real API calls skipped)")
print("real tool executions:", ToolResultCache.executions)''')

md("""This is exactly what the Valkey and DynamoDB apps run in production: one
agent, the same lifecycle hooks, the response cache in front and the reasoning
cache inside the loop.""")

# ---------------------------------------------------------------------------
md("""## 13b. Cache 4: the plan-template cache (skip the planning loop entirely)

The reasoning cache in section 9 stored a fixed list of tool calls and appended
it as a hint, but the model still ran the loop. A **plan template** goes one step
further: it caches the *shape* of a solved question, an `intent`, the `slots`
that made it specific, and the ordered `steps` (tool calls with placeholders). On
a hit the planning loop is skipped **entirely**: the hook fills the slots for the
new question, runs the known tools directly (in parallel where they are
independent), synthesizes the answer, and sets `event.cancel`, so the model never
plans and the agent spends **0 planning tokens** and runs **0 cycles**.

Like every cache in this notebook it is a Strands
[hook](https://strandsagents.com/docs/user-guide/concepts/agents/hooks/?trk=87c4c426-cddf-4799-a299-273337552ad8&sc_channel=el),
so it fires inside the agent lifecycle, not in a cell after `agent()`:

* On a **miss**, `AfterInvocationEvent` turns the run's tool calls into a
  `PlanTemplate` with Nova Pro (question-specific values become `{slot}`
  placeholders; a value a later step takes from an earlier one becomes a
  `{tool.key}` reference) and stores it. The write path lives in the hook.
* On a **hit**, `BeforeInvocationEvent` fills the template's slots from the new
  question (one cheap `AdaptedSlots` call), runs the tools directly, synthesizes,
  and cancels the LLM.

The three meta calls (extract, adapt, synthesize) use Strands
[structured output](https://strandsagents.com/docs/user-guide/concepts/agents/structured-output/?trk=87c4c426-cddf-4799-a299-273337552ad8&sc_channel=el),
so they return typed, validated Pydantic objects instead of hand-parsed JSON.

Templates live in their own vector index, `idx:plan` over `plan:` keys. The
match uses a looser `PLAN_THRESHOLD = 0.6` (versus 0.85 for the response cache):
a plan is meant to be reused across destinations, and the destination name weighs
heavily in the embedding ("Kyoto" vs "Osaka" scores about 0.71), so a stricter
threshold would never reuse the plan. A looser threshold is safe here because the
answer is still generated fresh from live tool results every time; only the
*planning* is reused.""")

md("""### 13b.1 Setup: two more models and the typed shapes

Notebook 01's agent already runs on Nova Lite (`AGENT_MODEL`). The plan cache
adds two more model roles without touching the existing `model`: `meta_model`
(Nova Pro) extracts the template on a miss, and `cheap_model` (Nova Lite) adapts
the slots and synthesizes the answer on a hit.

`structured(...)` is one async meta call that returns a typed object: it builds a
throwaway sub-`Agent` with `callback_handler=None`, calls `invoke_async` with a
`structured_output_model`, and reads `result.structured_output`. It is awaited
because the plan-cache invocation hooks are async (the agent loop dispatches invocation
hooks on the async path).""")
code('''import uuid, asyncio
from pydantic import BaseModel, Field
from strands.models import BedrockModel

META_MODEL  = "us.amazon.nova-pro-v1:0"    # extracts the plan template (miss path)
CHEAP_MODEL = "us.amazon.nova-lite-v1:0"   # adapts slots + synthesizes (hit path)
PLAN_THRESHOLD = 0.6      # plans are reused across destinations, so match looser
                          # than the 0.85 response threshold ("Kyoto" vs "Osaka" ~0.71)

# new model roles; the existing agent `model` (Nova Lite) is left untouched
meta_model  = BedrockModel(model_id=META_MODEL,  region_name=REGION)
cheap_model = BedrockModel(model_id=CHEAP_MODEL, region_name=REGION)
TOOLS_BY_NAME = {t.tool_name: t for t in ALL_TOOLS}

class Step(BaseModel):
    """One planned tool call. args values may be literals, {slot}, or {tool.key}."""
    tool: str = Field(description="tool name, e.g. geocode_destination")
    args: dict = Field(description="arg name -> literal, {slot}, or {tool_name.key}")

class PlanTemplate(BaseModel):
    """A reusable plan: an intent, the slots to fill, and the ordered steps."""
    intent: str = Field(description="short label for the kind of task")
    slots: dict = Field(description="slot name -> value taken from THIS question")
    steps: list[Step] = Field(description="ordered tool calls with placeholders")

class AdaptedSlots(BaseModel):
    """Slots filled from a new question, or applicable=False if the plan does not fit."""
    applicable: bool = Field(description="true if this template fits the new question")
    slots: dict = Field(description="slot name -> value from the new question (empty if not applicable)")

async def structured(bedrock_model, system, prompt, out_model):
    """One meta call that returns a typed, validated object, awaited inside a hook.

    Strands structured output: pass a Pydantic model as structured_output_model
    and read result.structured_output, no JSON string parsing. Returns
    (parsed_object, tokens)."""
    a = Agent(model=bedrock_model, system_prompt=system, callback_handler=None)
    r = await a.invoke_async(prompt, structured_output_model=out_model)
    return r.structured_output, int(r.metrics.accumulated_usage["totalTokens"])

print("plan-template models + typed shapes ready")''')

md("""### 13b.2 The meta prompts and the direct plan runner

Three system prompts drive the three meta calls. `EXTRACT_SYSTEM` (Nova Pro)
turns an executed tool sequence into a template with `{slot}` and `{tool.key}`
placeholders; `ADAPT_SYSTEM` fills those slots from a new question (or declares
the plan does not fit); `SYNTH_SYSTEM` writes the final answer from the tool
results.

`run_steps_directly` runs the planned tools with no agent loop. Steps whose args
are already resolved in the same "wave" run concurrently with `asyncio.gather`;
because the tools do blocking HTTP, each is pushed to a thread with
`asyncio.to_thread`. This is the parallel independent-tools technique: the agent
loop cannot overlap tool calls like this, it issues them one reasoning cycle at a
time. `run_steps_directly` is a module-level helper but is only ever called from
inside the hook.""")
code('''EXTRACT_SYSTEM = (
    "You extract a reusable plan template from an executed tool sequence. Replace "
    "question-specific values with {slot} placeholders. For an arg taken from an "
    "earlier step's JSON output, use {tool_name.key}. Keep unchanging args as "
    "literals. For example: a geocode place becomes {destination}; a climate "
    "latitude becomes {geocode_destination.latitude} and longitude "
    "{geocode_destination.longitude}; a visa topic becomes "
    "'Visa policy of {geocode_destination.country}'. Never leave a specific city, "
    "coordinate, or country hardcoded in the steps.")

ADAPT_SYSTEM = (
    "You fill a plan template's slots from a new question. If the new question is "
    "the same KIND of task (just a different destination, date, etc.), set "
    "applicable=true and fill the slots with the new question's values. If it is a "
    "genuinely different kind of task the steps would not answer, set "
    "applicable=false and leave slots empty.")

SYNTH_SYSTEM = (
    "You are a travel research specialist. Using ONLY the tool results given, "
    "answer the question in at most 4 sentences, plain text.")

async def run_steps_directly(steps, slots):
    """Run the planned tools with no agent loop. Steps whose args are already
    resolved (no unfilled {...} placeholder) in the same 'wave' run concurrently
    via asyncio.gather; a step that depends on an earlier one waits for it."""
    derived, results = {}, []

    def resolve(args):
        out = {}
        for k, v in args.items():
            if isinstance(v, str):
                for slot, val in slots.items():
                    v = v.replace("{" + slot + "}", str(val))
                for dk, dv in derived.items():
                    v = v.replace("{" + dk + "}", str(dv))
                if k in ("latitude", "longitude"):
                    try: v = float(v)
                    except ValueError: pass
            out[k] = v
        return out

    def unresolved(args):
        return any("{" in str(v) and "}" in str(v) for v in args.values())

    pending = list(steps)
    while pending:
        wave, rest = [], []
        for st in pending:
            a = st["args"] if isinstance(st, dict) else st.args
            (rest if unresolved(resolve(a)) else wave).append(st)
        if not wave:
            wave, rest = pending, []
        async def call(st):
            st = st if isinstance(st, dict) else {"tool": st.tool, "args": st.args}
            fn = TOOLS_BY_NAME.get(st["tool"])
            if not fn:
                return None
            out = await asyncio.to_thread(fn, **resolve(st["args"]))
            return {"tool": st["tool"], "output": str(out)}
        done = await asyncio.gather(*[call(st) for st in wave])
        for res in done:
            if not res:
                continue
            results.append(res)
            if res["output"].startswith("{"):
                try:
                    for pk, pv in json.loads(res["output"]).items():
                        derived[f"{res['tool']}.{pk}"] = pv
                except json.JSONDecodeError:
                    pass
        pending = rest
    return results

print("plan-template meta prompts + direct runner ready")''')

md("""### 13b.3 The plan-template hook

`PlanTemplateCache` is a `HookProvider`, exactly like the three core caches. It
records each tool call on `BeforeToolCallEvent`, looks up and runs a template
(cancelling the LLM) on `BeforeInvocationEvent`, and extracts and stores a
template on `AfterInvocationEvent`. The invocation hooks are `async` so they can
`await` the structured meta calls and the async plan runner directly. Templates
get their own index, `idx:plan`, so they never mix with the answer or trajectory
indexes.""")
code('''def create_plan_index():
    try:
        client.execute_command(
            "FT.CREATE", "idx:plan", "ON", "HASH", "PREFIX", "1", "plan:",
            "SCHEMA", "embedding", "VECTOR", "HNSW", "6",
            "TYPE", "FLOAT32", "DIM", "1024", "DISTANCE_METRIC", "COSINE")
        return "plan index created"
    except ResponseError as e:
        if "already exists" in str(e).lower():
            return "plan index already exists"
        raise

print(create_plan_index())

def _plan_question_of(event):
    if not event.messages:
        return None
    texts = [b["text"] for b in event.messages[-1].get("content", []) if "text" in b]
    return " ".join(texts) if texts else None

class PlanTemplateCache(HookProvider):
    """The plan-template cache, entirely inside the agent as a Strands hook.

    Hit  (BeforeInvocationEvent): fill slots, run the known plan directly, cancel
          the LLM (planning loop skipped, 0 agent cycles, 0 agent tokens).
    Miss (AfterInvocationEvent): extract a PlanTemplate from the trajectory and
          store it. The write path lives in the hook. capture() records each tool
          call in invocation_state so the miss path has a trajectory to extract."""

    def __init__(self, agent_model, meta_model, cheap_model, threshold=PLAN_THRESHOLD):
        self._agent_model = agent_model
        self._meta = meta_model
        self._cheap = cheap_model
        self._threshold = threshold
        self.question = None
        self.hit = False
        self.applied = None

    def register_hooks(self, registry: HookRegistry) -> None:
        registry.add_callback(BeforeToolCallEvent, self.capture)
        registry.add_callback(BeforeInvocationEvent, self.maybe_run_plan)
        registry.add_callback(AfterInvocationEvent, self.extract_and_store)

    def capture(self, event: BeforeToolCallEvent) -> None:
        event.invocation_state.setdefault("plan_traj", []).append(
            {"tool": event.tool_use["name"], "args": dict(event.tool_use["input"])})

    def _store(self, question, payload):
        key = "plan:" + uuid.uuid4().hex
        client.hset(key, mapping={"template": json.dumps(payload),
                                  "embedding": to_bytes(embed(question))})
        client.expire(key, TTL_SECONDS)

    def _lookup(self, question):
        res = client.execute_command("FT.SEARCH", "idx:plan",
            "*=>[KNN 1 @embedding $vec AS score]",
            "PARAMS", "2", "vec", to_bytes(embed(question)),
            "RETURN", "2", "template", "score", "DIALECT", "2")
        if not res or int(res[0]) == 0:
            return None
        f = res[2]
        d = {f[i].decode(): f[i + 1] for i in range(0, len(f), 2)}
        template = d["template"].decode() if isinstance(d["template"], bytes) else d["template"]
        if 1.0 - float(d["score"]) / 2.0 < self._threshold:
            return None
        return json.loads(template)

    async def maybe_run_plan(self, event: BeforeInvocationEvent) -> None:
        # fires before the loop: on a template hit, run the plan directly and
        # cancel the invocation so the model's planning loop never runs
        self.question = _plan_question_of(event)
        self.hit = False
        self.applied = None
        event.invocation_state["plan_traj"] = []
        if not self.question:
            return
        try:
            template = await asyncio.to_thread(self._lookup, self.question)
        except Exception as exc:                         # fail open: run the agent
            print("plan lookup failed, running the agent:", exc)
            return
        if template is None:
            return
        adapted, adapt_tokens = await structured(self._cheap, ADAPT_SYSTEM,
            f"TEMPLATE: {json.dumps({k: template[k] for k in ('intent','slots','steps')})}\\n"
            f"QUESTION: {self.question}", AdaptedSlots)
        if not (adapted.applicable and adapted.slots):
            return                                       # template did not fit: agent runs
        t0 = time.time()
        results = await run_steps_directly(template["steps"], adapted.slots)
        elapsed = time.time() - t0
        summary = "\\n".join(f"[{r['tool']}]: {r['output'][:300]}" for r in results)
        synth = Agent(model=self._agent_model, system_prompt=SYNTH_SYSTEM,
                      callback_handler=None)
        sr = await synth.invoke_async(
            f"QUESTION: {self.question}\\nTOOL RESULTS:\\n{summary}")
        synth_tokens = int(sr.metrics.accumulated_usage["totalTokens"])
        self.hit = True
        self.applied = {"tools_ran": len(results), "elapsed": round(elapsed, 2),
                        "slots": adapted.slots, "cold_tokens": template.get("cold_tokens"),
                        "meta_tokens": adapt_tokens + synth_tokens}
        event.cancel = str(sr).strip()                   # the LLM planning loop never runs

    async def extract_and_store(self, event: AfterInvocationEvent) -> None:
        # fires after a miss: extract a template from the trajectory and store it
        if self.hit or not self.question:
            return
        traj = event.invocation_state.get("plan_traj", [])
        if not traj:
            return
        cold_tokens = int(event.result.metrics.accumulated_usage.get("totalTokens", 0)) \\
            if event.result is not None else 0
        template, _ = await structured(self._meta, EXTRACT_SYSTEM,
            f"QUESTION: {self.question}\\nTOOL CALLS: {json.dumps(traj)}", PlanTemplate)
        payload = template.model_dump()
        payload["cold_tokens"] = cold_tokens
        await asyncio.to_thread(self._store, self.question, payload)
        self.applied = {"stored_intent": template.intent,
                        "steps": [s.tool for s in template.steps]}

plan_cache = PlanTemplateCache(model, meta_model, cheap_model)
print("PlanTemplateCache ready")''')

md("""### 13b.4 Cold run: the miss path stores a template

We attach only the plan hook and call `agent(question)`. On this first run there
is no template, so the agent answers Kyoto normally and the hook's
`AfterInvocationEvent` extracts and stores the `PlanTemplate`. No cell does the
storing; it happens inside the hook.""")
code('''Q_PLAN = "What is the best time to visit Kyoto and do I need a visa?"

cold_plan_agent = Agent(model=model, tools=ALL_TOOLS, system_prompt=SYSTEM_PROMPT,
                        hooks=[plan_cache])
cold_plan = cold_plan_agent(Q_PLAN)
print("hit:", plan_cache.hit, "| cycles:", cold_plan.metrics.cycle_count,
      "| tokens:", cold_plan.metrics.accumulated_usage["totalTokens"])
print("stored by AfterInvocationEvent:", plan_cache.applied)''')

md("""### 13b.5 Warm run: the hit path skips the planning loop entirely

A **different** destination, same shape. Again we only call `agent(question)`.
The hook's `BeforeInvocationEvent` matches the template at `PLAN_THRESHOLD`, fills
its slots for Osaka, runs the tools directly (independent ones concurrently),
synthesizes, and cancels the LLM, so the agent runs **0 cycles** and spends **0
tokens** on planning. The answer is still generated fresh from the live tool
results.""")
code('''Q_PLAN_2 = "When should I travel to Osaka and are visas required?"

warm_plan_agent = Agent(model=model, tools=ALL_TOOLS, system_prompt=SYSTEM_PROMPT,
                        hooks=[plan_cache])
warm_plan = warm_plan_agent(Q_PLAN_2)

print("=" * 70)
if plan_cache.hit:
    a = plan_cache.applied
    print("PLAN-CACHE HIT (BeforeInvocationEvent ran the plan, cancelled the LLM)")
    print(f"  planning loop : SKIPPED (agent cycles={warm_plan.metrics.cycle_count})")
    print(f"  agent tokens  : {warm_plan.metrics.accumulated_usage.get('totalTokens', 0)}")
    print(f"  tools ran     : {a['tools_ran']} (independent ones concurrently, {a['elapsed']}s)")
    print(f"  meta tokens   : {a['meta_tokens']} (adapt + synth, not the planning loop)")
    print(f"  cold baseline : {a['cold_tokens']} tokens")
    print(f"  answer        : {str(warm_plan).strip()}")
else:
    print("plan template did not match/fit: the full agent ran,",
          warm_plan.metrics.accumulated_usage.get("totalTokens", 0), "tokens")
print("=" * 70)''')

md("""On the warm run the planning loop was skipped completely: the hook filled
the slots for a new destination, ran the known tools directly, and synthesized
the answer, all with 0 agent cycles and 0 agent tokens. The only model cost was
the two small typed meta calls (adapt + synthesize), far less than a full
planning loop. This is the fourth cache, and like the other three it fires
entirely inside the agent lifecycle.""")

# ---------------------------------------------------------------------------
md("""## 14. The visual chat app

`cache_lib` wraps the three hooks for a Streamlit app. Launch it from here; it opens
at http://localhost:8501 and talks to the same Valkey.""")
code('''import subprocess, sys, time
chat = subprocess.Popen(
    [sys.executable, "-m", "streamlit", "run", "chat_app.py", "--server.headless", "true"],
    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
)
time.sleep(6)
print("Streamlit starting at http://localhost:8501  (run chat.terminate() to stop)")''')
code('''# chat.terminate()''')

md("""## 14b. Before production: this demo does not guard personal data

This notebook does not inspect what goes into the cache. If a user types
personal data into the chat, it gets embedded and stored like any other answer,
and a later *similar* question from a different user could retrieve it. A shared
semantic cache is a data-exfiltration and poisoning surface, so it is not safe
for personal data as shipped.

The fix is a rule on the write path: before an entry is written to the cache,
run it through a check and skip or redact anything that should not be shared.
The same Strands hooks this notebook uses for caching (`AfterInvocationEvent`
for the answer, `AfterToolCallEvent` for tool results) are the natural place to
add that check, for example with [Amazon Comprehend PII
detection](https://docs.aws.amazon.com/comprehend/latest/dg/how-pii.html?trk=87c4c426-cddf-4799-a299-273337552ad8&sc_channel=el)
or [Amazon Bedrock Guardrails sensitive-information
filters](https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails-sensitive-filters.html?trk=87c4c426-cddf-4799-a299-273337552ad8&sc_channel=el).
Partition the cache per tenant (a TAG on the index) the moment answers can
depend on who is asking.

These write-path guardrail patterns, with runnable Strands examples, are covered
in these posts:

- [Validate before the agent writes to memory](https://dev.to/aws/stop-ai-agent-hallucinations-validate-before-the-agent-writes-to-memory-57om)
- [Stop RAG hallucinations poisoning your vector store](https://dev.to/aws/how-to-stop-rag-hallucinations-poisoning-your-vector-store-2l59)
- [Stop prompt injection in agents that read untrusted content](https://dev.to/aws/how-to-stop-prompt-injection-in-ai-agents-that-read-untrusted-content-2j53)""")

md("""## 15. Cleanup (optional)

Stop and remove the container when you are done.""")
code('''# subprocess.run(["docker", "rm", "-f", "valkey-cache-local"])
# print("container removed")''')

nb = {"cells": cells,
      "metadata": {"kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
                   "language_info": {"name": "python", "version": "3.11"}},
      "nbformat": 4, "nbformat_minor": 5}

out = pathlib.Path(__file__).parent / "01_deploy_and_test.ipynb"
out.write_text(json.dumps(nb, indent=1))
print("wrote", out)
