import aws_cdk as cdk
import aws_cdk.assertions as assertions
from aws_cdk import aws_cognito, aws_lambda

from constructs import Construct
from apis.events_api import EventsAPI
from lambdas.project_lambdas import Lambdas


def _make_api_key_only_template():
    """Synthesize a stack with EventsAPI (no Cognito) + a channel namespace."""
    app = cdk.App()

    class _Stack(cdk.Stack):
        def __init__(self, scope, id, **kwargs):
            super().__init__(scope, id, **kwargs)
            self.events_api = EventsAPI(self, "EventsAPI")
            self.lambdas = Lambdas(self, "Lambdas")
            self.events_api.add_channel_namespace(
                "messages", publish=self.lambdas.publish, pub_invoke_type="EVENT"
            )

    stack = _Stack(app, "ApiKeyOnlyStack")
    return assertions.Template.from_stack(stack)


def _make_cognito_template():
    """Synthesize a stack with EventsAPI + Cognito User Pool + a channel namespace."""
    app = cdk.App()

    class _Stack(cdk.Stack):
        def __init__(self, scope, id, **kwargs):
            super().__init__(scope, id, **kwargs)
            pool = aws_cognito.UserPool(self, "TestPool")
            self.events_api = EventsAPI(self, "EventsAPI", cognito_user_pool=pool)
            self.lambdas = Lambdas(self, "Lambdas")
            self.events_api.add_channel_namespace(
                "messages", publish=self.lambdas.publish, pub_invoke_type="EVENT"
            )

    stack = _Stack(app, "CognitoStack")
    return assertions.Template.from_stack(stack)


# ---------------------------------------------------------------------------
# Requirement 1.1 — EventApi resource with correct API name
# ---------------------------------------------------------------------------
class TestEventApiResource:
    """Validates: Requirements 1.1"""

    def test_event_api_exists_with_correct_name(self):
        template = _make_api_key_only_template()
        template.has_resource_properties("AWS::AppSync::Api", {
            "Name": "EventsAPI",
        })

    def test_event_api_has_event_config(self):
        template = _make_api_key_only_template()
        template.has_resource_properties("AWS::AppSync::Api", {
            "EventConfig": assertions.Match.object_like({
                "AuthProviders": assertions.Match.any_value(),
            }),
        })


# ---------------------------------------------------------------------------
# Requirement 1.3 — API_KEY auth provider with 365-day expiration
# ---------------------------------------------------------------------------
class TestApiKeyAuth:
    """Validates: Requirements 1.3"""

    def test_api_key_resource_exists(self):
        template = _make_api_key_only_template()
        template.resource_count_is("AWS::AppSync::ApiKey", 1)

    def test_api_key_auth_provider_present(self):
        template = _make_api_key_only_template()
        template.has_resource_properties("AWS::AppSync::Api", {
            "EventConfig": assertions.Match.object_like({
                "AuthProviders": assertions.Match.array_with([
                    assertions.Match.object_like({"AuthType": "API_KEY"}),
                ]),
            }),
        })


# ---------------------------------------------------------------------------
# Requirement 1.2 — USER_POOL auth provider when Cognito is provided
# ---------------------------------------------------------------------------
class TestCognitoAuth:
    """Validates: Requirements 1.2"""

    def test_user_pool_auth_provider_present_when_cognito_provided(self):
        template = _make_cognito_template()
        template.has_resource_properties("AWS::AppSync::Api", {
            "EventConfig": assertions.Match.object_like({
                "AuthProviders": assertions.Match.array_with([
                    assertions.Match.object_like({
                        "AuthType": "AMAZON_COGNITO_USER_POOLS",
                        "CognitoConfig": assertions.Match.object_like({
                            "UserPoolId": assertions.Match.any_value(),
                        }),
                    }),
                ]),
            }),
        })

    def test_no_user_pool_auth_when_cognito_not_provided(self):
        template = _make_api_key_only_template()
        # Only API_KEY should be present — exactly one auth provider
        template.has_resource_properties("AWS::AppSync::Api", {
            "EventConfig": assertions.Match.object_like({
                "AuthProviders": [
                    {"AuthType": "API_KEY"},
                ],
            }),
        })


# ---------------------------------------------------------------------------
# Requirements 1.4, 1.5, 1.6 — Connection, publish, subscribe auth modes
# ---------------------------------------------------------------------------
class TestAuthModes:
    """Validates: Requirements 1.4, 1.5, 1.6"""

    def test_connection_auth_modes_api_key_only(self):
        template = _make_api_key_only_template()
        template.has_resource_properties("AWS::AppSync::Api", {
            "EventConfig": assertions.Match.object_like({
                "ConnectionAuthModes": [{"AuthType": "API_KEY"}],
            }),
        })

    def test_publish_auth_modes_api_key_only(self):
        template = _make_api_key_only_template()
        template.has_resource_properties("AWS::AppSync::Api", {
            "EventConfig": assertions.Match.object_like({
                "DefaultPublishAuthModes": [{"AuthType": "API_KEY"}],
            }),
        })

    def test_subscribe_auth_modes_api_key_only(self):
        template = _make_api_key_only_template()
        template.has_resource_properties("AWS::AppSync::Api", {
            "EventConfig": assertions.Match.object_like({
                "DefaultSubscribeAuthModes": [{"AuthType": "API_KEY"}],
            }),
        })

    def test_connection_auth_modes_with_cognito(self):
        template = _make_cognito_template()
        template.has_resource_properties("AWS::AppSync::Api", {
            "EventConfig": assertions.Match.object_like({
                "ConnectionAuthModes": assertions.Match.array_with([
                    assertions.Match.object_like({"AuthType": "API_KEY"}),
                    assertions.Match.object_like({"AuthType": "AMAZON_COGNITO_USER_POOLS"}),
                ]),
            }),
        })

    def test_publish_auth_modes_with_cognito(self):
        template = _make_cognito_template()
        template.has_resource_properties("AWS::AppSync::Api", {
            "EventConfig": assertions.Match.object_like({
                "DefaultPublishAuthModes": assertions.Match.array_with([
                    assertions.Match.object_like({"AuthType": "API_KEY"}),
                    assertions.Match.object_like({"AuthType": "AMAZON_COGNITO_USER_POOLS"}),
                ]),
            }),
        })

    def test_subscribe_auth_modes_with_cognito(self):
        template = _make_cognito_template()
        template.has_resource_properties("AWS::AppSync::Api", {
            "EventConfig": assertions.Match.object_like({
                "DefaultSubscribeAuthModes": assertions.Match.array_with([
                    assertions.Match.object_like({"AuthType": "API_KEY"}),
                    assertions.Match.object_like({"AuthType": "AMAZON_COGNITO_USER_POOLS"}),
                ]),
            }),
        })


# ---------------------------------------------------------------------------
# Requirements 2.1, 2.2 — Channel namespace with Lambda data source binding
# ---------------------------------------------------------------------------
class TestChannelNamespace:
    """Validates: Requirements 2.1, 2.2"""

    def test_channel_namespace_exists_with_correct_name(self):
        template = _make_api_key_only_template()
        template.has_resource_properties("AWS::AppSync::ChannelNamespace", {
            "Name": "messages",
        })

    def test_lambda_data_source_exists(self):
        template = _make_api_key_only_template()
        template.has_resource_properties("AWS::AppSync::DataSource", {
            "Type": "AWS_LAMBDA",
            "LambdaConfig": assertions.Match.object_like({
                "LambdaFunctionArn": assertions.Match.any_value(),
            }),
        })

    def test_channel_namespace_has_publish_handler(self):
        template = _make_api_key_only_template()
        template.has_resource_properties("AWS::AppSync::ChannelNamespace", {
            "Name": "messages",
            "HandlerConfigs": assertions.Match.object_like({
                "OnPublish": assertions.Match.object_like({
                    "Behavior": "DIRECT",
                    "Integration": assertions.Match.object_like({
                        "DataSourceName": assertions.Match.any_value(),
                        "LambdaConfig": {
                            "InvokeType": "EVENT",
                        },
                    }),
                }),
            }),
        })
