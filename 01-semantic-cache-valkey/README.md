# 01 - Semantic Cache Infrastructure (ElastiCache for Valkey)

The foundation stack: VPC, both Valkey cache stores, the Duffel secret, two
test agents on AWS Lambda, and the local dashboard. Deploy this first; stacks
02 and 03 read everything they need from SSM Parameter Store.

## Architecture

![Stack 01 architecture: two Lambda agents in private subnets query ElastiCache for Valkey (vector search) and ElastiCache Serverless (tool cache) in isolated subnets, reach Bedrock through a VPC endpoint, and export the cross-stack contract to SSM Parameter Store](./images/diagram.png)

Editable source: [images/diagram.drawio](./images/diagram.drawio)

## What gets deployed

| Resource | Purpose |
|----------|---------|
| VPC (isolated + private subnets, 1 NAT) | Cache stays isolated; agent subnets get API egress |
| ElastiCache for Valkey 9.0, node-based `cache.t4g.small` | Vector search (`FT.*`) for semantic lookups. Includes the memory-reserve parameter group that burstable nodes need |
| ElastiCache Serverless (Valkey) | Exact-match tool-result cache with per-tool TTLs |
| Bedrock runtime VPC endpoint | Private path to Titan Embeddings and the agent model |
| Lambda `travel_agent` | Demo 01: query-level semantic response cache (verbatim and rewrite modes) |
| Lambda `reasoning_agent` | Demo 02: in-loop reasoning cache via Strands hooks, tools call real APIs |
| Secrets Manager secret | Duffel sandbox API key for the flight tool |
| SSM parameters `/semantic-cache/*` | The cross-stack contract (endpoints, subnets, security group, model ids) |

## Deploy

```bash
cd 01-semantic-cache-valkey
bash scripts/build_layer.sh          # Lambda deps layer (ARM64 / Python 3.13)
uv venv --python 3.13 .venv && source .venv/bin/activate
uv pip install -r requirements.txt
cdk bootstrap                        # first time in the account only
cdk deploy                           # ElastiCache takes about 15 minutes
```

> ⚠️ **Required for the flight tool: `DUFFEL_API_KEY`.** Export it BEFORE
> `cdk deploy` (free sandbox key from [duffel.com](https://duffel.com)). If you
> deploy without it, the secret is created with a `REPLACE_ME` placeholder and
> `search_flights` returns errors until you set the real value:
> `aws secretsmanager put-secret-value --secret-id <DuffelApiKey ARN> --secret-string <key>`

## Test the two demos

```bash
# Demo 01: first phrasing misses, the paraphrase hits the cache
python3 scripts/test_cache.py --function <FunctionName output>

# Demo 02: cold run explores, warm paraphrase gets plan hint + tool cache
python3 scripts/test_reasoning_cache.py --function <ReasoningFunctionName output>
```

## Local dashboard

```bash
uv pip install flask boto3
python3 local_app/server.py --stack SemanticCacheStack --region us-east-1
# open http://127.0.0.1:8080
```

Chat with both demos, watch the per-session token bars, and inspect the live
inventory of both stores (see [local_app/README.md](./local_app/README.md)).

## SSM parameters exported

`valkey-host`, `valkey-port`, `tool-cache-host`, `tool-cache-port`, `vpc-id`,
`private-subnet-ids`, `agent-runtime-sg-id`, `duffel-secret-arn`,
`agent-model-id`, `embedding-model-id`, `reasoning-function-name`. All under
the `/semantic-cache/` prefix. Stack 02 attaches the AgentCore Runtime to the
exported security group; stack 03 proxies its cache-inventory panel through
the exported function name.

## Cleanup

```bash
cdk destroy
```

Every resource uses `RemovalPolicy.DESTROY`. Destroy stacks 03 and 02 first
if they are deployed, since they depend on this stack's parameters.
