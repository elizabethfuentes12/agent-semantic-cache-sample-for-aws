from aws_cdk import aws_ec2 as ec2
from constructs import Construct


class Networking(Construct):
    """VPC with isolated subnets only (no NAT) and a Bedrock interface endpoint.

    The Lambda and the cache live in isolated subnets; Bedrock is reached
    privately through the interface endpoint, so the stack needs no NAT
    gateway and has no public path to the cache.
    """

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.vpc = ec2.Vpc(
            self,
            "Vpc",
            max_azs=2,
            nat_gateways=0,
            subnet_configuration=[
                ec2.SubnetConfiguration(
                    name="isolated",
                    subnet_type=ec2.SubnetType.PRIVATE_ISOLATED,
                    cidr_mask=24,
                )
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
            description="Travel agent Lambda",
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
            description="Valkey from the agent Lambda only",
        )
