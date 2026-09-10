# Strands Agents on AgentCore Runtime with DynamoDB Cache: No VPC, Serverless

Two Strands travel agents deployed on [Amazon Bedrock AgentCore Runtime](https://aws.amazon.com/bedrock/agentcore/?trk=87c4c426-cddf-4799-a299-273337552ad8&sc_channel=el) using DynamoDB as the cache backend. Identical agent logic to the Valkey variant - only the cache infrastructure changes. No VPC attachment, no ElastiCache clusters, no SSL configuration.

![Python](https://img.shields.io/badge/Python-3.13-blue)
![Strands](https://img.shields.io/badge/Strands_Agents-latest-green)
![CDK](https://img.shields.io/badge/AWS_CDK-2.265.0-orange)
![DynamoDB](https://img.shields.io/badge/DynamoDB-Vector_Search-purple)

---

## What agents are deployed?

| Agent | Runtime name | File | Caching pattern |
|-------|--------------|------|-----------------|
| Production | `DynamoCacheTravelAgent` | `production_agent.py` | Query-level response cache + in-loop reasoning hooks |
| Plan template | `DynamoPlanCacheAgent` | `plan_cache_agent.py` | Plan Template Cache (arXiv:2506.14852) |

All agents use the same travel tools: `geocode_destination`, `climate_summary`, `wikipedia_summary`, `search_flights`.

---

## How does DynamoDB caching differ from the Valkey version?

The Valkey version attaches AgentCore Runtime to a private VPC so the agent can reach ElastiCache directly. DynamoDB is a public AWS endpoint - no VPC attachment is needed. The CDK stack has no `NetworkConfiguration` block.

| | Valkey | DynamoDB |
|--|--------|---------|
| VPC attachment | Required | Not needed |
| SSL config | Yes (Valkey TLS) | Managed by AWS SDK |
| Cache client | `valkey.Valkey(host=..., ssl=True)` | `boto3.client("dynamodb")` |
| Vector search | `FT.SEARCH` (RediSearch) | `search_vectors` native API |
| SSM prefix | `/semantic-cache/` | `/dynamodb-cache/` |

---

## What is `dynamodb_cache.py`?

`dynamodb_cache.py` is the single module that replaces both `semantic_cache.py` and `reasoning_cache.py` from the Valkey implementation. It provides:

| Class | Replaces | Purpose |
|-------|----------|---------|
| `SemanticResponseCache` | `semantic_cache.SemanticCache` | Query-level cache: question → answer by cosine similarity |
| `ToolResultCache` | Serverless Valkey GET/SET | Exact-match tool result cache with manual TTL check |
| `ReasoningCacheHook` | `reasoning_cache.ReasoningCacheHook` | Strands `HookProvider` - same 4 hook events, DynamoDB storage |
| `PlanTemplateCache` | plancache:* Valkey keys | Plan template KNN lookup + store |
| `flush_all()` | `flushdb()` | Scan + batch delete all table items |

---

## What IAM permissions does the agent need?

```
dynamodb:GetItem
dynamodb:PutItem
dynamodb:UpdateItem
dynamodb:DeleteItem
dynamodb:BatchWriteItem
dynamodb:Query
dynamodb:Scan
dynamodb:SearchVectors         ← vector index queries
ssm:GetParameter               ← /dynamodb-cache/* config
ssm:GetParameters
ssm:GetParametersByPath
bedrock:InvokeModel            ← LLM inference + embeddings
bedrock:InvokeModelWithResponseStream
secretsmanager:GetSecretValue  ← Duffel API key
logs:CreateLogGroup
logs:CreateLogStream
logs:PutLogEvents
logs:DescribeLogGroups
logs:DescribeLogStreams
xray:PutTraceSegments
xray:PutTelemetryRecords
cloudwatch:PutMetricData
```

---

## SSM contract

**Reads** (written by `01-cache-layers-dynamodb`):
- `/dynamodb-cache/table-name`
- `/dynamodb-cache/vector-index-name`
- `/dynamodb-cache/entry-type-gsi-name`

**Reads** (shared with Valkey stack):
- `/semantic-cache/agent-model-id`
- `/semantic-cache/embedding-model-id`
- `/semantic-cache/duffel-secret-arn`

**Writes** (read by `03-production-website`):
- `/dynamodb-cache/agent-runtime-arn`
- `/dynamodb-cache/plan-cache-runtime-arn`

---

## How do I deploy?

```bash
cd 02-production-agent
source .venv/bin/activate
pip install -r requirements.txt

# Build ARM64 deployment package
bash create_deployment_package.sh

# Deploy (requires 01-cache-layers-dynamodb already deployed)
AWS_PROFILE=<your-profile> cdk deploy
```

Stack name: `DynamoProductionAgentStack`

---

## How do I test the deployed agents?

```bash
ARN=$(aws ssm get-parameter \
  --name /dynamodb-cache/agent-runtime-arn \
  --query "Parameter.Value" --output text)

aws bedrock-agentcore invoke-agent-runtime \
  --agent-runtime-arn "$ARN" \
  --runtime-session-id "$(uuidgen)" \
  --payload "$(echo -n '{"prompt": "Best time to visit Japan?"}' | base64)" \
  response.json && cat response.json
```

---

## FAQ

**Can I run the notebooks locally without deploying to AWS?**
Yes - open `../notebooks/` in JupyterLab or VS Code. The notebooks use `boto3.client("dynamodb")` directly. You need valid AWS credentials with DynamoDB access. No local Valkey instance required.

**What changed in agent_common.py?**
`get_clients()` (returning two Valkey clients) is replaced by `get_ddb_client()` (returning one boto3 DynamoDB client). `knn_lookup()` now calls `search_vectors()`. `store_vector()` calls `put_item()`. `ensure_vector_index()` is a no-op - the index is created at deploy time.

**Why is TTL check manual for tool results?**
DynamoDB TTL (Time To Live) deletion is eventually consistent. The `ToolResultCache.get()` method explicitly checks `int(item["ttl"]["N"]) > time.time()` so the 5-minute `search_flights` cache cannot serve stale prices.

---

## References

- [Strands Agents Hooks](https://strandsagents.com/latest/user-guide/concepts/agents/hooks/?trk=87c4c426-cddf-4799-a299-273337552ad8&sc_channel=el)
- [AgentCore Runtime](https://docs.aws.amazon.com/bedrock/latest/userguide/agentcore-runtime.html?trk=87c4c426-cddf-4799-a299-273337552ad8&sc_channel=el)
- [DynamoDB SearchVectors API](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/VectorSearch.html?trk=87c4c426-cddf-4799-a299-273337552ad8&sc_channel=el)
- Plan Template Cache - arXiv:2506.14852

---

## Contributing

Contributions are welcome! See [CONTRIBUTING](../../CONTRIBUTING.md) for more information.

---

## Security

If you discover a potential security issue in this project, notify AWS/Amazon Security via the [vulnerability reporting page](http://aws.amazon.com/security/vulnerability-reporting/). Please do **not** create a public GitHub issue.

---

## License

This library is licensed under the MIT-0 License. See the [LICENSE](../../LICENSE) file for details.
