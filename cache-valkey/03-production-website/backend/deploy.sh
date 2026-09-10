#!/usr/bin/env bash
set -euo pipefail

echo "==> Deploying CDK stack..."
source .venv/bin/activate
cdk deploy --require-approval never

echo "==> Done!"
