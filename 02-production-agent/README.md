# 02: Production Agent on Amazon Bedrock AgentCore Runtime

The stack-01 travel agent, promoted to production: a Strands Agents agent running
inside [Amazon Bedrock AgentCore Runtime](https://aws.amazon.com/bedrock/agentcore/?trk=87c4c426-cddf-4799-a299-273337552ad8&sc_channel=el)
with **direct VPC access to both Valkey cache stores**. Everything deploys with
CDK (Cloud Development Kit); all cross-stack values arrive via SSM Parameter Store.

## How does the runtime reach the private caches?

This stack uses **VPC mode** (`NetworkConfiguration: VPC`): AgentCore creates
ENIs (Elastic Network Interfaces) in the stack-01 private subnets, so the cache
hooks talk to ElastiCache directly with sub-millisecond latency: the same
SG-to-SG (security group) pattern as the stack-01 test Lambda.

**Alternative design (not implemented): data-access Lambdas.** The runtime could
stay out of the VPC (network mode `PUBLIC`) and call one Lambda per cache store
(`lambda:InvokeFunction`), with the Lambdas living in the VPC. Choose that when
multiple agents/services should share the caches behind a stable API with
per-store IAM permissions, or when you cannot attach the runtime to a VPC. The
cost is one extra network hop (tens of ms) per cache operation and a possible
double cold start: we chose direct VPC access because the cache sits in the hot
path of every request and latency is the whole point of a cache.

## What does this stack contain?

| Piece | Purpose |
|------|---------|
| `agent_files/production_agent.py` | `BedrockAgentCoreApp` entrypoint wrapping the Strands agent + reasoning cache hooks |
| `agent_files/{reasoning_cache,tools,embeddings,semantic_cache}.py` | Same cache/tool code as stack 01 (copied: the runtime is self-contained) |
| `create_deployment_package.sh` | Builds the ARM64 ZIP (code-based deploy, no Docker) |
| `agentcore/agentcore_deployment.py` | `CfnRuntime` with `VpcConfig` (subnets + SG read from SSM) |
| `agentcore/agentcore_role.py` | Execution role: Bedrock invoke, SSM read `/semantic-cache/*`, Duffel secret, CloudWatch/X-Ray |
| `production_agent_stack/` | Lean stack: wires role + deployment, exports the runtime ARN |

## SSM contract

Reads (written by stack 01): `/semantic-cache/{valkey-host,valkey-port,tool-cache-host,tool-cache-port,private-subnet-ids,agent-runtime-sg-id,duffel-secret-arn,agent-model-id,embedding-model-id}`

Writes (read by stack 03): `/semantic-cache/agent-runtime-arn`

The agent reads its configuration from SSM **at runtime** (first invocation per
container), so cache endpoints can rotate without redeploying this stack.

> ⚠️ Gotcha we hit: `get_parameters_by_path` returns max 10 parameters per page -
> use the paginator or your 11th parameter silently disappears and the cache
> fails open with no savings.

## Deploy

```bash
cd 02-production-agent
uv venv --python 3.13 .venv && source .venv/bin/activate
uv pip install -r requirements.txt boto3
bash create_deployment_package.sh     # ARM64 ZIP
cdk deploy                            # requires stack 01 deployed first
```

## Test

```bash
ARN=$(aws ssm get-parameter --name /semantic-cache/agent-runtime-arn --query "Parameter.Value" --output text)
aws bedrock-agentcore invoke-agent-runtime \
  --agent-runtime-arn "$ARN" \
  --runtime-session-id "my-session-0000000000000000000000001" \
  --payload "$(echo -n '{"prompt": "Do I need a visa for Japan as a US citizen?"}' | base64)" \
  response.json && cat response.json
```

Measured on this stack (cold vs paraphrase, different sessions): 4,043 → 2,893
tokens (`tokens_saved: 1150`), plan hint active, 3 tool cache hits, 0 real tool
executions. Sessions are isolated microVMs (15 min idle / 8 h max): the cache
lives in Valkey, so savings carry across sessions and users.
