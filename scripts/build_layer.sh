#!/usr/bin/env bash
# Build the Lambda dependencies layer for ARM64 / Python 3.13.
# Run from the repo root before `cdk deploy`.
set -euo pipefail

LAYER_DIR="layers/deps/python"
rm -rf "$LAYER_DIR"
mkdir -p "$LAYER_DIR"

uv pip install \
  --target "$LAYER_DIR" \
  --python-platform aarch64-manylinux2014 \
  --python-version 3.13 \
  --only-binary=:all: \
  strands-agents valkey

echo "Layer built at $LAYER_DIR"
