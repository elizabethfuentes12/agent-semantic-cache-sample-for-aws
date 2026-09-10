from aws_cdk import RemovalPolicy, aws_ec2 as ec2, aws_elasticache as elasticache
from constructs import Construct


class ServerlessToolCache(Construct):
    """ElastiCache Serverless (Valkey) for exact-match tool-result caching.

    Split-store design: this cache handles the ephemeral, TTL-heavy,
    unpredictable-volume workload (tool results). Vector search stays on the
    node-based cluster because serverless does not support FT.* commands.
    Serverless scales capacity automatically and bills per GB-hour + request,
    so an idle sample costs near the 100 MB floor.
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        vpc: ec2.IVpc,
        security_group: ec2.ISecurityGroup,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.cache = elasticache.CfnServerlessCache(
            self,
            "ToolCache",
            serverless_cache_name="agent-tool-cache",
            engine="valkey",
            description="Exact-match tool result cache for AI agents",
            security_group_ids=[security_group.security_group_id],
            subnet_ids=vpc.select_subnets(
                subnet_type=ec2.SubnetType.PRIVATE_ISOLATED
            ).subnet_ids,
        )
        self.cache.apply_removal_policy(RemovalPolicy.DESTROY)

        self.endpoint_address = self.cache.attr_endpoint_address
        self.endpoint_port = self.cache.attr_endpoint_port
