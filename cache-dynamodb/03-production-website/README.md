# DynamoDB Agent Chat UI: Same Web App, Serverless Cache Backend

Identical chat interface to `cache-valkey/03-production-website/` - AppSync Events, Cognito, CloudFront, S3 - wired to the DynamoDB-backed agent ARNs instead of the Valkey-backed ones.

![CDK](https://img.shields.io/badge/AWS_CDK-2.265.0-orange)

---

## What changed vs the Valkey website?

| Item | Valkey | DynamoDB |
|------|--------|---------|
| Stack names | `SemanticCacheWebBackendStack` / `SemanticCacheWebsiteStack` | `DynamoCacheWebBackendStack` / `DynamoCacheWebsiteStack` |
| Agent ARN SSM prefix | `/semantic-cache/agent-runtime-arn` | `/dynamodb-cache/agent-runtime-arn` |
| Cache inventory Lambda | Stack 01 Valkey Lambda | Stack 01 DynamoDB Lambda |
| Frontend code | Identical | Identical |
| Backend Lambda code | Identical | Identical |

---

## SSM contract

**Reads** (written by `02-production-agent`):
- `/dynamodb-cache/agent-runtime-arn`
- `/dynamodb-cache/plan-cache-runtime-arn`
- `/dynamodb-cache/cache-inventory-function-name`

---

## How do I deploy?

Deploy `01-cache-layers-dynamodb` and `02-production-agent` first, then:

```bash
# Backend
cd 03-production-website/backend
source .venv/bin/activate && pip install -r requirements.txt
AWS_PROFILE=<your-profile> cdk deploy  # DynamoCacheWebBackendStack

# Frontend (production dashboard): config comes from SSM automatically
cd ../frontend/dashboard
bash generate_config.sh                # reads SSM + backend stack, writes config.js
cd ..
source .venv/bin/activate && pip install -r requirements.txt
AWS_PROFILE=<your-profile> cdk deploy DynamoCacheWebsiteStack
```

---

## Contributing

Contributions are welcome! See [CONTRIBUTING](../../CONTRIBUTING.md) for more information.

---

## Security

If you discover a potential security issue in this project, notify AWS/Amazon Security via the [vulnerability reporting page](http://aws.amazon.com/security/vulnerability-reporting/). Please do **not** create a public GitHub issue.

---

## License

This library is licensed under the MIT-0 License. See the [LICENSE](../../LICENSE) file for details.
