from aws_cdk import Duration, aws_ec2 as ec2, aws_lambda
from constructs import Construct

from layers import Layers

BASE_LAMBDA_CONFIG = dict(
    timeout=Duration.seconds(120),
    memory_size=1024,
    tracing=aws_lambda.Tracing.ACTIVE,
    architecture=aws_lambda.Architecture.ARM_64,
    runtime=aws_lambda.Runtime.PYTHON_3_13,
)


class Lambdas(Construct):
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

        lay = Layers(self, "Lay")

        self.travel_agent = aws_lambda.Function(
            self,
            "travel_agent",
            description="Strands travel agent with Valkey semantic cache",
            handler="lambda_function.lambda_handler",
            code=aws_lambda.Code.from_asset("./lambdas/code/travel_agent"),
            layers=[lay.deps],
            vpc=vpc,
            vpc_subnets=ec2.SubnetSelection(
                subnet_type=ec2.SubnetType.PRIVATE_ISOLATED
            ),
            security_groups=[security_group],
            **BASE_LAMBDA_CONFIG,
        )
