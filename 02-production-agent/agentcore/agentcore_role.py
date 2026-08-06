from aws_cdk import Stack, aws_iam as iam
from constructs import Construct


class AgentCoreRole(Construct):
    """Execution role for the AgentCore Runtime.

    Grants: Bedrock model invocation, SSM read of the /semantic-cache/*
    contract, the Duffel secret, CloudWatch logs/X-Ray telemetry, and ECR
    image pull (required by the service even for code-based deploys).
    """

    def __init__(self, scope: Construct, construct_id: str, *, duffel_secret_arn: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        stack = Stack.of(self)

        self.role = iam.Role(
            self,
            "RuntimeRole",
            assumed_by=iam.ServicePrincipal(
                "bedrock-agentcore.amazonaws.com",
                conditions={
                    "StringEquals": {"aws:SourceAccount": stack.account},
                },
            ),
        )

        self.role.add_to_policy(iam.PolicyStatement(
            actions=["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"],
            resources=[
                f"arn:aws:bedrock:*:{stack.account}:inference-profile/*",
                "arn:aws:bedrock:*::foundation-model/*",
            ],
        ))
        self.role.add_to_policy(iam.PolicyStatement(
            actions=["ssm:GetParameter", "ssm:GetParameters", "ssm:GetParametersByPath"],
            resources=[
                f"arn:aws:ssm:{stack.region}:{stack.account}:parameter/semantic-cache/*",
                f"arn:aws:ssm:{stack.region}:{stack.account}:parameter/semantic-cache",
            ],
        ))
        self.role.add_to_policy(iam.PolicyStatement(
            actions=["secretsmanager:GetSecretValue"],
            resources=[duffel_secret_arn],
        ))
        self.role.add_to_policy(iam.PolicyStatement(
            actions=[
                "logs:CreateLogGroup",
                "logs:CreateLogStream",
                "logs:PutLogEvents",
                "logs:DescribeLogGroups",
                "logs:DescribeLogStreams",
                "xray:PutTraceSegments",
                "xray:PutTelemetryRecords",
                "cloudwatch:PutMetricData",
            ],
            resources=["*"],
        ))
