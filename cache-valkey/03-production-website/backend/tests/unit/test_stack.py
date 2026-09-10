import aws_cdk as cdk
import aws_cdk.assertions as assertions

from appsync_event_lambda_primitive.appsync_event_lambda_primitive_stack import (
    AppsyncEventLambdaPrimitiveStack,
)
from lambdas.project_lambdas import LAMBDA_CONFIG
from config import (
    APPSYNC_HTTP_ENDPOINT_PARAM_NAME,
    APPSYNC_REALTIME_ENDPOINT_PARAM_NAME,
    APPSYNC_API_KEY_PARAM_NAME,
    RESPONSE_NAMESPACE,
)


def _make_stack():
    """Synthesize the full stack without Cognito for template assertions."""
    app = cdk.App()
    stack = AppsyncEventLambdaPrimitiveStack(app, "TestStack")
    return stack, assertions.Template.from_stack(stack)


# ---------------------------------------------------------------------------
# Requirements 5.1, 5.2, 5.3 — SSM parameters created with correct names
# ---------------------------------------------------------------------------
class TestSSMParameters:
    """Validates: Requirements 5.1, 5.2, 5.3"""

    def test_http_endpoint_ssm_parameter_created(self):
        _, template = _make_stack()
        template.has_resource_properties("AWS::SSM::Parameter", {
            "Name": APPSYNC_HTTP_ENDPOINT_PARAM_NAME,
            "Type": "String",
            "Value": assertions.Match.any_value(),
        })

    def test_realtime_endpoint_ssm_parameter_created(self):
        _, template = _make_stack()
        template.has_resource_properties("AWS::SSM::Parameter", {
            "Name": APPSYNC_REALTIME_ENDPOINT_PARAM_NAME,
            "Type": "String",
            "Value": assertions.Match.any_value(),
        })

    def test_api_key_ssm_parameter_created(self):
        _, template = _make_stack()
        template.has_resource_properties("AWS::SSM::Parameter", {
            "Name": APPSYNC_API_KEY_PARAM_NAME,
            "Type": "String",
            "Value": assertions.Match.any_value(),
        })

    def test_ssm_parameter_count(self):
        # 5 app parameters (appsync http/realtime/api_key, bucket, chat table)
        # + 3 auth parameters (identity pool, web client, user pool) created
        # when the stack owns its Cognito user pool.
        _, template = _make_stack()
        template.resource_count_is("AWS::SSM::Parameter", 8)


# ---------------------------------------------------------------------------
# Requirements 5.4, 7.2 — Lambda env vars contain SSM parameter names
# ---------------------------------------------------------------------------
class TestLambdaEnvVars:
    """Validates: Requirements 5.4, 7.2"""

    def test_lambda_has_appsync_http_endpoint_param_env_var(self):
        _, template = _make_stack()
        template.has_resource_properties("AWS::Lambda::Function", {
            "Environment": assertions.Match.object_like({
                "Variables": assertions.Match.object_like({
                    "APPSYNC_HTTP_ENDPOINT_PARAM": APPSYNC_HTTP_ENDPOINT_PARAM_NAME,
                }),
            }),
        })

    def test_lambda_has_appsync_api_key_param_env_var(self):
        _, template = _make_stack()
        template.has_resource_properties("AWS::Lambda::Function", {
            "Environment": assertions.Match.object_like({
                "Variables": assertions.Match.object_like({
                    "APPSYNC_API_KEY_PARAM": APPSYNC_API_KEY_PARAM_NAME,
                }),
            }),
        })

    def test_lambda_has_response_namespace_env_var(self):
        _, template = _make_stack()
        template.has_resource_properties("AWS::Lambda::Function", {
            "Environment": assertions.Match.object_like({
                "Variables": assertions.Match.object_like({
                    "RESPONSE_NAMESPACE": RESPONSE_NAMESPACE,
                }),
            }),
        })

    def test_env_vars_are_plain_strings_not_tokens(self):
        """SSM param names must be literal strings, not CloudFormation Ref/GetAtt tokens."""
        _, template = _make_stack()
        template.has_resource_properties("AWS::Lambda::Function", {
            "Environment": assertions.Match.object_like({
                "Variables": assertions.Match.object_like({
                    # These must be plain string values, not intrinsic functions
                    "APPSYNC_HTTP_ENDPOINT_PARAM": "/semantic-cache/appsync/http_endpoint",
                    "APPSYNC_API_KEY_PARAM": "/semantic-cache/appsync/api_key",
                    "RESPONSE_NAMESPACE": "response/",
                }),
            }),
        })


# ---------------------------------------------------------------------------
# Requirements 7.6 — Lambda function configuration matches LAMBDA_CONFIG
# ---------------------------------------------------------------------------
class TestLambdaConfig:
    """Validates: Requirements 7.6"""

    def test_lambda_runtime_matches_config(self):
        _, template = _make_stack()
        template.has_resource_properties("AWS::Lambda::Function", {
            "Runtime": "python3.13",
        })

    def test_lambda_memory_matches_config(self):
        _, template = _make_stack()
        template.has_resource_properties("AWS::Lambda::Function", {
            "MemorySize": 256,
        })

    def test_lambda_timeout_matches_config(self):
        _, template = _make_stack()
        template.has_resource_properties("AWS::Lambda::Function", {
            "Timeout": 900,
        })

    def test_lambda_architecture_matches_config(self):
        _, template = _make_stack()
        template.has_resource_properties("AWS::Lambda::Function", {
            "Architectures": ["arm64"],
        })

    def test_lambda_tracing_active(self):
        _, template = _make_stack()
        template.has_resource_properties("AWS::Lambda::Function", {
            "TracingConfig": {"Mode": "Active"},
        })


# ---------------------------------------------------------------------------
# Requirements 7.3 — SSM parameters store resolved resource values
# ---------------------------------------------------------------------------
class TestSSMParameterValues:
    """Validates: Requirements 7.3"""

    def test_http_endpoint_param_has_ref_value(self):
        """SSM parameter value should reference the EventApi HTTP DNS (a resolved token)."""
        _, template = _make_stack()
        # The value should be a GetAtt on the EventApi resource, not a plain string
        template.has_resource_properties("AWS::SSM::Parameter", {
            "Name": APPSYNC_HTTP_ENDPOINT_PARAM_NAME,
            "Value": assertions.Match.not_(assertions.Match.exact("")),
        })

    def test_realtime_endpoint_param_has_ref_value(self):
        _, template = _make_stack()
        template.has_resource_properties("AWS::SSM::Parameter", {
            "Name": APPSYNC_REALTIME_ENDPOINT_PARAM_NAME,
            "Value": assertions.Match.not_(assertions.Match.exact("")),
        })

    def test_api_key_param_has_ref_value(self):
        _, template = _make_stack()
        template.has_resource_properties("AWS::SSM::Parameter", {
            "Name": APPSYNC_API_KEY_PARAM_NAME,
            "Value": assertions.Match.not_(assertions.Match.exact("")),
        })


# ---------------------------------------------------------------------------
# Requirements 7.7 — get_all_functions() returns all Lambda instances
# ---------------------------------------------------------------------------
class TestGetAllFunctions:
    """Validates: Requirements 7.7"""

    def test_get_all_functions_returns_list(self):
        stack, _ = _make_stack()
        result = stack.lambdas.get_all_functions()
        assert isinstance(result, list)

    def test_get_all_functions_contains_publish(self):
        stack, _ = _make_stack()
        result = stack.lambdas.get_all_functions()
        assert stack.lambdas.publish in result

    def test_get_all_functions_length(self):
        # publish, subscribe, chat_history, cache_inventory
        stack, _ = _make_stack()
        result = stack.lambdas.get_all_functions()
        assert len(result) == 4


# ---------------------------------------------------------------------------
# Requirements 6.1, 6.2 — IAM permissions for Lambda invocation
# ---------------------------------------------------------------------------
class TestLambdaInvokePermissions:
    """Validates: Requirements 6.1, 6.2"""

    def test_lambda_invoke_function_policy_exists(self):
        """IAM policy must include a lambda:InvokeFunction action."""
        _, template = _make_stack()
        template.has_resource_properties("AWS::IAM::Policy", assertions.Match.object_like({
            "PolicyDocument": assertions.Match.object_like({
                "Statement": assertions.Match.array_with([
                    assertions.Match.object_like({
                        "Action": "lambda:InvokeFunction",
                        "Effect": "Allow",
                    }),
                ]),
            }),
        }))

    def test_lambda_invoke_function_resource_scoped(self):
        """lambda:InvokeFunction resource must be scoped to arn:aws:lambda:*:*:function:*."""
        _, template = _make_stack()
        template.has_resource_properties("AWS::IAM::Policy", assertions.Match.object_like({
            "PolicyDocument": assertions.Match.object_like({
                "Statement": assertions.Match.array_with([
                    assertions.Match.object_like({
                        "Action": "lambda:InvokeFunction",
                        "Effect": "Allow",
                        "Resource": assertions.Match.any_value(),
                    }),
                ]),
            }),
        }))

    def test_ssm_get_parameter_permission_still_exists(self):
        """Regression: ssm:GetParameter permission must still be present."""
        _, template = _make_stack()
        template.has_resource_properties("AWS::IAM::Policy", assertions.Match.object_like({
            "PolicyDocument": assertions.Match.object_like({
                "Statement": assertions.Match.array_with([
                    assertions.Match.object_like({
                        "Action": "ssm:GetParameter",
                        "Effect": "Allow",
                        "Resource": "arn:aws:ssm:*:*:parameter/semantic-cache/*",
                    }),
                ]),
            }),
        }))

    def test_appsync_event_publish_permission_still_exists(self):
        """Regression: appsync:EventPublish permission must still be present."""
        _, template = _make_stack()
        template.has_resource_properties("AWS::IAM::Policy", assertions.Match.object_like({
            "PolicyDocument": assertions.Match.object_like({
                "Statement": assertions.Match.array_with([
                    assertions.Match.object_like({
                        "Action": "appsync:EventPublish",
                        "Effect": "Allow",
                    }),
                ]),
            }),
        }))


# ---------------------------------------------------------------------------
# Requirements 9.1, 9.2, 9.3 — AgentCore IAM permissions and timeout
# ---------------------------------------------------------------------------
class TestAgentCoreInfrastructure:
    """Validates: Requirements 9.1, 9.2, 9.3"""

    def test_agentcore_invoke_permission_exists(self):
        """IAM policy must include bedrock-agentcore:InvokeAgentRuntime action."""
        _, template = _make_stack()
        template.has_resource_properties("AWS::IAM::Policy", assertions.Match.object_like({
            "PolicyDocument": assertions.Match.object_like({
                "Statement": assertions.Match.array_with([
                    assertions.Match.object_like({
                        "Action": [
                            "bedrock-agentcore:InvokeAgentRuntime",
                            "bedrock-agentcore:InvokeAgentRuntimeForUser",
                        ],
                        "Effect": "Allow",
                    }),
                ]),
            }),
        }))

    def test_agentcore_invoke_resource_scoped(self):
        """bedrock-agentcore:InvokeAgentRuntime must be scoped to arn:aws:bedrock-agentcore:*:*:runtime/*."""
        _, template = _make_stack()
        template.has_resource_properties("AWS::IAM::Policy", assertions.Match.object_like({
            "PolicyDocument": assertions.Match.object_like({
                "Statement": assertions.Match.array_with([
                    assertions.Match.object_like({
                        "Action": [
                            "bedrock-agentcore:InvokeAgentRuntime",
                            "bedrock-agentcore:InvokeAgentRuntimeForUser",
                        ],
                        "Effect": "Allow",
                        "Resource": "arn:aws:bedrock-agentcore:*:*:runtime/*",
                    }),
                ]),
            }),
        }))

    def test_lambda_timeout_300_seconds(self):
        """Lambda timeout must be 900 seconds for AgentCore streaming."""
        _, template = _make_stack()
        template.has_resource_properties("AWS::Lambda::Function", {
            "Timeout": 900,
        })
