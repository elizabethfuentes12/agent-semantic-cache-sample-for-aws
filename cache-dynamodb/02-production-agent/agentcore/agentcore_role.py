"""IAM execution role for the DynamoDB-backed AgentCore Runtime.

Differences from the Valkey version:
- DynamoDB permissions instead of VPC/EC2 network permissions
- SSM read covers both /dynamodb-cache/* (cache config) and /semantic-cache/agent-model-id
- No VPC ENI or security group permissions needed
"""

from aws_cdk import Stack, aws_iam as iam
from constructs import Construct


class AgentCoreRole(Construct):
    """Execution role for the DynamoDB-backed AgentCore Runtime."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        duffel_secret_arn: str,
        table_name: str,
        **kwargs,
    ) -> None:
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

        # Bedrock model inference (agent model + Titan embeddings)
        self.role.add_to_policy(iam.PolicyStatement(
            actions=["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"],
            resources=[
                f"arn:aws:bedrock:*:{stack.account}:inference-profile/*",
                "arn:aws:bedrock:*::foundation-model/*",
            ],
        ))

        # DynamoDB cache table access (replaces Valkey VPC access)
        table_arn = f"arn:aws:dynamodb:{stack.region}:{stack.account}:table/{table_name}"
        self.role.add_to_policy(iam.PolicyStatement(
            actions=[
                "dynamodb:GetItem",
                "dynamodb:PutItem",
                "dynamodb:UpdateItem",
                "dynamodb:DeleteItem",
                "dynamodb:Query",
                "dynamodb:Scan",
                "dynamodb:BatchWriteItem",
                "dynamodb:SearchVectors",
            ],
            resources=[
                table_arn,
                f"{table_arn}/index/*",
            ],
        ))

        # SSM: DynamoDB cache config + shared model ID
        self.role.add_to_policy(iam.PolicyStatement(
            actions=["ssm:GetParameter", "ssm:GetParameters", "ssm:GetParametersByPath"],
            resources=[
                f"arn:aws:ssm:{stack.region}:{stack.account}:parameter/dynamodb-cache/*",
                f"arn:aws:ssm:{stack.region}:{stack.account}:parameter/dynamodb-cache",
                f"arn:aws:ssm:{stack.region}:{stack.account}:parameter/semantic-cache/agent-model-id",
                f"arn:aws:ssm:{stack.region}:{stack.account}:parameter/semantic-cache/embedding-model-id",
            ],
        ))

        # Duffel API key (Secrets Manager)
        self.role.add_to_policy(iam.PolicyStatement(
            actions=["secretsmanager:GetSecretValue"],
            resources=[duffel_secret_arn],
        ))

        # Observability
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
