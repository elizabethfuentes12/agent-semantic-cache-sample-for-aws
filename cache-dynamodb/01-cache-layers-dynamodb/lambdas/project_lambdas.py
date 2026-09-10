from aws_cdk import Duration, aws_lambda
from constructs import Construct
from layers import Layers

BASE_LAMBDA_CONFIG = dict(
    timeout=Duration.seconds(30),
    memory_size=256,
    tracing=aws_lambda.Tracing.ACTIVE,
    architecture=aws_lambda.Architecture.ARM_64,
    runtime=aws_lambda.Runtime.PYTHON_3_13,
)


class Lambdas(Construct):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        lay = Layers(self, "Lay")

        self.cache_inventory = aws_lambda.Function(
            self,
            "cache-inventory",
            description="DynamoDB cache stats and flush — invoked by AppSync cache/ namespace",
            handler="lambda_function.lambda_handler",
            code=aws_lambda.Code.from_asset("./lambdas/code/cache_inventory"),
            layers=[lay.deps],
            **BASE_LAMBDA_CONFIG,
        )

        # table_creator uses a 5-min timeout — CreateTable + waiter can take ~30s
        self.table_creator = aws_lambda.Function(
            self,
            "table-creator",
            description="Custom Resource handler: creates DynamoDB table with VectorIndexes (requires boto3 1.43.72+)",
            handler="lambda_function.lambda_handler",
            code=aws_lambda.Code.from_asset("./lambdas/code/table_creator"),
            layers=[lay.deps],
            timeout=Duration.seconds(300),
            memory_size=256,
            tracing=aws_lambda.Tracing.ACTIVE,
            architecture=aws_lambda.Architecture.ARM_64,
            runtime=aws_lambda.Runtime.PYTHON_3_13,
        )
