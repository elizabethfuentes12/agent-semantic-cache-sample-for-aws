import aws_cdk as cdk
import aws_cdk.assertions as assertions

from appsync_event_lambda_primitive.appsync_event_lambda_primitive_stack import (
    AppsyncEventLambdaPrimitiveStack,
)
from config import CHAT_MESSAGES_TABLE_PARAM_NAME


def _make_stack():
    """Synthesize the full stack without Cognito for template assertions."""
    app = cdk.App()
    stack = AppsyncEventLambdaPrimitiveStack(app, "TestStack")
    return stack, assertions.Template.from_stack(stack)


# ---------------------------------------------------------------------------
# Task 10.1 — DynamoDB table with correct key schema, billing mode, and GSI
# ---------------------------------------------------------------------------
class TestDynamoDBTable:
    """Validates: Requirement 1.1, 1.2 — DynamoDB table schema and GSI correctness."""

    def test_dynamodb_table_exists(self):
        _, template = _make_stack()
        template.resource_count_is("AWS::DynamoDB::Table", 1)

    def test_table_has_correct_partition_key(self):
        _, template = _make_stack()
        template.has_resource_properties("AWS::DynamoDB::Table", {
            "KeySchema": assertions.Match.array_with([
                assertions.Match.object_like({
                    "AttributeName": "PK",
                    "KeyType": "HASH",
                }),
            ]),
        })

    def test_table_has_correct_sort_key(self):
        _, template = _make_stack()
        template.has_resource_properties("AWS::DynamoDB::Table", {
            "KeySchema": assertions.Match.array_with([
                assertions.Match.object_like({
                    "AttributeName": "SK",
                    "KeyType": "RANGE",
                }),
            ]),
        })

    def test_table_pk_attribute_is_string_type(self):
        _, template = _make_stack()
        template.has_resource_properties("AWS::DynamoDB::Table", {
            "AttributeDefinitions": assertions.Match.array_with([
                assertions.Match.object_like({
                    "AttributeName": "PK",
                    "AttributeType": "S",
                }),
            ]),
        })

    def test_table_sk_attribute_is_string_type(self):
        _, template = _make_stack()
        template.has_resource_properties("AWS::DynamoDB::Table", {
            "AttributeDefinitions": assertions.Match.array_with([
                assertions.Match.object_like({
                    "AttributeName": "SK",
                    "AttributeType": "S",
                }),
            ]),
        })

    def test_table_billing_mode_is_pay_per_request(self):
        _, template = _make_stack()
        template.has_resource_properties("AWS::DynamoDB::Table", {
            "BillingMode": "PAY_PER_REQUEST",
        })

    def test_table_has_ttl_attribute(self):
        _, template = _make_stack()
        template.has_resource_properties("AWS::DynamoDB::Table", {
            "TimeToLiveSpecification": {
                "AttributeName": "ttl",
                "Enabled": True,
            },
        })

    def test_table_has_destroy_removal_policy(self):
        _, template = _make_stack()
        template.has_resource("AWS::DynamoDB::Table", {
            "UpdateReplacePolicy": "Delete",
            "DeletionPolicy": "Delete",
        })

    def test_table_has_gsi1(self):
        _, template = _make_stack()
        template.has_resource_properties("AWS::DynamoDB::Table", {
            "GlobalSecondaryIndexes": assertions.Match.array_with([
                assertions.Match.object_like({
                    "IndexName": "GSI1",
                }),
            ]),
        })

    def test_gsi1_has_correct_partition_key(self):
        _, template = _make_stack()
        template.has_resource_properties("AWS::DynamoDB::Table", {
            "GlobalSecondaryIndexes": assertions.Match.array_with([
                assertions.Match.object_like({
                    "IndexName": "GSI1",
                    "KeySchema": assertions.Match.array_with([
                        assertions.Match.object_like({
                            "AttributeName": "GSI1PK",
                            "KeyType": "HASH",
                        }),
                    ]),
                }),
            ]),
        })

    def test_gsi1_has_correct_sort_key(self):
        _, template = _make_stack()
        template.has_resource_properties("AWS::DynamoDB::Table", {
            "GlobalSecondaryIndexes": assertions.Match.array_with([
                assertions.Match.object_like({
                    "IndexName": "GSI1",
                    "KeySchema": assertions.Match.array_with([
                        assertions.Match.object_like({
                            "AttributeName": "GSI1SK",
                            "KeyType": "RANGE",
                        }),
                    ]),
                }),
            ]),
        })

    def test_gsi1pk_attribute_is_string_type(self):
        _, template = _make_stack()
        template.has_resource_properties("AWS::DynamoDB::Table", {
            "AttributeDefinitions": assertions.Match.array_with([
                assertions.Match.object_like({
                    "AttributeName": "GSI1PK",
                    "AttributeType": "S",
                }),
            ]),
        })

    def test_gsi1sk_attribute_is_string_type(self):
        _, template = _make_stack()
        template.has_resource_properties("AWS::DynamoDB::Table", {
            "AttributeDefinitions": assertions.Match.array_with([
                assertions.Match.object_like({
                    "AttributeName": "GSI1SK",
                    "AttributeType": "S",
                }),
            ]),
        })


# ---------------------------------------------------------------------------
# Task 10.2 — Chat history Lambda with correct handler and runtime
# ---------------------------------------------------------------------------
class TestChatHistoryLambda:
    """Validates: Requirement 6.1 — Chat history Lambda function configuration."""

    def test_chat_history_lambda_exists_with_correct_handler(self):
        _, template = _make_stack()
        template.has_resource_properties("AWS::Lambda::Function", {
            "Handler": "lambda_function.lambda_handler",
            "Code": assertions.Match.object_like({
                "S3Bucket": assertions.Match.any_value(),
            }),
        })

    def test_chat_history_lambda_runtime_python_313(self):
        _, template = _make_stack()
        template.has_resource_properties("AWS::Lambda::Function", {
            "Runtime": "python3.13",
        })

    def test_chat_history_lambda_architecture_arm64(self):
        _, template = _make_stack()
        template.has_resource_properties("AWS::Lambda::Function", {
            "Architectures": ["arm64"],
        })

    def test_two_lambda_functions_exist(self):
        """Publish, chat_history, and subscribe Lambdas should be created."""
        _, template = _make_stack()
        template.resource_count_is("AWS::Lambda::Function", 3)

    def test_chat_history_lambda_has_table_param_env_var(self):
        _, template = _make_stack()
        template.has_resource_properties("AWS::Lambda::Function", {
            "Environment": assertions.Match.object_like({
                "Variables": assertions.Match.object_like({
                    "CHAT_MESSAGES_TABLE_PARAM": CHAT_MESSAGES_TABLE_PARAM_NAME,
                }),
            }),
        })


# ---------------------------------------------------------------------------
# Task 10.3 — Chat channel namespace in AppSync Events API
# ---------------------------------------------------------------------------
class TestChatChannelNamespace:
    """Validates: Requirement 4.1 — Chat channel namespace with correct handler."""

    def test_chat_channel_namespace_exists(self):
        _, template = _make_stack()
        template.has_resource_properties("AWS::AppSync::ChannelNamespace", {
            "Name": "chat",
        })

    def test_chat_channel_namespace_has_publish_handler(self):
        _, template = _make_stack()
        template.has_resource_properties("AWS::AppSync::ChannelNamespace", {
            "Name": "chat",
            "HandlerConfigs": assertions.Match.object_like({
                "OnPublish": assertions.Match.object_like({
                    "Behavior": "DIRECT",
                    "Integration": assertions.Match.object_like({
                        "DataSourceName": assertions.Match.any_value(),
                        "LambdaConfig": {
                            "InvokeType": "REQUEST_RESPONSE",
                        },
                    }),
                }),
            }),
        })

    def test_chat_data_source_exists(self):
        """A Lambda data source should exist for the chat channel namespace."""
        _, template = _make_stack()
        # There should be at least 2 data sources: messages-publish-ds and chat-publish-ds
        resources = template.find_resources("AWS::AppSync::DataSource", {
            "Properties": assertions.Match.object_like({
                "Type": "AWS_LAMBDA",
            }),
        })
        assert len(resources) >= 2, f"Expected at least 2 Lambda data sources, found {len(resources)}"

    def test_three_channel_namespaces_exist(self):
        """Three channel namespaces should exist: messages, response, chat."""
        _, template = _make_stack()
        template.resource_count_is("AWS::AppSync::ChannelNamespace", 3)


# ---------------------------------------------------------------------------
# Task 10.4 — IAM permissions for DynamoDB access
# ---------------------------------------------------------------------------
class TestDynamoDBPermissions:
    """Validates: Requirements 5.1, 5.2, 5.3 — IAM permissions for DynamoDB access."""

    def test_publish_lambda_has_dynamodb_put_get_update_permissions(self):
        """Publish Lambda should have PutItem, GetItem, UpdateItem on ChatMessages table."""
        _, template = _make_stack()
        template.has_resource_properties("AWS::IAM::Policy", assertions.Match.object_like({
            "PolicyDocument": assertions.Match.object_like({
                "Statement": assertions.Match.array_with([
                    assertions.Match.object_like({
                        "Action": [
                            "dynamodb:PutItem",
                            "dynamodb:GetItem",
                            "dynamodb:UpdateItem",
                        ],
                        "Effect": "Allow",
                    }),
                ]),
            }),
        }))

    def test_chat_history_lambda_has_full_dynamodb_permissions(self):
        """Chat history Lambda should have Query, PutItem, GetItem, DeleteItem, BatchWriteItem, UpdateItem."""
        _, template = _make_stack()
        template.has_resource_properties("AWS::IAM::Policy", assertions.Match.object_like({
            "PolicyDocument": assertions.Match.object_like({
                "Statement": assertions.Match.array_with([
                    assertions.Match.object_like({
                        "Action": [
                            "dynamodb:Query",
                            "dynamodb:PutItem",
                            "dynamodb:GetItem",
                            "dynamodb:DeleteItem",
                            "dynamodb:BatchWriteItem",
                            "dynamodb:UpdateItem",
                        ],
                        "Effect": "Allow",
                    }),
                ]),
            }),
        }))

    def test_chat_history_lambda_dynamodb_resource_includes_index(self):
        """Chat history Lambda DynamoDB permissions should cover both table ARN and index ARN."""
        _, template = _make_stack()
        # Find all IAM policies and check that the chat history DynamoDB statement
        # has a Resource array (covering both table and index ARNs)
        policies = template.find_resources("AWS::IAM::Policy")
        found_index_resource = False
        for policy_id, policy in policies.items():
            statements = (
                policy.get("Properties", {})
                .get("PolicyDocument", {})
                .get("Statement", [])
            )
            for stmt in statements:
                actions = stmt.get("Action", [])
                if isinstance(actions, list) and "dynamodb:Query" in actions:
                    resource = stmt.get("Resource", [])
                    if isinstance(resource, list) and len(resource) == 2:
                        found_index_resource = True
        assert found_index_resource, (
            "Expected a DynamoDB policy statement with dynamodb:Query "
            "and a Resource array of length 2 (table ARN + index ARN)"
        )

    def test_ssm_get_parameter_permission_for_chat_table(self):
        """Both Lambdas should have ssm:GetParameter on the chat messages table SSM parameter."""
        _, template = _make_stack()
        template.has_resource_properties("AWS::IAM::Policy", assertions.Match.object_like({
            "PolicyDocument": assertions.Match.object_like({
                "Statement": assertions.Match.array_with([
                    assertions.Match.object_like({
                        "Action": "ssm:GetParameter",
                        "Effect": "Allow",
                        "Resource": assertions.Match.string_like_regexp(
                            ".*parameter/table/chat_messages"
                        ),
                    }),
                ]),
            }),
        }))
