import aws_cdk as cdk

from semantic_cache_stack.semantic_cache_stack import SemanticCacheStack

app = cdk.App()

SemanticCacheStack(
    app,
    "SemanticCacheStack",
    description="Semantic cache for AI agents with ElastiCache for Valkey (sample)",
)

app.synth()
