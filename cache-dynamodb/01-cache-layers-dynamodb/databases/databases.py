"""DynamoDB agent cache table with native vector index.

CloudFormation does not support VectorIndexes in AWS::DynamoDB::Table. This
construct uses a real Lambda-backed Custom Resource (cr.Provider) so the
Lambda carries the deps layer with boto3 ≥ 1.43.72 - the minimum version that
supports VectorIndexes in CreateTable.

One table handles all three cache patterns:
  response     - semantic response cache          (has embedding)
  plan         - plan template cache (reasoning)  (has embedding)
  tool_result  - tool result exact-match cache    (no embedding)

Items without an embedding attribute are stored normally and never appear in
search_vectors results.

Sources:
  https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/VectorSearch.html?trk=87c4c426-cddf-4799-a299-273337552ad8&sc_channel=el
  https://docs.aws.amazon.com/boto3/latest/reference/services/dynamodb/client/search_vectors.html?trk=87c4c426-cddf-4799-a299-273337552ad8&sc_channel=el
"""

import aws_cdk as cdk
from aws_cdk import aws_iam as iam, custom_resources as cr
from constructs import Construct

TABLE_NAME = "agent-cache-dynamodb"
VECTOR_INDEX_NAME = "embedding-index"
ENTRY_TYPE_GSI_NAME = "entry-type-index"


class Tables(Construct):
    def __init__(self, scope: Construct, construct_id: str,
                 table_creator_fn, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.table_name = TABLE_NAME
        self.vector_index_name = VECTOR_INDEX_NAME
        self.entry_type_gsi_name = ENTRY_TYPE_GSI_NAME

        # Grant the Lambda permission to manage the table
        table_creator_fn.add_to_role_policy(
            iam.PolicyStatement(
                actions=[
                    "dynamodb:CreateTable",
                    "dynamodb:DeleteTable",
                    "dynamodb:DescribeTable",
                    "dynamodb:UpdateTimeToLive",
                ],
                resources=["*"],
            )
        )

        # cr.Provider routes CloudFormation lifecycle events (Create/Update/Delete)
        # to table_creator_fn, which uses boto3 1.43.72 from the deps layer to
        # call CreateTable with VectorIndexes.
        provider = cr.Provider(
            self,
            "TableCreatorProvider",
            on_event_handler=table_creator_fn,
        )

        self._table_resource = cdk.CustomResource(
            self,
            "AgentCacheTable",
            service_token=provider.service_token,
            removal_policy=cdk.RemovalPolicy.DESTROY,
        )
