import os

from aws_cdk import CfnOutput, Stack, aws_iam as iam
from constructs import Construct

from app_secrets import Secrets
from cache import ServerlessToolCache, ValkeyCache
from lambdas import Lambdas
from networking import Networking

# Any Bedrock model with Converse API support works; cache entries are
# scoped per model id. Swap for a Claude model if your account has access.
AGENT_MODEL_ID = "us.amazon.nova-lite-v1:0"
EMBEDDING_MODEL_ID = "amazon.titan-embed-text-v2:0"


class SemanticCacheStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        net = Networking(self, "Net")
        # Split-store design: vectors need FT.* (node-based only); tool
        # results are exact-match key-value and go to serverless.
        cache = ValkeyCache(
            self, "Cache", vpc=net.vpc, security_group=net.cache_sg
        )
        tool_cache = ServerlessToolCache(
            self, "ToolCache", vpc=net.vpc, security_group=net.cache_sg
        )
        fns = Lambdas(
            self, "Fn", vpc=net.vpc, security_group=net.lambda_sg
        )
        secrets = Secrets(
            self, "Secrets", duffel_key=os.environ.get("DUFFEL_API_KEY")
        )
        secrets.duffel.grant_read(fns.reasoning_agent)
        fns.reasoning_agent.add_environment(
            "DUFFEL_SECRET_ARN", secrets.duffel.secret_arn
        )

        bedrock_policy = iam.PolicyStatement(
            actions=["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"],
            resources=[
                f"arn:aws:bedrock:*:{self.account}:inference-profile/*",
                "arn:aws:bedrock:*::foundation-model/*",
            ],
        )

        for fn in [fns.travel_agent, fns.reasoning_agent]:
            fn.add_environment("VALKEY_HOST", cache.endpoint_address)
            fn.add_environment("VALKEY_PORT", cache.endpoint_port)
            fn.add_environment("TOOL_CACHE_HOST", tool_cache.endpoint_address)
            fn.add_environment("TOOL_CACHE_PORT", tool_cache.endpoint_port)
            fn.add_environment("AGENT_MODEL_ID", AGENT_MODEL_ID)
            fn.add_environment("EMBEDDING_MODEL_ID", EMBEDDING_MODEL_ID)
            fn.add_environment("SIMILARITY_THRESHOLD", "0.85")
            fn.add_environment("CACHE_TTL_SECONDS", "86400")
            fn.add_to_role_policy(bedrock_policy)

        CfnOutput(self, "FunctionName", value=fns.travel_agent.function_name)
        CfnOutput(self, "ReasoningFunctionName", value=fns.reasoning_agent.function_name)
        CfnOutput(self, "CacheEndpoint", value=cache.endpoint_address)
