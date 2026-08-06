# 03 — Production Website (AppSync Events + Cognito)

Secure, real-time web chat for the semantic-cache travel agent. Two CDK apps:
`backend/` (AppSync Events API, router Lambda, Cognito, DynamoDB chat history)
and `frontend/` (React app on S3 + CloudFront). Based on the AppSync
Event–Lambda primitive pattern.

## Architecture

```
Browser ──auth──> Cognito User Pool + Identity Pool
Browser ──WebSocket──> AppSync Events API
   messages/  namespace ──EVENT──> publish Lambda ──invoke_agent_runtime──> AgentCore (stack 02)
   response/  namespace <──stream── publish Lambda (SSE chunks republished)
   chat/      namespace ──REQ/RESP──> chat history Lambda ──> DynamoDB
```

Security: no anonymous access — Cognito User Pool auth on the AppSync
namespaces, self-sign-up disabled (create users with `admin-create-user`),
scoped IAM per Lambda, S3 media bucket with expiring lifecycle.

## SSM contract

Reads: `/semantic-cache/agent-runtime-arn` (written by stack 02 — the frontend
pins it in `VITE_AGENT_LIST`).
Writes: `/semantic-cache/appsync/{http_endpoint,realtime_endpoint,api_key}`,
`/semantic-cache/bucket/media_sessions`, `/semantic-cache/table/chat_messages`.

## Deploy (order matters: stacks 01 and 02 first)

```bash
# Backend
cd 03-production-website/backend
uv venv --python 3.13 .venv && source .venv/bin/activate
uv pip install -r requirements.txt boto3
cdk deploy

# Frontend: fill .env from the backend outputs + SSM, then
cd ../frontend/ai-agent-frontend
cp .env.example .env          # fill in the values (see below)
pnpm install && pnpm build
cd .. && uv venv --python 3.13 .venv && source .venv/bin/activate
uv pip install -r requirements.txt
cdk deploy SemanticCacheWebsiteStack
```

`.env` values come from: Cognito pool/client/identity-pool ids (backend stack
resources), the AppSync endpoint (`/semantic-cache/appsync/http_endpoint` + `/event`),
the media bucket, and the agent ARN (`/semantic-cache/agent-runtime-arn`).

## Create a user (self-sign-up is disabled by design)

```bash
aws cognito-idp admin-create-user --user-pool-id <pool> --username <email> \
  --user-attributes Name=email,Value=<email> Name=email_verified,Value=true \
  --message-action SUPPRESS
aws cognito-idp admin-set-user-password --user-pool-id <pool> \
  --username <email> --password '<password>' --permanent
```

Then open the CloudFront URL from the frontend stack output and sign in.
