# Stop Paying for Repeated LLM Calls: In-Memory Cache on ElastiCache for Valkey

Stop overpaying for repeated LLM inference by caching agent answers, tool results, and reasoning plans in [Amazon ElastiCache for Valkey](https://aws.amazon.com/elasticache/?trk=87c4c426-cddf-4799-a299-273337552ad8&sc_channel=el) - the in-memory track of this sample. The cache sits in the hot path of every request, so the lookup cost must stay negligible: Valkey's native vector search (`FT.*`) delivers sub-millisecond KNN lookups from a node-based cluster, with an ElastiCache Serverless store for the exact-match tool cache.

This is the **Valkey variant**. The agent logic, tools, and web UI are identical to the [DynamoDB variant](../cache-dynamodb/README.md) - only the cache infrastructure changes. Pick this track when you already run inside a VPC and want the lowest-latency cache in a sustained-traffic hot path; pick the [DynamoDB track](../cache-dynamodb/README.md) for spiky traffic with zero idle cost and no VPC. It is a "which matches your workload" choice, not a "which is better" one.

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

Every LLM call costs tokens and latency. When an agent answers the same question twice - or calls the same tool with the same arguments - those tokens are wasted. This track inserts application-level caches between the user and the model:

| Cache layer | What it stores | Savings |
|-------------|----------------|---------|
| **Semantic response cache** | Full answers keyed by question embedding | Agent loop skipped entirely on a hit |
| **Tool result cache** | Tool outputs keyed by `hash(tool_name + args)` | Real API calls skipped on a hit |
| **Reasoning cache** (plan hints) | Tool trajectories for similar past questions | Fewer deliberation cycles per run |

---

## How does Valkey differ from the DynamoDB variant?

| Concern | Valkey (this folder) | DynamoDB (cache-dynamodb/) |
|---------|----------------------|----------------------------|
| VPC required | Yes - ElastiCache lives in a private subnet | No - DynamoDB is a public endpoint |
| Infrastructure | Two clusters (node-based + serverless) | One table, on-demand billing |
| Vector search | `FT.SEARCH` (RediSearch module) | `search_vectors` native API (GA 2025) |
| Exact-match cache | Valkey GET/SET | DynamoDB GetItem/PutItem |
| CDK complexity | VPC, SGs, subnet IDs, SSL config | Single Lambda-backed custom resource (cr.Provider) |
| TTL precision | Exact (EXPIRE to the second) | Eventually consistent - volatile data checked manually |
| Cold start | Requires warm container in VPC | Serverless, no warm-up needed |
| Best for | Sustained hot-path traffic, lowest latency, already in a VPC | Spiky traffic, zero idle cost, no VPC |

---

## The two demos inside stack 01

| Demo | Description |
|------|-------------|
| [travel_agent](./01-cache-layers-valkey/lambdas/code/travel_agent/) | Query-level semantic cache: a paraphrased repeat returns the cached answer (verbatim or rewrite mode) - the agent never runs |
| [reasoning_agent](./01-cache-layers-valkey/lambdas/code/reasoning_agent/) | In-loop reasoning cache via Strands hooks: plan hints + tool-result cache, real APIs (Duffel, Wikipedia, Open-Meteo) |

---

## How do I deploy?

Deploy in numeric order; each stack reads what it needs from SSM Parameter Store (`/semantic-cache/*`). Full instructions are in each stack's README and in the [root README](../README.md).

```bash
# 1. Cache infrastructure + test agents
cd 01-cache-layers-valkey
bash scripts/build_layer.sh
uv venv --python 3.13 .venv && source .venv/bin/activate
uv pip install -r requirements.txt boto3
cdk deploy                      # ElastiCache takes ~15 minutes

# 2. Production agent on AgentCore Runtime
cd ../02-production-agent        # see its README

# 3. Production website (backend, then frontend)
cd ../03-production-website      # see its README
```

---

## Contributing

Contributions are welcome! See [CONTRIBUTING](../CONTRIBUTING.md) for more information.

---

## Security

If you discover a potential security issue in this project, notify AWS/Amazon Security via the [vulnerability reporting page](http://aws.amazon.com/security/vulnerability-reporting/?trk=87c4c426-cddf-4799-a299-273337552ad8&sc_channel=el). Please do **not** create a public GitHub issue.

---

## License

This library is licensed under the MIT-0 License. See the [LICENSE](../LICENSE) file for details.
