#!/usr/bin/env python3
import os
import aws_cdk as cdk
from cache_layers_dynamodb.cache_layers_dynamodb_stack import CacheLayersDynamodbStack

app = cdk.App()

CacheLayersDynamodbStack(
    app,
    "DynamoCacheStack",
    env=cdk.Environment(
        account=os.environ.get("CDK_DEFAULT_ACCOUNT"),
        region=os.environ.get("CDK_DEFAULT_REGION", "us-east-1"),
    ),
    description="DynamoDB-backed agent cache (vector + KV) — parallel to SemanticCacheStack",
)

app.synth()
