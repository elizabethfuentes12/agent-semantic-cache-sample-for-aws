# Local track: cache a Strands agent with hooks, on DynamoDB

A no-CDK, no-SSM, no-VPC version of the DynamoDB cache demo that runs locally.
You create one DynamoDB table straight from a Jupyter notebook, cache a
[Strands](https://strandsagents.com/?trk=87c4c426-cddf-4799-a299-273337552ad8&sc_channel=el)
travel agent with three hooks, and then play with it in a Streamlit chat. It is the
same pattern as the full [`cache-dynamodb/`](../README.md) track, stripped down so
it is easy to read, run, and teach from.

The teaching point: both cache levels are **Strands hooks on one agent**. There
is no wrapper code around the agent. The caching happens inside the agent loop
through the lifecycle events Strands exposes.

## What it demonstrates

Two caches, each wired in as a hook and each saving something different:

| Cache | Hook events | Fires when | What it saves |
|---|---|---|---|
| Level 1, response cache | `BeforeInvocationEvent` (cancel), `AfterInvocationEvent` (store) | the question repeats (reworded or in another language) | the whole LLM generation. 0 tokens on a hit |
| Level 2, reasoning cache | `BeforeInvocationEvent`, `BeforeToolCallEvent`, `AfterToolCallEvent`, `AfterInvocationEvent` | a new question resembles a past one | exploration cycles and real tool/API calls |

Level 1 uses a real Strands mechanism: on a hit, the hook sets
`event.cancel` to the stored answer, so the agent returns it and the model never
runs. Level 2 does not skip the agent; it adds the tool plan a similar past
question used and serves repeated tool calls from cache.

This stacks with, and is different from, the providers' native prompt caching,
which only discounts your input prefix and still generates every response. Full
comparison in the [top-level README](../../README.md).

### Cross-language rewrite (answers in the user's language)

Titan Text Embeddings V2 is multilingual, so a question asked in Spanish can hit
an answer that was cached in English (measured similarity ~0.87). The embedding
does the *matching*; it does not translate the stored text. Without a rewrite the
hit would return the English answer to a Spanish question.

`cache_lib/rewrite.py` fixes only the language of the answer on such a hit, using
one call to a cheap model (Nova Lite) with Strands
[structured output](https://strandsagents.com/docs/user-guide/concepts/agents/structured-output/?trk=87c4c426-cddf-4799-a299-273337552ad8&sc_channel=el):
the model returns a typed `Localized(same_language, answer)`, translating only
when the languages differ and reporting `same_language=true` otherwise. It fails
open: any error returns the cached answer unchanged.

Two `CacheConfig` fields control it:

| Field | Default | Meaning |
|---|---|---|
| `rewrite_on_hit` | `True` | run the rewrite-check on a response-cache hit. Set `False` for verbatim-only (0 tokens, original language). |
| `rewrite_model_id` | Nova Lite | the cheap model used for the translation. The answer is already verified, so this is translation, not research. |

`VERBATIM_SIMILARITY` (0.985, in `agent.py`) is the shortcut: a near-identical hit
is almost certainly the same question in the same language, so it is served
verbatim at **0 tokens** with no rewrite-check. A reworded same-language hit below
that threshold runs the cheap check (a few hundred tokens) and is served in the
same language. A cross-language hit is translated and reported as
`source="cache-rewrite"`. The result carries `rewrite_tokens` so the UI can show
the real cost instead of a flat "0 tokens".

## DynamoDB vs Valkey: which local track?

This repo ships the same demo on two cache backends. Both `local/` tracks run the
identical agent, tools, hooks, and Streamlit UI. Only the cache store changes.

| | DynamoDB (`cache-dynamodb/local`) | Valkey (`cache-valkey/local`) |
|---|---|---|
| What runs locally | Nothing. Talks to real DynamoDB in your account | A Docker container (`valkey/valkey-bundle`) |
| Vector search | Native DynamoDB `search_vectors` (needs boto3 >= 1.43.72) | Valkey `FT.*` from the `search` module (HNSW) |
| Storage model | Serverless, disk-backed, pay-per-request | In-memory, node/process-backed |
| Latency on a warm hit | Low (tens of ms over the network) | Lowest (in-memory, sub-ms server-side) |
| Idle cost | About zero (on-demand) | The node or container must stay running |
| Prerequisite friction | AWS credentials only | Docker or colima running |
| TTL semantics | Eventually consistent (verified on read) | Precise (`EXPIRE`) |
| Production counterpart | One table, no VPC | Node-based Valkey in a VPC |

**Pick DynamoDB when** you want zero infrastructure to run, traffic is spiky or
low, you are already serverless, and tens of milliseconds on a hit is fine.

**Pick Valkey when** you have sustained hot-path traffic and want the lowest
latency, you already run Valkey or Redis, or you want precise TTLs and pub-sub for
invalidation, and you can keep a node running.

Rule of thumb: serverless and spiky goes to DynamoDB; hot-path and
latency-critical goes to Valkey. For local development this DynamoDB track is the
lower-friction start (no Docker); the Valkey track mirrors a production
ElastiCache deployment.

## Files

```
local/
├── cache_lib/            # the implementation, one file per concern
│   ├── config.py         # CacheConfig dataclass, the only thing you configure
│   ├── table.py          # create/delete the DynamoDB table + vector index
│   ├── embeddings.py     # Titan Text Embeddings V2 (1024-dim)
│   ├── tools.py          # 4 travel tools on real public APIs
│   ├── caches.py         # ResponseCache + ToolResultCache + ReasoningCache (3 hooks)
│   ├── rewrite.py        # cross-language rewrite on a hit (cheap model, structured output)
│   ├── agent.py          # CachedTravelAgent: one agent, the three hooks
│   └── inventory.py      # count items per kind / flush the table
├── 01_deploy_and_test.ipynb # tutorial 1: build the agent and the three cache hooks inline
├── chat_app.py           # the visual Streamlit chat
├── requirements.txt
├── smoke_test.py         # offline check of the pure-Python helpers (no AWS)
└── _build_notebook.py    # regenerates 01_deploy_and_test.ipynb (dev helper)
```

## Prerequisites

| Requirement | Details |
|---|---|
| AWS credentials | `aws configure`, with DynamoDB and Bedrock permissions |
| Bedrock model access | Amazon Nova Lite and Titan Text Embeddings V2 enabled in your region (default `us-east-1`), see the [model access console](https://docs.aws.amazon.com/bedrock/latest/userguide/model-access.html?trk=87c4c426-cddf-4799-a299-273337552ad8&sc_channel=el) |
| Python 3.11+ | |
| boto3 >= 1.43.72 | Required for DynamoDB vector search. It is pinned in `requirements.txt` |
| Duffel key (optional) | Free sandbox key from [duffel.com](https://duffel.com) for the flight tool. The other three tools need no key |

## Quick start

```bash
cd cache-dynamodb/local
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

If you plan to run the notebook, register this venv as a dedicated Jupyter kernel
so you install into it (and not a shared global Python that would throw
dependency-conflict warnings from unrelated packages):

```bash
pip install ipykernel
python -m ipykernel install --user --name semantic-cache-local \
  --display-name "Python (semantic-cache-local)"
```

Then pick "Python (semantic-cache-local)" as the kernel in Jupyter.

### 1. Follow the tutorial (notebook)

```bash
jupyter notebook 01_deploy_and_test.ipynb
```

Run the cells top to bottom. They build everything inline so you can read it:
the `embed` function, a Strands `@tool`, the `Agent`, the DynamoDB table with its
vector index, then the two cache hooks. The demo then shows a cold run, a warm
level-1 hit (0 tokens, the model never runs), reworded and other-language hits,
and the level-2 reasoning cache serving tools from cache.

### 2. Play with it (chat)

```bash
streamlit run chat_app.py
```

Ask a question, then ask it again (or reworded, or in another language) and watch
the tokens drop to zero. Each answer shows a badge, the tokens used versus saved,
and an expandable cache-flow timeline. The sidebar has the live table inventory
and a Flush button for a clean cold run. If you change the region or table name,
change them in the sidebar so the app and the notebook point at the same table.

### 3. The plan-template cache

The third hook, the **plan-template cache**, is how this notebook implements the
reasoning cache. On a cold run it extracts the solved question's tool plan into a
reusable template (intent + slots + steps); on a similar warm question it fills
the slots, runs the known tools directly, and cancels the model's planning loop,
so a hit costs zero agent planning tokens. The template extraction uses Amazon
Nova Pro, so you need Bedrock access to it too.

## Use it from your own code

The packaged `cache_lib` runs one Strands agent with the three cache hooks attached:

```python
from cache_lib import CacheConfig, create_table, CachedTravelAgent

cfg = CacheConfig(region="us-east-1")
create_table(cfg)                       # one-time

agent = CachedTravelAgent(cfg)          # cache_mode="both" by default
r1 = agent.ask("Best time to visit Japan and do I need a visa?")  # cold, source="agent"
r2 = agent.ask("Best time to visit Japan and do I need a visa?")  # warm, source="cache", 0 tokens
print(r2["source"], r2["tokens_saved"], r2["similarity"])
```

`ask()` returns a dict with `answer`, `source` (`cache` or `agent`),
`similarity`, `tokens_saved`, `cycles`, `usage`, `plan_hint_used`,
`tool_cache_hits`, `tool_executions`, and a `flow` timeline.

`cache_mode` can be `"both"` (default), `"response-cache"` (level 1 only), or
`"reasoning-cache"` (level 2 only), which is handy for isolating what each layer
does.

## How the table is built

One `create_table(cfg)` call creates a single DynamoDB table that holds all three
cache patterns, distinguished by a `kind` attribute (`answer`, `trajectory`,
`tool_result`):

- a vector index `embedding-index` (1024-dim, COSINE) for KNN lookups, with `kind` as an inline filter so a search is scoped to one pattern (answers, or plans),
- TTL on the `ttl` attribute so entries expire on their own.

Items with no `embedding` attribute (cached tool results) are stored normally and
never appear in vector search. Counts and flush use a scan filtered by `kind`
rather than a secondary index.

`cache_lib` and the notebook build the same schema, so the Streamlit app and the
notebook share one table. `create_table` guards against a stale table: if a table
with this name exists but lacks the `kind` filter (an older schema), it returns a
clear message telling you to delete and recreate it, instead of failing later
with a cryptic error.

## Model provider

Bedrock is the model provider here, through `BedrockModel`. Strands supports
others, so you can swap it without touching the tools or the hooks: only the two
lines that build the model change. See
[OpenAI](https://strandsagents.com/latest/documentation/docs/user-guide/concepts/model-providers/openai/?trk=87c4c426-cddf-4799-a299-273337552ad8&sc_channel=el),
[Anthropic](https://strandsagents.com/latest/documentation/docs/user-guide/concepts/model-providers/anthropic/?trk=87c4c426-cddf-4799-a299-273337552ad8&sc_channel=el),
and [Ollama](https://strandsagents.com/latest/documentation/docs/user-guide/concepts/model-providers/ollama/?trk=87c4c426-cddf-4799-a299-273337552ad8&sc_channel=el).
The embeddings still come from Titan, which is what decides cache hits, so the
model provider and the embedding provider are independent choices.

## Cost

At demo traffic this is effectively free: DynamoDB on-demand costs cents for a few
hundred items, and Bedrock Nova Lite plus Titan V2 are cents for the generations
and embeddings. Delete the table (last notebook cell, or `delete_table(cfg)`) when
you are done.

## Not production-ready

This is a demo. A shared semantic cache is a data-exfiltration and poisoning
surface: nothing here inspects what gets written. Before production, validate
before writing to the cache, guard against prompt injection in tool outputs,
detect PII at the cache boundary, and partition per tenant. See the
[top-level README](../../README.md#is-this-cache-safe-for-personal-data-read-before-production)
for links and techniques.
