# local_app

Local dashboard for the sample: chat with both deployed agents and see the
caching working visually.

## Run

```bash
uv pip install flask boto3
AWS_PROFILE=<profile> python3 local_app/server.py \
    --stack SemanticCacheStack --region us-east-1
# open http://127.0.0.1:8080
```

The server resolves both Lambda names from the CloudFormation stack outputs
and proxies invocations; nothing talks to Valkey directly from your machine
(the caches are VPC-only — inventory comes from the Lambda's `cache_stats`
action).

## What it shows

- **Chat panel** — pick demo 01 (query-level) or demo 02 (in-loop), ask
  questions; each answer carries badges: `cache hit · sim 0.96`, `agent ran`,
  `plan hint`, `N tool cache hits`, cycles, tokens, latency.
- **Session tokens** — stat tiles (consumed / saved / questions) and one bar
  per question: blue = tokens consumed (agent ran), green = tokens saved
  (cache hit). Sessions are in-memory; "New session" starts a fresh count.
- **Cache contents** — live inventory of both stores: semantic responses and
  reasoning trajectories (node-based, vector search) and tool results
  (serverless) with their TTLs — the per-tool freshness policy is visible
  here (geocode ~30 d, climate ~7 d, Wikipedia ~24 h).
- **Flush caches** — wipes both stores for a clean cold-run demo.
