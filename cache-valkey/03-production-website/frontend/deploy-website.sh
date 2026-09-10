#!/usr/bin/env bash
set -euo pipefail

echo "==> Building frontend..."
cd ai-agent-frontend
pnpm install
pnpm build
cd ..

echo "==> Deploying CDK stack..."
source .venv/bin/activate
cdk deploy SemanticCacheWebsiteStack --require-approval never

echo "==> Done!"
