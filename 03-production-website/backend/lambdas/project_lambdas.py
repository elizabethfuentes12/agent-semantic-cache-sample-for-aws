from aws_cdk import Duration
from aws_cdk import aws_lambda
from constructs import Construct

LAMBDA_CONFIG = dict(
    timeout=Duration.minutes(15),
    memory_size=256,
    runtime=aws_lambda.Runtime.PYTHON_3_13,
    architecture=aws_lambda.Architecture.ARM_64,
    tracing=aws_lambda.Tracing.ACTIVE,
)


class Lambdas(Construct):
    def __init__(self, scope, construct_id, **kwargs):
        super().__init__(scope, construct_id, **kwargs)

        self.publish = aws_lambda.Function(
            self,
            "PublishFunction",
            handler="lambda_function.lambda_handler",
            code=aws_lambda.Code.from_asset("./lambdas/code/publish/"),
            **LAMBDA_CONFIG,
        )

        self.chat_history = aws_lambda.Function(
            self,
            "ChatHistoryFunction",
            handler="lambda_function.lambda_handler",
            code=aws_lambda.Code.from_asset("./lambdas/code/chat_history/"),
            **LAMBDA_CONFIG,
        )

        self.subscribe = aws_lambda.Function(
            self,
            "SubscribeFunction",
            handler="lambda_function.lambda_handler",
            code=aws_lambda.Code.from_asset("./lambdas/code/subscribe/"),
            **LAMBDA_CONFIG,
        )

        self.cache_inventory = aws_lambda.Function(
            self,
            "CacheInventoryFunction",
            handler="lambda_function.lambda_handler",
            code=aws_lambda.Code.from_asset("./lambdas/code/cache_inventory/"),
            **LAMBDA_CONFIG,
        )

    def get_all_functions(self) -> list:
        return [self.publish, self.chat_history, self.subscribe, self.cache_inventory]
