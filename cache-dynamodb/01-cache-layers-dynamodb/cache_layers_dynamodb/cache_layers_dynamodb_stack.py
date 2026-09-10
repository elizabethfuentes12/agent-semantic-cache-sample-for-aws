"""DynamoDB cache infrastructure stack.

Stack name: DynamoCacheStack - does not conflict with SemanticCacheStack.
SSM prefix: /dynamodb-cache/  - does not conflict with /semantic-cache/

This stack provisions the single DynamoDB table used by all three agent caching
patterns (response cache, plan templates, tool result cache).  The table is
created via AwsCustomResource because CloudFormation does not support
VectorIndexes natively.

Downstream stack 02-production-agent reads table coordinates from SSM.
"""

import aws_cdk as cdk
from aws_cdk import Stack, aws_iam as iam, aws_ssm as ssm
from constructs import Construct

from databases import Tables
from lambdas import Lambdas


class CacheLayersDynamodbStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        stk = Stack.of(self)
        account, region = stk.account, stk.region

        # ── Constructs ────────────────────────────────────────────────────────
        # Lambdas must be instantiated first so table_creator_fn can be passed
        # to Tables - the table creator Lambda carries the deps layer with
        # boto3 1.43.72 which supports VectorIndexes in CreateTable.
        fn = Lambdas(self, "Fn")
        tbl = Tables(self, "Tbl", table_creator_fn=fn.table_creator)

        # ── Wire: env vars ────────────────────────────────────────────────────
        fn.cache_inventory.add_environment("TABLE_NAME", tbl.table_name)
        fn.cache_inventory.add_environment("ENTRY_TYPE_GSI_NAME", tbl.entry_type_gsi_name)

        # ── Wire: IAM grants on the cache_inventory Lambda ────────────────────
        table_arn = f"arn:aws:dynamodb:{region}:{account}:table/{tbl.table_name}"
        fn.cache_inventory.add_to_role_policy(
            iam.PolicyStatement(
                actions=[
                    "dynamodb:Scan",
                    "dynamodb:Query",
                    "dynamodb:DeleteItem",
                    "dynamodb:BatchWriteItem",
                ],
                resources=[
                    table_arn,
                    f"{table_arn}/index/*",
                ],
            )
        )

        # ── SSM outputs - read by 02-production-agent ─────────────────────────
        ssm.StringParameter(
            self, "TableNameParam",
            parameter_name="/dynamodb-cache/table-name",
            string_value=tbl.table_name,
            description="DynamoDB agent cache table name",
        )
        ssm.StringParameter(
            self, "VectorIndexParam",
            parameter_name="/dynamodb-cache/vector-index-name",
            string_value=tbl.vector_index_name,
            description="DynamoDB vector index name for KNN cache lookups",
        )
        ssm.StringParameter(
            self, "EntryTypeGsiParam",
            parameter_name="/dynamodb-cache/entry-type-gsi-name",
            string_value=tbl.entry_type_gsi_name,
            description="DynamoDB GSI for querying items by cache pattern",
        )
        ssm.StringParameter(
            self, "CacheInventoryFnParam",
            parameter_name="/dynamodb-cache/cache-inventory-function-name",
            string_value=fn.cache_inventory.function_name,
            description="Lambda function name for cache stats/flush",
        )

        # ── CloudFormation outputs ─────────────────────────────────────────────
        cdk.CfnOutput(self, "TableName",
                      value=tbl.table_name,
                      description="DynamoDB agent cache table")
        cdk.CfnOutput(self, "VectorIndexName",
                      value=tbl.vector_index_name,
                      description="Vector index for KNN cache lookups")
        cdk.CfnOutput(self, "EntryTypeGsiName",
                      value=tbl.entry_type_gsi_name,
                      description="GSI for per-pattern queries")
        cdk.CfnOutput(self, "CacheInventoryFunctionName",
                      value=fn.cache_inventory.function_name,
                      description="Cache stats/flush Lambda")
