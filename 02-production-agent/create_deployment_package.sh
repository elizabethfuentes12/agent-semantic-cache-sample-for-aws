#!/bin/bash

# Create deployment package for AgentCore Runtime (code-based deploy)
# https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-get-started-code-deploy.html
set -euo pipefail

cd agent_files || exit 1

rm -rf deployment_package deployment_package.zip

# Install dependencies for ARM64 architecture
uv pip install \
  --python-platform aarch64-manylinux2014 \
  --python-version 3.11 \
  --target=deployment_package \
  --only-binary=:all: \
  -r requirements.txt

# Create ZIP with dependencies
(
  cd deployment_package || exit 1
  zip -qr ../deployment_package.zip .
)

# Add source files to ZIP root
zip -q deployment_package.zip ./*.py requirements.txt

echo "Deployment package created: agent_files/deployment_package.zip"
