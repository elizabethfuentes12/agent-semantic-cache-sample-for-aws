from aws_cdk import aws_lambda
from constructs import Construct

COMPATIBLE_RUNTIMES = [aws_lambda.Runtime.PYTHON_3_13]


class Layers(Construct):
    """Third-party dependencies for the agent Lambda (strands-agents, valkey).

    Built into layers/deps/python/ by scripts/build_layer.sh before deploy.
    """

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.deps = aws_lambda.LayerVersion(
            self,
            "deps-layer",
            code=aws_lambda.Code.from_asset("./layers/deps/"),
            compatible_runtimes=COMPATIBLE_RUNTIMES,
            description="strands-agents + valkey client",
        )
