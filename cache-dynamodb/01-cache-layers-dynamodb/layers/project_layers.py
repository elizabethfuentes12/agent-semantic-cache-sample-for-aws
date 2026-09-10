"""Lambda layers for the DynamoDB cache stack.

The deps layer ships the latest boto3 so Lambda has access to
dynamodb:SearchVectors (requires a boto3 build that includes the
DynamoDB vector search API).

Build before deploy (ARM64 / Lambda-compatible):
    pip install boto3 -t layers/deps/python/ \\
        --platform manylinux2014_aarch64 \\
        --only-binary=:all:
"""

from aws_cdk import aws_lambda
from constructs import Construct

COMPATIBLE_RUNTIMES = [
    aws_lambda.Runtime.PYTHON_3_13,
    aws_lambda.Runtime.PYTHON_3_12,
]


class Layers(Construct):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.deps = aws_lambda.LayerVersion(
            self,
            "deps-layer",
            code=aws_lambda.Code.from_asset("./layers/deps/"),
            compatible_runtimes=COMPATIBLE_RUNTIMES,
            description="boto3 with DynamoDB vector search support",
        )
