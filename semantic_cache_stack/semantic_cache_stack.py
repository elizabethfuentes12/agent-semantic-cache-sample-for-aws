from aws_cdk import CfnOutput, Stack, aws_iam as iam
from constructs import Construct

from cache import ValkeyCache
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
        cache = ValkeyCache(
            self, "Cache", vpc=net.vpc, security_group=net.cache_sg
        )
        fns = Lambdas(
            self, "Fn", vpc=net.vpc, security_group=net.lambda_sg
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
            fn.add_environment("AGENT_MODEL_ID", AGENT_MODEL_ID)
            fn.add_environment("EMBEDDING_MODEL_ID", EMBEDDING_MODEL_ID)
            fn.add_environment("SIMILARITY_THRESHOLD", "0.85")
            fn.add_environment("CACHE_TTL_SECONDS", "86400")
            fn.add_to_role_policy(bedrock_policy)

        CfnOutput(self, "FunctionName", value=fns.travel_agent.function_name)
        CfnOutput(self, "ReasoningFunctionName", value=fns.reasoning_agent.function_name)
        CfnOutput(self, "CacheEndpoint", value=cache.endpoint_address)
