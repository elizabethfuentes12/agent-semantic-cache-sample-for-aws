# 03 Frontend · Production Dashboard on CloudFront + S3 (Valkey track)

CDK app that hosts the production cache dashboard: a single static page served
globally through CloudFront with S3 origin and Origin Access Control (OAC).
The page authenticates against Cognito, chats with the AgentCore agent over
AppSync Events, and renders the cache-flow timeline, token bars, and the live
inventory of both Valkey stores.

## Deploy

```bash
cd 03-production-website/frontend/dashboard
bash generate_config.sh     # reads SSM + the backend stack, writes config.js

cd ..
uv venv --python 3.13 .venv && source .venv/bin/activate
uv pip install -r requirements.txt
cdk deploy SemanticCacheWebsiteStack
```

The stack output `DistributionDomainName` is your URL. `config.js` is
generated per deployment and never committed (it contains account-specific
endpoints).

## Files

| File | Purpose |
|------|---------|
| `dashboard/index.html` | The whole dashboard: login, chat, demo selector, flow timeline, token bars, cache inventory |
| `dashboard/generate_config.sh` | Builds `config.js` from the SSM contract and the backend stack |
| `dashboard/build.sh` | Copies page + config into `dist/` for the CDK asset |
| `webhosting/web_hosting.py` | CloudFront + S3 + OAC construct with SPA error responses |

## After changing the page

```bash
cd dashboard && bash build.sh && cd ..
cdk deploy SemanticCacheWebsiteStack
aws cloudfront create-invalidation --distribution-id <id> --paths "/*"
```
