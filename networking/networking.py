from aws_cdk import aws_ec2 as ec2
from constructs import Construct


class Networking(Construct):
    """VPC for the agents and the cache.

    The agent tools call real public APIs (Open-Meteo, Wikipedia), so the
    Lambda subnets need outbound internet: one NAT gateway (single AZ — this
    is a sample). Bedrock still goes through a private interface endpoint,
    and the cache subnets/SG remain unreachable from outside the VPC.
    """

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.vpc = ec2.Vpc(
            self,
            "Vpc",
            max_azs=2,
            nat_gateways=1,
            subnet_configuration=[
                # The cache lives here: no internet needed, and keeping the
                # original name/CIDRs avoids replacing the running cluster.
                ec2.SubnetConfiguration(
                    name="isolated",
                    subnet_type=ec2.SubnetType.PRIVATE_ISOLATED,
                    cidr_mask=24,
                ),
                # The agent Lambdas live in "private": their tools call real
                # public APIs, so they need NAT egress.
                ec2.SubnetConfiguration(
                    name="public",
                    subnet_type=ec2.SubnetType.PUBLIC,
                    cidr_mask=24,
                ),
                ec2.SubnetConfiguration(
                    name="private",
                    subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS,
                    cidr_mask=24,
                ),
            ],
        )

        self.bedrock_endpoint = self.vpc.add_interface_endpoint(
            "BedrockRuntimeEndpoint",
            service=ec2.InterfaceVpcEndpointAwsService.BEDROCK_RUNTIME,
        )

        self.lambda_sg = ec2.SecurityGroup(
            self,
            "LambdaSg",
            vpc=self.vpc,
            description="Agent Lambdas",
            allow_all_outbound=True,
        )

        self.cache_sg = ec2.SecurityGroup(
            self,
            "CacheSg",
            vpc=self.vpc,
            description="ElastiCache for Valkey semantic cache",
            allow_all_outbound=False,
        )
        self.cache_sg.add_ingress_rule(
            peer=self.lambda_sg,
            connection=ec2.Port.tcp(6379),
            description="Valkey from the agent Lambdas only",
        )
