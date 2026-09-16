# Stop Paying for Repeated LLM Calls: DynamoDB Vector Cache

Stop overpaying for repeated LLM inference by caching agent answers, tool results, and reasoning plans in Amazon DynamoDB - the same application-level caches as the Valkey implementation (semantic response, reasoning, and tool-result), but fully serverless with no VPC, no node sizing, and no ElastiCache clusters to manage.

This is the **DynamoDB variant** of the `cache-valkey/` implementation. The agent logic, tools, and web UI are identical. Only the cache infrastructure changes.

---

## Projects

| Project | Description | Stack |
|---------|-------------|-------|
| [01-cache-layers-dynamodb](./01-cache-layers-dynamodb/) | One DynamoDB table replacing two Valkey clusters - vector index + key-value cache | ![CDK](https://img.shields.io/badge/AWS_CDK-2.265.0-orange) ![DynamoDB](https://img.shields.io/badge/DynamoDB-Vector_Search-purple) |
| [02-production-agent](./02-production-agent/) | Same two Strands agents on AgentCore Runtime, now using DynamoDB cache - no VPC attachment | ![Python](https://img.shields.io/badge/Python-3.13-blue) ![Strands](https://img.shields.io/badge/Strands_Agents-latest-green) |
| [03-production-website](./03-production-website/) | Identical chat UI wired to DynamoDB-backed agents | ![CDK](https://img.shields.io/badge/AWS_CDK-2.265.0-orange) |
| [notebooks](./notebooks/) | Local test notebooks for the DynamoDB cache patterns | ![Jupyter](https://img.shields.io/badge/Jupyter-notebooks-orange) |
| [local](./local/) | No-CDK tutorial: cache a Strands agent with three hooks from a notebook, plus a Streamlit chat. Start here to learn the pattern | ![Jupyter](https://img.shields.io/badge/Jupyter-tutorial-orange) ![Streamlit](https://img.shields.io/badge/Streamlit-chat-red) |

---

## What problem does this solve?

Every LLM call costs tokens and latency. When an agent answers the same question twice - or calls the same tool with the same arguments - those tokens are wasted. This project inserts four application-level caches between the user and the model, one per `entry_type` in the table:

| Cache layer | What it stores | Savings |
|-------------|----------------|---------|
| **Semantic response cache** | Full answers keyed by question embedding | Agent loop skipped entirely on a hit |
| **Reasoning cache** | The tool-call trajectory a past question produced | Exploration replaced by a plan hint |
| **Plan template cache** | Reusable tool-call sequences | Planning loop replaced by slot-filling |
| **Tool result cache** | Tool outputs keyed by `hash(tool_name + args)` | Real API calls skipped on a hit |

---

## How does DynamoDB differ from the Valkey implementation?

| Concern | Valkey (cache-valkey/) | DynamoDB (this folder) |
|---------|----------------------|----------------------|
| VPC required | Yes - ElastiCache lives in a private subnet | No - DynamoDB is a public endpoint |
| Infrastructure | Two clusters (node-based + serverless) | One table, on-demand billing |
| Vector search | FT.SEARCH (RediSearch module) | `search_vectors` native API (GA Aug 2026) |
| Exact-match cache | Valkey GET/SET | DynamoDB GetItem/PutItem |
| CDK complexity | VPC, SGs, subnet IDs, SSL config | Single Lambda-backed custom resource |
| TTL precision | Exact (EXPIRE to the second) | Eventually consistent - volatile data checked manually |
| Cold start | Requires warm container in VPC | Serverless, no warm-up needed |

---

## What is the architecture?

![AWS architecture of the DynamoDB track: the browser signs in with Cognito and publishes to AppSync Events; the publish Lambda invokes the Strands agent on Amazon Bedrock AgentCore Runtime with no VPC, which reads and writes one DynamoDB table for all cache entries via search_vectors and GetItem, calls Amazon Bedrock for model and embeddings, calls real public APIs for tools, and reads the table name from SSM Parameter Store](../images/architecture-dynamodb.png)

Editable diagram: [architecture-dynamodb.drawio](../images/architecture-dynamodb.drawio).

---

## How does the single-table design work?

One DynamoDB table (`agent-cache-dynamodb`) holds every entry type. Items are separated by the `entry_type` attribute, which is also declared as an `INLINE_FILTER` on the vector index so `search_vectors()` can scope KNN to one type:

```
entry_type = response      → semantic response cache (has embedding)
entry_type = plan          → plan template cache     (has embedding)
entry_type = trajectory    → reasoning cache         (has embedding)
entry_type = tool_result   → tool result cache       (no embedding)
```

Items without an `embedding` attribute are never indexed in the vector index. All operations use the same boto3 `dynamodb` client.

---

## What is `search_vectors`?

[Amazon DynamoDB vector search](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/VectorSearch.html?trk=87c4c426-cddf-4799-a299-273337552ad8&sc_channel=el) is a native DynamoDB feature ([generally available since August 2026](https://aws.amazon.com/about-aws/whats-new/2026/08/amazon-dynamodb-vector-search/?trk=87c4c426-cddf-4799-a299-273337552ad8&sc_channel=el)) that performs approximate nearest-neighbor (ANN) search on a vector attribute:

```python
response = client.search_vectors(
    TableName="agent-cache-dynamodb",
    IndexName="embedding-index",
    SearchVector=[{"N": str(v)} for v in query_embedding],  # list of N dicts
    TopK=1,
    SearchConditionExpression="entry_type = :et AND model_id = :m",
    ExpressionAttributeValues={":et": {"S": "response"}, ":m": {"S": model_id}},
)
# Score (COSINE): 0 = identical, 2 = opposite
similarity = 1.0 - (response["SearchResults"][0]["Score"] / 2.0)
```

Before designing around the vector index, read [Requirements and limitations](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/VectorSearch.Requirements.html?trk=87c4c426-cddf-4799-a299-273337552ad8&sc_channel=el) in the DynamoDB documentation.

---

## Prerequisites

- AWS CLI configured with permissions for DynamoDB, SSM, Lambda, CloudFormation, AgentCore Runtime
- [AWS CDK (Cloud Development Kit)](https://aws.amazon.com/cdk/?trk=87c4c426-cddf-4799-a299-273337552ad8&sc_channel=el) v2 installed
- Python 3.13
- Stack `01-cache-layers-dynamodb` must be deployed before `02-production-agent`

---

## How do I deploy?

```bash
# 1. Deploy cache infrastructure
cd 01-cache-layers-dynamodb
source .venv/bin/activate && pip install -r requirements.txt
cdk deploy

# 2. Build and deploy agents
cd ../02-production-agent
source .venv/bin/activate && pip install -r requirements.txt
bash create_deployment_package.sh
cdk deploy

# 3. Deploy website
cd ../03-production-website
# follow backend then frontend README
```

---

## FAQ

**Why not use Valkey for everything?**
Valkey requires a VPC, an ElastiCache cluster with node sizing, security groups, and subnet configuration. DynamoDB requires none of that - it scales automatically and bills per request.

**Can the same DynamoDB table handle vector search AND plain key-value lookups?**
Yes. Items without the `embedding` attribute are stored normally and never appear in `search_vectors` results. Both operations use the same table and the same boto3 client.

**Why does tool result TTL need a manual check?**
DynamoDB TTL deletion is eventually consistent: AWS deletes expired items ["typically within a few days after their expiration"](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/howitworks-ttl.html?trk=87c4c426-cddf-4799-a299-273337552ad8&sc_channel=el), so a read can return an item whose expiry has passed. Every read of a cached tool result compares the stored `ttl` against the clock and treats a stale entry as a miss, which matters most for the `search_flights` tool (5-minute TTL). The check is in [`local/cache_lib/caches.py`](local/cache_lib/caches.py), in the notebook's `ToolResultCache` hook and in [`02-production-agent/agent_files/dynamodb_cache.py`](02-production-agent/agent_files/dynamodb_cache.py).

**Does `search_vectors` support exact-match lookups?**
No. `search_vectors` is approximate nearest-neighbor only. Exact-match lookups (tool results) use `GetItem` directly.

**Is this production-ready or a demo?**
This is a demonstration of the caching patterns. Every CDK resource uses `RemovalPolicy.DESTROY` - `cdk destroy` leaves a clean account. Adjust retention policies before using in production.

---

## References

- [DynamoDB Vector Search](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/VectorSearch.html?trk=87c4c426-cddf-4799-a299-273337552ad8&sc_channel=el)
- [Strands Agents SDK](https://strandsagents.com/latest/?trk=87c4c426-cddf-4799-a299-273337552ad8&sc_channel=el)
- [Amazon Bedrock AgentCore Runtime](https://aws.amazon.com/bedrock/agentcore/?trk=87c4c426-cddf-4799-a299-273337552ad8&sc_channel=el)
- Budget-matched evaluation of agent memory and skill modules - arXiv:2606.15017
- Temporal-caching failure modes - arXiv:2605.20630
- Near-miss promotion (Krites pattern) - arXiv:2602.13165

---

## Contributing

Contributions are welcome! See [CONTRIBUTING](../CONTRIBUTING.md) for more information.

---

## Security

If you discover a potential security issue in this project, notify AWS/Amazon Security via the [vulnerability reporting page](http://aws.amazon.com/security/vulnerability-reporting/). Please do **not** create a public GitHub issue.

---

## License

This library is licensed under the MIT-0 License. See the [LICENSE](../LICENSE) file for details.
