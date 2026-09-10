# Stop Paying for Repeated LLM Calls: In-Memory Cache on ElastiCache for Valkey

Stop overpaying for repeated LLM (Large Language Model) inference by caching agent answers, tool results, and reasoning plans in [Amazon ElastiCache for Valkey](https://aws.amazon.com/elasticache/?trk=87c4c426-cddf-4799-a299-273337552ad8&sc_channel=el), the in-memory track of this sample. The cache sits in the hot path of every request, so the lookup cost must stay negligible: Valkey's native vector search (`FT.*`) delivers sub-millisecond KNN (k-nearest-neighbors) lookups from a node-based cluster, with an ElastiCache Serverless store for the exact-match tool cache.

This is the **Valkey variant**. The agent logic, tools, and web UI are identical to the [DynamoDB variant](../cache-dynamodb/README.md); only the cache infrastructure and the reasoning-reuse mechanism change. Pick this track when you already run inside a VPC (Virtual Private Cloud) and want the lowest-latency cache in a sustained-traffic hot path; pick the [DynamoDB track](../cache-dynamodb/README.md) for spiky traffic with no idle compute cost and no VPC. It is a "which matches your workload" choice, not a "which is better" one.

---

## Projects

| Project | Description | Stack |
|---------|-------------|-------|
| [01-cache-layers-valkey](./01-cache-layers-valkey/) | Cache infrastructure: VPC, node-based Valkey 9.0 (vector search) + ElastiCache Serverless (tool cache), two test agents, local dashboard | ![CDK](https://img.shields.io/badge/AWS_CDK-2.265.0-orange) ![Valkey](https://img.shields.io/badge/ElastiCache-Valkey_9.0-C925D1) ![Lambda](https://img.shields.io/badge/AWS-Lambda-ED7100) |
| [02-production-agent](./02-production-agent/) | Two Strands agents on AgentCore Runtime, VPC-attached for direct cache access | ![Python](https://img.shields.io/badge/Python-3.13-blue) ![Strands](https://img.shields.io/badge/Strands_Agents-latest-green) ![AgentCore](https://img.shields.io/badge/Bedrock-AgentCore-01A88D) |
| [03-production-website](./03-production-website/) | Secure real-time web chat wired to the Valkey-backed agents: AppSync Events + Cognito + CloudFront | ![AppSync](https://img.shields.io/badge/AWS-AppSync-E7157B) ![Cognito](https://img.shields.io/badge/Amazon-Cognito-DD344C) |
| [notebooks](./notebooks/) | Local test notebooks for the production and advanced agents | ![Jupyter](https://img.shields.io/badge/Jupyter-notebooks-orange) |
| [local](./local/) | No-CDK tutorial: cache a Strands agent with three hooks from a notebook against a local Valkey container, plus a Streamlit chat. Start here to learn the pattern | ![Jupyter](https://img.shields.io/badge/Jupyter-tutorial-orange) ![Streamlit](https://img.shields.io/badge/Streamlit-chat-red) |

---

## What problem does this solve?

Every LLM call costs tokens and latency. When an agent answers the same question twice, or calls the same tool with the same arguments, those tokens are wasted. This track inserts application-level caches between the user and the model:

| Cache layer | What it stores | Savings |
|-------------|----------------|---------|
| **Semantic response cache** | Full answers keyed by question embedding | Agent loop skipped entirely on a hit |
| **Tool result cache** | Tool outputs keyed by `hash(tool_name + args)` | Real API calls skipped on a hit |
| **Reasoning cache** (plan hints) | Tool trajectories for similar past questions | Fewer deliberation cycles per run |

---

## How does Valkey differ from the DynamoDB variant?

| Concern | Valkey (this folder) | DynamoDB (cache-dynamodb/) |
|---------|----------------------|----------------------------|
| VPC required | Yes, ElastiCache lives in a private subnet | No, DynamoDB is a public endpoint |
| Infrastructure | Two clusters (node-based + serverless) | One table, on-demand billing |
| Vector search | `FT.SEARCH` (RediSearch module) | `search_vectors` native API (GA 2025) |
| Exact-match cache | Valkey GET/SET | DynamoDB GetItem/PutItem |
| CDK complexity | VPC, SGs, subnet IDs, SSL config | Single Lambda-backed custom resource (cr.Provider) |
| TTL precision | Exact (EXPIRE to the second) | Eventually consistent, volatile data checked manually |
| Cold start | Requires warm container in VPC | Serverless, no warm-up needed |
| Best for | Sustained hot-path traffic, lowest latency, already in a VPC | Spiky traffic, no idle compute cost, no VPC |

---

## What is the architecture?

![AWS architecture: the browser signs in with Cognito and publishes to AppSync Events; the publish Lambda invokes the Strands agent running on Amazon Bedrock AgentCore Runtime in VPC mode, whose two-level cache reads both ElastiCache for Valkey stores in the stack 01 VPC, calls Amazon Bedrock for model and embeddings, real APIs for tools, and shares values through SSM Parameter Store](../images/architecture.png)

Editable diagrams: [architecture](../images/architecture.drawio) ·
[demo 01 flow](../images/demo01-flow.drawio) · [demo 02 flow](../images/demo02-flow.drawio) ·
[cache flow](../images/cache-flow.drawio).

### Split-store design (production pattern)

Each cache lives on the store that matches its access pattern:

| Workload | Store | Why |
|---|---|---|
| Question/trajectory embeddings (KNN) | **Node-based Valkey 9.0** | `FT.*` vector search requires node-based; memory is predictable (N × 4 KB) |
| Tool results (exact match) | **ElastiCache Serverless Valkey** | Ephemeral, TTL-heavy, unpredictable volume; serverless scales automatically, no node sizing |

---

## How do the two demos differ?

Demo 01 treats the cached answer as the **output** (the LLM never runs on a hit);
Demo 02 treats cached data as **input** (the LLM always generates fresh, guided by
cached context). That single difference drives everything else:

| | Demo 01: [`travel_agent`](./01-cache-layers-valkey/lambdas/code/travel_agent/) | Demo 02: [`reasoning_agent`](./01-cache-layers-valkey/lambdas/code/reasoning_agent/) |
|---|---|---|
| Cache level | Before the agent (query-level) | Inside the agent loop (hooks) |
| Hits when | The same question is asked again (paraphrased or cross-language) | A new question resembles a past one |
| What is saved | Up to 100% of the invocation | Deliberation cycles + tool executions (40% to 85%) |
| Prompt sensitivity | Stale-prompt entries are rewritten, then self-healed | None. Answers are always generated under the current prompt |
| Strands mechanism | Wrapper around the invocation | [`BeforeInvocationEvent.messages`](https://strandsagents.com/docs/user-guide/concepts/agents/hooks/?trk=87c4c426-cddf-4799-a299-273337552ad8&sc_channel=el) (plan hint) + `BeforeToolCallEvent.selected_tool` (tool swap) |
| Measured | 0 tokens / 127 ms on verbatim hits | 4,035 tokens saved on a warm run (58%) |

### Demo 01 flow: query-level cache (serve verbatim or rewrite)

![Demo 01 flow: question is embedded, KNN lookup in Valkey, hit returns the stored answer without running the LLM, miss runs the Strands agent and stores the answer](../images/demo01-flow.png)

**Cache modes** (`CACHE_MODE` environment variable):

| Mode | On a paraphrased hit | Savings | Use when |
|---|---|---|---|
| `verbatim` | Stored answer returned as-is | 100% of the invocation | Same-language FAQ, maximum savings |
| `rewrite` (default) | The model adapts the **verified** cached answer to the question (language, tone, current prompt rules) without re-researching | Invocation minus a small rewrite call | Multilingual users, conversational phrasing |

Identical questions (similarity 1.0) under the current prompt are always served
verbatim; the rewrite only runs when it adds value. Entries generated under an
older system prompt are rewritten once and **self-healed** (the entry is updated),
so the next hit is verbatim again.

Cross-language works: asking in Spanish against an answer cached in English
measured similarity **0.93** (Titan Text Embeddings V2 is multilingual), and
rewrite mode returns the answer in the user's language.

### Demo 02 flow: in-loop reasoning cache (LLM always generates)

![Demo 02 flow: trajectory KNN adds a cached plan hint to the message, the agent loop runs under the current prompt, exact tool calls are served from the serverless cache, results and trajectory are captured](../images/demo02-flow.png)

Two hooks, two savings:

1. **Plan hint** (reasoning savings): on a semantic match with a past question, the
   cached tool trajectory, with already-resolved arguments, is appended to the
   user message. The model issues the right tool calls in its **first** cycle
   instead of exploring.
2. **Tool cache** (execution savings): an exact repeated (tool, args) call is served
   by a stub returning the cached result; the real tool never executes.

---

## What real APIs do the agent tools call?

Demo 02's tools fetch live data (no hardcoded answers):

| Tool | API | Cache TTL (Time To Live) | Why that TTL |
|---|---|---|---|
| `geocode_destination` | [Open-Meteo Geocoding](https://open-meteo.com/) | 30 days | Coordinates are effectively immutable |
| `climate_summary` | [Open-Meteo Archive](https://open-meteo.com/) | 7 days | Historical climate updates monthly |
| `wikipedia_summary` | [Wikipedia REST](https://www.mediawiki.org/wiki/API:REST_API) | 24 hours | Policies change without notice |
| `search_flights` | [Duffel sandbox](https://duffel.com/) | **5 minutes** | Prices are volatile |

The flight tool is adapted from
[Ricardo Ceci's Strands course](https://github.com/ricardoceci/curso-strands-agentcore-2026);
its API key lives in AWS Secrets Manager (never an environment variable).

## How does the cache stay fresh when data changes (prices, policies)?

The reasoning cache stores *which tools to call* (stable) separately from *what the
tools returned* (volatile). Three mechanisms:

1. **Per-tool TTLs by volatility** (`TOOL_TTL_SECONDS` in `tools.py`); see the
   table above. After a flight price expires, a repeat query re-fetches live prices
   while the cached reasoning remains valid.
2. **Version-keyed namespaces** (`CACHE_VERSIONS`): bump a tool's version to
   invalidate all its cached results at once (upstream schema/semantics change).
3. **Stale-on-error fallback**: every result also keeps a longer-lived stale copy;
   if the fresh entry expired AND the live call fails, the last known value is
   served marked `[stale]`: availability over perfect freshness, visible to the model.

For push-based invalidation (source system announces changes), subscribe a consumer
to the source's events and `DEL` the affected namespace. Valkey pub/sub or Amazon
EventBridge both work; not implemented in this sample.

---

## How do I deploy?

Deploy in numeric order; each stack reads what it needs from SSM Parameter Store
(`/semantic-cache/*`), with no hardcoded endpoints anywhere. Prerequisites are in
the [root README](../README.md#what-are-the-prerequisites); the production stacks
additionally need Python 3.13 + [uv](https://docs.astral.sh/uv/) and Node.js 22+
with the CDK CLI on a [CDK-bootstrapped account](https://docs.aws.amazon.com/cdk/v2/guide/bootstrapping.html?trk=87c4c426-cddf-4799-a299-273337552ad8&sc_channel=el).

> ⚠️ **The flight tool needs `DUFFEL_API_KEY` exported BEFORE `cdk deploy`**
> (free sandbox key from [Duffel](https://duffel.com)). Without it,
> `search_flights` returns errors until you put the real value in the created
> Secrets Manager secret. The other three tools work without it.

```bash
# ---- Stack 01: cache infrastructure + test agents ----
cd 01-cache-layers-valkey
bash scripts/build_layer.sh                     # Lambda deps layer (ARM64 / Python 3.13)
uv venv --python 3.13 .venv && source .venv/bin/activate
uv pip install -r requirements.txt boto3
cdk bootstrap                                   # first time in the account only
cdk deploy                                      # ElastiCache takes ~15 minutes

# Test both demos against the deployed Lambdas
python3 scripts/test_cache.py --function <FunctionName output>
python3 scripts/test_reasoning_cache.py --function <ReasoningFunctionName output>

# Optional: local dashboard at http://127.0.0.1:8080
uv pip install flask
python3 local_app/server.py --stack SemanticCacheStack --region us-east-1
deactivate

# ---- Stack 02: production agent on AgentCore Runtime ----
cd ../02-production-agent
bash create_deployment_package.sh               # ARM64 ZIP (no Docker)
uv venv --python 3.13 .venv && source .venv/bin/activate
uv pip install -r requirements.txt boto3
cdk deploy
deactivate

# ---- Stack 03: production website (backend, then frontend) ----
cd ../03-production-website/backend
uv venv --python 3.13 .venv && source .venv/bin/activate
uv pip install -r requirements.txt boto3
cdk deploy
deactivate

cd ../frontend/dashboard
bash generate_config.sh                         # builds config.js from SSM
cd ..
uv venv --python 3.13 .venv && source .venv/bin/activate
uv pip install -r requirements.txt
cdk deploy SemanticCacheWebsiteStack            # outputs the CloudFront URL
```

Create a login for the website (self sign-up is disabled by design):

```bash
aws cognito-idp admin-create-user --user-pool-id <pool id> --username <email> \
  --user-attributes Name=email,Value=<email> Name=email_verified,Value=true \
  --message-action SUPPRESS
aws cognito-idp admin-set-user-password --user-pool-id <pool id> \
  --username <email> --password '<password>' --permanent
```

### What does the dashboard show?

Per-answer badges (`cache hit · sim 0.96`, `agent ran`, `plan hint`, `N tool cache
hits`), per-session token bars (consumed vs saved), and a live inventory of both
stores where the per-tool TTLs are visible side by side. **Flush caches** resets
everything for a clean cold-run demo.

---

## What savings were measured?

All numbers from real deployments of this stack (Amazon Nova Lite,
`us-east-1`); your runs will vary because cold-run exploration is model-driven.

**Demo 01** (query-level):

| Scenario | Result |
|---|---|
| Identical question repeated | `source=cache`, 0 tokens, 112 to 146 ms |
| Paraphrase, same language | hit at similarity 0.92 to 0.96, 0 tokens (verbatim) |
| Same question in Spanish vs English cache | hit at similarity **0.93**, answer rewritten to Spanish (~195 rewrite tokens vs full re-research) |

**Demo 02** (in-loop, real-API tools):

| | Cold run | Warm run (plan hint) | Saved |
|---|---|---|---|
| Event-loop cycles | 5 | 2 | **60%** |
| Total tokens | 7,000 | 2,965 | **58% (4,035 tokens)** |
| Tool executions | 3 | 0 | **100%** |
| Flight search (Duffel) | 4 cycles / 5,754 tokens | 2 cycles / 2,790 tokens | **51%** |

Across test runs the warm savings ranged from 40% to 85% of tokens and cycles;
tool-execution savings are stable (~86% to 100%).

---

## Key implementation details

- **Vector search requires node-based Valkey 8.2+**. ElastiCache Serverless does
  not support `FT.*`. This stack deploys Valkey 9.0 on `cache.t4g.small`.
- **Burstable nodes need a memory reserve for search**: the stack sets
  `reserved-memory-percent = 30` via a parameter group; without it `FT.CREATE`
  is rejected at runtime (50% on micro instances).
- The agent model defaults to Amazon Nova Lite so the sample runs in any account
  with Bedrock enabled; swap `AGENT_MODEL_ID` for a Claude model if your account
  has access.
- Cache entries are **scoped by model id** and **tagged with the system-prompt
  hash**: an answer from one model is never served for another, and stale-prompt
  answers are rewritten (not discarded) before serving.
- The cache **fails open**: if Valkey or the embedding call is unavailable, the
  agent runs normally. Availability is probed with `FT._LIST`, never assumed.
- Dual-key layout keeps answer payloads out of the HNSW (Hierarchical Navigable
  Small World) index; TTLs include jitter to avoid synchronized expirations.
- Every hit returns its `similarity`, and near-misses log
  `cache_miss_best_similarity` so you can tune the threshold from real traffic.

## What does this track cost to run?

Approximate cost with all three stacks deployed in `us-east-1`, at demo-level
traffic (a few hundred questions). Always check the official pricing pages;
these numbers drift.

| Service | What this demo uses | Approx. cost | Pricing page |
|---------|--------------------|--------------|--------------|
| ElastiCache for Valkey (node-based) | 1× `cache.t4g.small` | ~$0.032/hour (~$23/month) | [ElastiCache pricing](https://aws.amazon.com/elasticache/pricing/?trk=87c4c426-cddf-4799-a299-273337552ad8&sc_channel=el) |
| ElastiCache Serverless (Valkey) | Tool cache, ~100 MB floor | ~$6/month minimum + per-request ECPUs | [ElastiCache pricing](https://aws.amazon.com/elasticache/pricing/?trk=87c4c426-cddf-4799-a299-273337552ad8&sc_channel=el) |
| NAT Gateway | 1× (agent tools call public APIs) | ~$0.045/hour + $0.045/GB (~$33/month) | [VPC pricing](https://aws.amazon.com/vpc/pricing/?trk=87c4c426-cddf-4799-a299-273337552ad8&sc_channel=el) |
| VPC interface endpoint | 1× bedrock-runtime, 2 AZs | ~$0.02/hour (~$15/month) | [PrivateLink pricing](https://aws.amazon.com/privatelink/pricing/?trk=87c4c426-cddf-4799-a299-273337552ad8&sc_channel=el) |
| Bedrock AgentCore Runtime | Per-second CPU/memory while a session is active; idle sessions time out at 15 min | Cents at demo volume | [AgentCore pricing](https://aws.amazon.com/bedrock/agentcore/pricing/?trk=87c4c426-cddf-4799-a299-273337552ad8&sc_channel=el) |
| Amazon Bedrock (Nova Lite + Titan Embeddings V2) | Agent generations and embeddings | Nova Lite $0.06/$0.24 per 1M input/output tokens; Titan V2 $0.02/1M. Cents at demo volume | [Bedrock pricing](https://aws.amazon.com/bedrock/pricing/?trk=87c4c426-cddf-4799-a299-273337552ad8&sc_channel=el) |
| AWS Lambda | 2 test agents + 4 website Lambdas, ARM64 | Free tier covers demo volume | [Lambda pricing](https://aws.amazon.com/lambda/pricing/?trk=87c4c426-cddf-4799-a299-273337552ad8&sc_channel=el) |
| AWS AppSync Events | WebSocket connections + events | $1.00/million events; cents at demo volume | [AppSync pricing](https://aws.amazon.com/appsync/pricing/?trk=87c4c426-cddf-4799-a299-273337552ad8&sc_channel=el) |
| Amazon Cognito | User pool, a handful of users | Free tier (50k MAUs) | [Cognito pricing](https://aws.amazon.com/cognito/pricing/?trk=87c4c426-cddf-4799-a299-273337552ad8&sc_channel=el) |
| Amazon DynamoDB | Chat history, on-demand | Cents at demo volume | [DynamoDB pricing](https://aws.amazon.com/dynamodb/pricing/?trk=87c4c426-cddf-4799-a299-273337552ad8&sc_channel=el) |
| Amazon CloudFront + S3 | Dashboard hosting | Free tier covers demo volume | [CloudFront pricing](https://aws.amazon.com/cloudfront/pricing/?trk=87c4c426-cddf-4799-a299-273337552ad8&sc_channel=el) |

**Ballpark total: about $2.60/day (~$78/month) if left running**, dominated by
the three always-on pieces: NAT Gateway, the Valkey node, and the VPC endpoint.
Everything else is effectively free at demo traffic. Destroy the stacks when
you finish testing and the cost stops:

```bash
cdk destroy
```

Every resource uses `RemovalPolicy.DESTROY`, so nothing is left behind.

## Troubleshooting

| Symptom | Resolution |
|---|---|
| `FT.*` commands rejected | Confirm engine 8.2+ **node-based** and the memory-reserve parameter group is attached |
| All lookups miss | Check `SIMILARITY_THRESHOLD` (0.85 default); CloudWatch logs include the computed `similarity` and `cache_miss_best_similarity` per request |
| Answers served in the wrong language | Set `CACHE_MODE=rewrite` (default); `verbatim` returns answers exactly as first generated |
| A repeated question consumed tokens right after a deploy | Changing the system prompt marks entries stale; the first hit rewrites and self-heals, later hits are verbatim again |
| Flight tool returns an error | Set the Duffel key: `aws secretsmanager put-secret-value --secret-id <DuffelApiKey ARN> --secret-string <key>` |
| First invocation slow | Cold start + lazy index creation; subsequent calls are fast |

## FAQ

**Why not run everything on ElastiCache Serverless?**
Vector search (`FT.*`) is only available on node-based Valkey 8.2+. Serverless
hosts the exact-match tool cache, where it fits the access pattern best.

**Is the cache per user or per session?**
Global: an answer cached for one user serves every user. Partition with a tenant
TAG in the index if answers become user-specific. The dashboard's "sessions" only
group local token statistics.

**Can I use a different embedding model?**
Yes: change `EMBEDDING_MODEL_ID`, but the `FT.CREATE` schema `DIM` must match the
model's output dimensions exactly (Titan Text Embeddings V2 = 1024), and changing
models requires re-indexing existing vectors.

**How do I demo a clean cold run?**
Use the dashboard's **Flush caches** button, or invoke the agent Lambda with
`{"action": "flush"}` (what `scripts/test_reasoning_cache.py` does before its
cold run); both clear the cached entries.

---

## Contributing

Contributions are welcome! See [CONTRIBUTING](../CONTRIBUTING.md) for more information.

---

## Security

If you discover a potential security issue in this project, notify AWS/Amazon Security via the [vulnerability reporting page](http://aws.amazon.com/security/vulnerability-reporting/?trk=87c4c426-cddf-4799-a299-273337552ad8&sc_channel=el). Please do **not** create a public GitHub issue.

---

## License

This library is licensed under the MIT-0 License. See the [LICENSE](../LICENSE) file for details.
