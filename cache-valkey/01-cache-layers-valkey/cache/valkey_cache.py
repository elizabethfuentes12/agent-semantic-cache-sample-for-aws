from aws_cdk import RemovalPolicy, aws_ec2 as ec2, aws_elasticache as elasticache
from constructs import Construct

# AWS documents search availability on node-based Valkey clusters: 8.2 for vector
# search, 9.0+ for vector, full-text, tag, numeric and hybrid search. There is no
# serverless entry in that availability statement, so this cache runs node-based.
# https://docs.aws.amazon.com/AmazonElastiCache/latest/dg/search-features-limits.html
ENGINE_VERSION = "9.0"
NODE_TYPE = "cache.t4g.small"


class ValkeyCache(Construct):
    """Single-node ElastiCache for Valkey replication group with TLS.

    Cluster mode stays off so FT.SEARCH has no hash-slot co-location
    constraints. Smallest footprint for a sample: 1 shard, 0 replicas.
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

        # Search on burstable nodes requires a memory reserve: 30% on small,
        # 50% on micro. Without it FT.CREATE is rejected at runtime.
        parameter_group = elasticache.CfnParameterGroup(
            self,
            "ParameterGroup",
            cache_parameter_group_family="valkey9",
            description="Valkey 9 with memory reserve for vector search",
            properties={
                "reserved-memory-percent": "30",
                # Explicit eviction policy per AWS semantic-caching guidance;
                # all cache keys carry a TTL, LRU evicts the coldest first.
                "maxmemory-policy": "allkeys-lru",
            },
        )

        subnet_group = elasticache.CfnSubnetGroup(
            self,
            "SubnetGroup",
            description="Isolated subnets for the semantic cache",
            subnet_ids=vpc.select_subnets(
                subnet_type=ec2.SubnetType.PRIVATE_ISOLATED
            ).subnet_ids,
        )

        self.replication_group = elasticache.CfnReplicationGroup(
            self,
            "SemanticCache",
            replication_group_description="Semantic cache for AI agents (Valkey vector search)",
            engine="valkey",
            engine_version=ENGINE_VERSION,
            cache_node_type=NODE_TYPE,
            num_cache_clusters=1,
            automatic_failover_enabled=False,
            multi_az_enabled=False,
            cache_parameter_group_name=parameter_group.ref,
            cache_subnet_group_name=subnet_group.ref,
            security_group_ids=[security_group.security_group_id],
            transit_encryption_enabled=True,
            at_rest_encryption_enabled=True,
        )
        self.replication_group.apply_removal_policy(RemovalPolicy.DESTROY)

        self.endpoint_address = self.replication_group.attr_primary_end_point_address
        self.endpoint_port = self.replication_group.attr_primary_end_point_port
