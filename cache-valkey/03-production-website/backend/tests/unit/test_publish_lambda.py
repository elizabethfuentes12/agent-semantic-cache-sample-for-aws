"""Tests for publish lambda_function module (lambdas/code/publish/lambda_function.py).

Unit tests for the router handler pattern. Property-based tests are in separate tasks.

Validates: Requirements 1.1, 1.2, 1.3, 2.1, 2.2, 2.3, 2.4, 3.1, 3.2, 3.3, 3.4, 3.5,
           4.3, 4.5, 7.1, 7.2, 7.3
"""

import importlib.util
import json
import os
import sys
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Mock config_service and invocation_service at the sys.modules level before
# importing lambda_function, since the module imports them at the top level.
# ---------------------------------------------------------------------------
_mock_config_service = MagicMock()
_mock_invocation_service = MagicMock()

sys.modules["config_service"] = _mock_config_service
sys.modules["invocation_service"] = _mock_invocation_service

# Import lambda_function via importlib.util
_MODULE_DIR = os.path.join(
    os.path.dirname(__file__), "..", "..", "lambdas", "code", "publish"
)
_MODULE_PATH = os.path.join(_MODULE_DIR, "lambda_function.py")

_spec = importlib.util.spec_from_file_location("publish_lambda_function", _MODULE_PATH)
lambda_function = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lambda_function)


@pytest.fixture(autouse=True)
def _reset_mocks_and_env(monkeypatch):
    """Reset mocks and set required environment variables before each test."""
    _mock_config_service.reset_mock()
    _mock_invocation_service.reset_mock()

    monkeypatch.setenv("APPSYNC_HTTP_ENDPOINT_PARAM", "/appsync/http_endpoint")
    monkeypatch.setenv("APPSYNC_API_KEY_PARAM", "/appsync/api_key")
    monkeypatch.setenv("RESPONSE_NAMESPACE", "response/")

    # Default: config_service.get_ssm_parameter returns sensible values
    _mock_config_service.get_ssm_parameter.side_effect = lambda name: {
        "/appsync/http_endpoint": "abc123.appsync-api.us-east-1.amazonaws.com",
        "/appsync/api_key": "da2-fakeapikey",
    }.get(name, "unknown")

    # Default: invocation_service.invoke_lambda returns 202 (async success)
    _mock_invocation_service.invoke_lambda.side_effect = None
    _mock_invocation_service.invoke_lambda.return_value = {"StatusCode": 202}


def _make_event(
    operation="PUBLISH",
    channel_path="messages/user1/session1",
    payload=None,
):
    """Build a valid router event. Override fields as needed."""
    if payload is None:
        payload = {
            "target_arn": "arn:aws:lambda:us-east-1:123456789012:function:my-target",
            "message": "Hello",
            "sessionId": "session1",
            "userId": "user1",
        }
    return {
        "info": {
            "operation": operation,
            "channel": {"path": channel_path},
        },
        "events": [
            {
                "id": "evt-001",
                "payload": payload,
            }
        ],
    }


# ---------------------------------------------------------------------------
# Successful router flow
# ---------------------------------------------------------------------------
class TestSuccessfulRouterFlow:
    """Verify successful end-to-end router flow returns 200.

    Validates: Requirements 1.1, 2.1, 2.2, 2.3, 3.1, 3.2, 3.3, 3.4, 3.5, 4.3, 7.1
    """

    def test_valid_publish_returns_200(self):
        """Router returns 200 for a valid PUBLISH event with valid target_arn."""
        event = _make_event()
        result = lambda_function.lambda_handler(event, None)

        assert result["statusCode"] == 200
        assert result["body"] == "OK"

    def test_invoke_called_with_correct_enriched_payload(self):
        """invocation_service.invoke_lambda receives target_arn and enriched payload."""
        event = _make_event(channel_path="messages/user1/session1")
        lambda_function.lambda_handler(event, None)

        _mock_invocation_service.invoke_lambda.assert_called_once()
        call_args = _mock_invocation_service.invoke_lambda.call_args

        # First positional arg: target_arn
        assert call_args[0][0] == "arn:aws:lambda:us-east-1:123456789012:function:my-target"

        # Second positional arg: enriched payload dict
        enriched = call_args[0][1]
        assert enriched["appsync_endpoint"] == "abc123.appsync-api.us-east-1.amazonaws.com"
        assert enriched["appsync_api_key"] == "da2-fakeapikey"
        assert enriched["channel"] == "/response/messages/user1/session1/evt-001"
        # Original fields preserved
        assert enriched["message"] == "Hello"
        assert enriched["sessionId"] == "session1"
        assert enriched["userId"] == "user1"
        assert enriched["target_arn"] == "arn:aws:lambda:us-east-1:123456789012:function:my-target"

    def test_ssm_called_for_endpoint_and_api_key(self):
        """config_service.get_ssm_parameter is called for both SSM params."""
        event = _make_event()
        lambda_function.lambda_handler(event, None)

        calls = [c[0][0] for c in _mock_config_service.get_ssm_parameter.call_args_list]
        assert "/appsync/http_endpoint" in calls
        assert "/appsync/api_key" in calls


# ---------------------------------------------------------------------------
# Missing target_arn → 400
# ---------------------------------------------------------------------------
class TestMissingTargetArn:
    """Verify missing target_arn returns 400.

    Validates: Requirements 1.2, 7.2
    """

    def test_missing_target_arn_returns_400(self):
        """Router returns 400 when target_arn is absent from payload."""
        payload = {"message": "Hello", "sessionId": "s1", "userId": "u1"}
        event = _make_event(payload=payload)

        result = lambda_function.lambda_handler(event, None)

        assert result["statusCode"] == 400
        assert "Missing target_arn" in result["body"]
        _mock_invocation_service.invoke_lambda.assert_not_called()


# ---------------------------------------------------------------------------
# Empty target_arn → 400
# ---------------------------------------------------------------------------
class TestEmptyTargetArn:
    """Verify empty target_arn returns 400.

    Validates: Requirements 1.3, 7.2
    """

    def test_empty_target_arn_returns_400(self):
        """Router returns 400 when target_arn is an empty string."""
        payload = {
            "target_arn": "",
            "message": "Hello",
            "sessionId": "s1",
            "userId": "u1",
        }
        event = _make_event(payload=payload)

        result = lambda_function.lambda_handler(event, None)

        assert result["statusCode"] == 400
        assert "Empty target_arn" in result["body"]
        _mock_invocation_service.invoke_lambda.assert_not_called()


# ---------------------------------------------------------------------------
# SSM failure → 500
# ---------------------------------------------------------------------------
class TestSsmFailure:
    """Verify SSM retrieval failure returns 500.

    Validates: Requirements 2.4, 7.3
    """

    def test_ssm_value_error_returns_500(self):
        """Router returns 500 when config_service raises ValueError."""
        _mock_config_service.get_ssm_parameter.side_effect = ValueError(
            "SSM parameter not found: /appsync/http_endpoint"
        )

        event = _make_event()
        result = lambda_function.lambda_handler(event, None)

        assert result["statusCode"] == 500
        assert "Failed to retrieve configuration" in result["body"]
        _mock_invocation_service.invoke_lambda.assert_not_called()


# ---------------------------------------------------------------------------
# Invoke exception → 500
# ---------------------------------------------------------------------------
class TestInvokeException:
    """Verify Lambda invoke exception returns 500.

    Validates: Requirements 4.5, 7.3
    """

    def test_invoke_exception_returns_500(self):
        """Router returns 500 when invocation_service.invoke_lambda raises."""
        _mock_invocation_service.invoke_lambda.side_effect = RuntimeError(
            "Connection error"
        )

        event = _make_event()
        result = lambda_function.lambda_handler(event, None)

        assert result["statusCode"] == 500
        assert "Internal server error" in result["body"]


# ---------------------------------------------------------------------------
# Feature: lambda-router, Property 1: Non-PUBLISH operations are rejected without invocation
# ---------------------------------------------------------------------------
class TestNonPublishOperationsRejected:
    """Property 1: Non-PUBLISH operations are rejected without invocation.

    Validates: Requirements 5.1, 5.2, 5.3
    """

    @pytest.mark.parametrize(
        "operation",
        ["SUBSCRIBE", "publish", "", "DELETE", "GET", None],
        ids=["subscribe", "lowercase-publish", "empty-string", "delete", "get", "none"],
    )
    def test_non_publish_operation_returns_400(self, operation):
        event = _make_event(operation=operation)
        result = lambda_function.lambda_handler(event, None)

        assert result["statusCode"] == 400
        assert "Invalid operation" in result["body"]
        _mock_invocation_service.invoke_lambda.assert_not_called()


# ---------------------------------------------------------------------------
# Feature: lambda-router, Property 2: Invalid target ARN format is rejected
# ---------------------------------------------------------------------------
class TestInvalidTargetArnFormatRejected:
    """Property 2: Invalid target ARN format is rejected.

    Validates: Requirements 1.4
    """

    @pytest.mark.parametrize(
        "invalid_arn, expected_message",
        [
            ("not a valid arn!", "Invalid target_arn format"),
            ("arn:aws:s3:::bucket", "Invalid target_arn format"),
            ("arn:aws:lambda:us-east-1:short:function:fn", "Invalid target_arn format"),
            ("arn:aws:lambda:us-east-1:123456789012:function:", "Invalid target_arn format"),
            ("arn:aws:lambda:us-east-1:123456789012:alias:fn", "Invalid target_arn format"),
            ("", "Empty target_arn"),
        ],
        ids=[
            "invalid-chars",
            "s3-arn",
            "short-account-id",
            "empty-function-name",
            "alias-not-function",
            "empty-string",
        ],
    )
    def test_invalid_arn_returns_400(self, invalid_arn, expected_message):
        """**Validates: Requirements 1.4**"""
        payload = {
            "target_arn": invalid_arn,
            "message": "Hello",
            "sessionId": "s1",
            "userId": "u1",
        }
        event = _make_event(payload=payload)
        result = lambda_function.lambda_handler(event, None)

        assert result["statusCode"] == 400
        assert expected_message in result["body"]
        _mock_invocation_service.invoke_lambda.assert_not_called()


# ---------------------------------------------------------------------------
# Feature: lambda-router, Property 3: Payload enrichment preserves original fields and adds AppSync connection data
# ---------------------------------------------------------------------------
class TestPayloadEnrichmentPreservesOriginalFields:
    """Property 3: Payload enrichment preserves original fields and adds AppSync connection data.

    **Validates: Requirements 3.2, 3.3, 3.4, 3.5, 3.6, 3.7**
    """

    VALID_TARGET_ARN = "arn:aws:lambda:us-east-1:123456789012:function:my-target"

    @pytest.mark.parametrize(
        "payload",
        [
            # 1. Minimal: just target_arn
            {"target_arn": "arn:aws:lambda:us-east-1:123456789012:function:my-target"},
            # 2. Extra fields
            {
                "target_arn": "arn:aws:lambda:us-east-1:123456789012:function:my-target",
                "message": "Hello",
                "sessionId": "session1",
                "userId": "user1",
                "custom_field": "custom_value",
            },
            # 3. Conflicting appsync_endpoint
            {
                "target_arn": "arn:aws:lambda:us-east-1:123456789012:function:my-target",
                "appsync_endpoint": "old-endpoint",
            },
            # 4. Conflicting all three AppSync fields
            {
                "target_arn": "arn:aws:lambda:us-east-1:123456789012:function:my-target",
                "appsync_endpoint": "old-endpoint",
                "appsync_api_key": "old-api-key",
                "channel": "old/channel/path",
            },
            # 5. Unicode values
            {
                "target_arn": "arn:aws:lambda:us-east-1:123456789012:function:my-target",
                "message": "日本語テスト 🎉",
            },
            # 6. Nested dict
            {
                "target_arn": "arn:aws:lambda:us-east-1:123456789012:function:my-target",
                "metadata": {"key": "value", "nested": {"deep": True}},
            },
        ],
        ids=[
            "minimal",
            "extra-fields",
            "conflicting-endpoint",
            "conflicting-all-three",
            "unicode-values",
            "nested-dict",
        ],
    )
    def test_enrichment_preserves_original_and_adds_appsync_fields(self, payload):
        """**Validates: Requirements 3.2, 3.3, 3.4, 3.5, 3.6, 3.7**"""
        channel_path = "messages/user1/session1"
        event = _make_event(channel_path=channel_path, payload=payload)

        result = lambda_function.lambda_handler(event, None)

        assert result["statusCode"] == 200

        enriched = _mock_invocation_service.invoke_lambda.call_args[0][1]

        # All original payload fields are present in the enriched payload
        for key, value in payload.items():
            if key in ("appsync_endpoint", "appsync_api_key", "channel"):
                # Conflicting fields must be overwritten with router-provided values
                continue
            assert enriched[key] == value, (
                f"Original field '{key}' not preserved: expected {value!r}, got {enriched.get(key)!r}"
            )

        # AppSync fields are set to router-provided values
        assert enriched["appsync_endpoint"] == "abc123.appsync-api.us-east-1.amazonaws.com"
        assert enriched["appsync_api_key"] == "da2-fakeapikey"
        # Channel should be /{RESPONSE_NAMESPACE}{channel_path}/{event_id}
        assert enriched["channel"] == f"/response/{channel_path}/evt-001"


# ---------------------------------------------------------------------------
# Feature: lambda-router, Property 5: Non-202 invoke responses produce 502
# ---------------------------------------------------------------------------
class TestNon202InvokeResponsesProduce502:
    """Property 5: Non-202 invoke responses produce 502.

    **Validates: Requirements 4.4**
    """

    @pytest.mark.parametrize(
        "status_code",
        [200, 400, 403, 404, 500, 503],
        ids=["200", "400", "403", "404", "500", "503"],
    )
    def test_non_202_status_code_returns_502(self, status_code):
        """**Validates: Requirements 4.4**"""
        _mock_invocation_service.invoke_lambda.return_value = {"StatusCode": status_code}

        event = _make_event()
        result = lambda_function.lambda_handler(event, None)

        assert result["statusCode"] == 502
        assert "Target invocation failed" in result["body"]


# ---------------------------------------------------------------------------
# Property 1: Routing determinism
# For any combination of agent_arn/target_arn presence (present/absent,
# empty/non-empty, both present), exactly one of {AgentCore path, Lambda path,
# 400 error} is chosen.
# ---------------------------------------------------------------------------

VALID_AGENT_ARN = "arn:aws:bedrock-agentcore:us-east-1:123456789012:runtime/my-agent"
VALID_TARGET_ARN = "arn:aws:lambda:us-east-1:123456789012:function:my-target"


class TestRoutingDeterminism:
    """Property 1: Routing determinism.

    For any payload containing any combination of agent_arn and target_arn
    fields (present/absent, empty/non-empty), exactly one of {AgentCore path,
    Lambda path, 400 error} is chosen.

    **Validates: Requirements 1.1, 1.2, 1.3, 1.4, 1.5**
    """

    # ------------------------------------------------------------------
    # Parametrized: all meaningful combinations of agent_arn / target_arn
    # ------------------------------------------------------------------
    @pytest.mark.parametrize(
        "agent_arn_value, target_arn_value, expected_path",
        [
            # agent_arn present & valid, no target_arn → AgentCore
            (VALID_AGENT_ARN, None, "agentcore"),
            # no agent_arn, target_arn present & valid → Lambda
            (None, VALID_TARGET_ARN, "lambda"),
            # both present → AgentCore (agent_arn takes precedence)
            (VALID_AGENT_ARN, VALID_TARGET_ARN, "agentcore"),
            # neither present → 400
            (None, None, "error_400"),
            # agent_arn empty string, target_arn valid → Lambda
            ("", VALID_TARGET_ARN, "lambda"),
            # agent_arn empty string, no target_arn → 400
            ("", None, "error_400"),
            # agent_arn empty string, target_arn empty → 400
            ("", "", "error_400"),
            # agent_arn valid, target_arn empty → AgentCore (agent_arn wins)
            (VALID_AGENT_ARN, "", "agentcore"),
        ],
        ids=[
            "agent_arn_only",
            "target_arn_only",
            "both_present_agent_wins",
            "neither_present",
            "empty_agent_valid_target",
            "empty_agent_no_target",
            "both_empty",
            "valid_agent_empty_target",
        ],
    )
    def test_exactly_one_path_chosen(
        self, agent_arn_value, target_arn_value, expected_path
    ):
        """Exactly one of {AgentCore, Lambda, 400} is chosen per combination.

        **Validates: Requirements 1.1, 1.2, 1.3, 1.4, 1.5**
        """
        from unittest.mock import patch, MagicMock

        payload = {"message": "Hello"}
        if agent_arn_value is not None:
            payload["agent_arn"] = agent_arn_value
        if target_arn_value is not None:
            payload["target_arn"] = target_arn_value

        event = _make_event(payload=payload)

        mock_ac_service_cls = MagicMock()
        mock_ac_instance = MagicMock()
        mock_ac_service_cls.return_value = mock_ac_instance
        mock_ac_instance.invoke.return_value = []

        mock_appsync_cls = MagicMock()
        mock_appsync_instance = MagicMock()
        mock_appsync_cls.return_value = mock_appsync_instance

        with patch.dict(
            "sys.modules",
            {
                "agent_core_service": MagicMock(AgentCoreService=mock_ac_service_cls),
                "appsync_service": MagicMock(AppsyncService=mock_appsync_cls),
            },
        ):
            result = lambda_function.lambda_handler(event, None)

        if expected_path == "agentcore":
            assert result["statusCode"] == 200
            mock_ac_service_cls.assert_called_once()
            _mock_invocation_service.invoke_lambda.assert_not_called()
        elif expected_path == "lambda":
            assert result["statusCode"] == 200
            _mock_invocation_service.invoke_lambda.assert_called_once()
            mock_ac_service_cls.assert_not_called()
        elif expected_path == "error_400":
            assert result["statusCode"] == 400
            mock_ac_service_cls.assert_not_called()
            _mock_invocation_service.invoke_lambda.assert_not_called()

    # ------------------------------------------------------------------
    # agent_arn takes precedence when both are present
    # ------------------------------------------------------------------
    def test_agent_arn_takes_precedence_over_target_arn(self):
        """When both agent_arn and target_arn are present, AgentCore path is taken.

        **Validates: Requirements 1.3**
        """
        from unittest.mock import patch, MagicMock

        payload = {
            "agent_arn": VALID_AGENT_ARN,
            "target_arn": VALID_TARGET_ARN,
            "message": "Hello",
        }
        event = _make_event(payload=payload)

        mock_ac_service_cls = MagicMock()
        mock_ac_instance = MagicMock()
        mock_ac_service_cls.return_value = mock_ac_instance
        mock_ac_instance.invoke.return_value = []

        mock_appsync_cls = MagicMock()

        with patch.dict(
            "sys.modules",
            {
                "agent_core_service": MagicMock(AgentCoreService=mock_ac_service_cls),
                "appsync_service": MagicMock(AppsyncService=mock_appsync_cls),
            },
        ):
            result = lambda_function.lambda_handler(event, None)

        assert result["statusCode"] == 200
        assert result["body"] == "OK"
        mock_ac_service_cls.assert_called_once()
        _mock_invocation_service.invoke_lambda.assert_not_called()

    # ------------------------------------------------------------------
    # Empty agent_arn with valid target_arn routes to Lambda path
    # ------------------------------------------------------------------
    def test_empty_agent_arn_with_valid_target_routes_to_lambda(self):
        """Empty agent_arn falls through to target_arn Lambda path.

        **Validates: Requirements 1.5**
        """
        payload = {
            "agent_arn": "",
            "target_arn": VALID_TARGET_ARN,
            "message": "Hello",
        }
        event = _make_event(payload=payload)

        result = lambda_function.lambda_handler(event, None)

        assert result["statusCode"] == 200
        assert result["body"] == "OK"
        _mock_invocation_service.invoke_lambda.assert_called_once()
        # Verify it was called with the target_arn
        call_args = _mock_invocation_service.invoke_lambda.call_args
        assert call_args[0][0] == VALID_TARGET_ARN


# ---------------------------------------------------------------------------
# Property 2: ARN validation completeness
# For any string provided as agent_arn, the Publish Lambda accepts it and
# proceeds to AgentCore invocation if and only if it matches the AgentCore
# ARN pattern. All non-matching strings are rejected with statusCode 400
# before any AgentCore API call is made.
# ---------------------------------------------------------------------------


class TestArnValidationCompletenessValidArns:
    """Property 2 (valid ARNs): ARN validation completeness.

    Parametrized tests with valid AgentCore ARNs (various regions, account IDs,
    agent IDs) that should pass and route to the AgentCore path.

    **Validates: Requirements 2.1, 2.2, 2.3**
    """

    @pytest.mark.parametrize(
        "valid_arn",
        [
            "arn:aws:bedrock-agentcore:us-east-1:123456789012:runtime/my-agent",
            "arn:aws:bedrock-agentcore:eu-west-1:999888777666:runtime/agent_v2",
            "arn:aws:bedrock-agentcore:ap-southeast-1:000000000000:runtime/A-B_C",
            "arn:aws:bedrock-agentcore:us-west-2:111222333444:runtime/agent123",
            "arn:aws:bedrock-agentcore:sa-east-1:555666777888:runtime/My_Agent-v3",
        ],
        ids=[
            "us-east-1-standard",
            "eu-west-1-underscore",
            "ap-southeast-1-mixed-case",
            "us-west-2-numeric-id",
            "sa-east-1-complex-id",
        ],
    )
    def test_valid_agent_arn_routes_to_agentcore(self, valid_arn):
        """Valid AgentCore ARNs are accepted and routed to AgentCore path.

        **Validates: Requirements 2.1**
        """
        from unittest.mock import patch, MagicMock

        payload = {"agent_arn": valid_arn, "message": "Hello"}
        event = _make_event(payload=payload)

        mock_ac_service_cls = MagicMock()
        mock_ac_instance = MagicMock()
        mock_ac_service_cls.return_value = mock_ac_instance
        mock_ac_instance.invoke.return_value = []

        mock_appsync_cls = MagicMock()
        mock_appsync_instance = MagicMock()
        mock_appsync_cls.return_value = mock_appsync_instance

        with patch.dict(
            "sys.modules",
            {
                "agent_core_service": MagicMock(AgentCoreService=mock_ac_service_cls),
                "appsync_service": MagicMock(AppsyncService=mock_appsync_cls),
            },
        ):
            result = lambda_function.lambda_handler(event, None)

        assert result["statusCode"] == 200
        assert result["body"] == "OK"
        mock_ac_service_cls.assert_called_once()
        mock_ac_instance.invoke.assert_called_once()
        _mock_invocation_service.invoke_lambda.assert_not_called()


class TestArnValidationCompletenessInvalidArns:
    """Property 2 (invalid ARNs): ARN validation completeness.

    Parametrized tests with invalid ARNs (wrong service, missing parts, bad
    format) that should return 400. No AgentCore API call should be made.

    **Validates: Requirements 2.1, 2.2, 2.3**
    """

    @pytest.mark.parametrize(
        "invalid_arn",
        [
            "arn:aws:lambda:us-east-1:123456789012:function:my-fn",
            "arn:aws:bedrock-agentcore:us-east-1:12345:runtime/agent",
            "arn:aws:bedrock-agentcore:us-east-1:123456789012:agent/my-agent",
            "not-an-arn",
            "arn:aws:bedrock-agentcore:us-east-1:123456789012:runtime/",
            "arn:aws:bedrock-agentcore:UPPER:123456789012:runtime/agent",
            "arn:aws:bedrock-agentcore:us-east-1:123456789012:runtime/agent with space",
        ],
        ids=[
            "wrong-service-lambda",
            "short-account-id",
            "wrong-resource-type",
            "random-string",
            "empty-agent-id",
            "uppercase-region",
            "space-in-agent-id",
        ],
    )
    def test_invalid_agent_arn_returns_400(self, invalid_arn):
        """Invalid agent_arn strings are rejected with 400 before any API call.

        **Validates: Requirements 2.2, 2.3**
        """
        from unittest.mock import MagicMock

        payload = {"agent_arn": invalid_arn, "message": "Hello"}
        event = _make_event(payload=payload)

        # Create mocks to verify they are NOT called
        mock_ac_service_cls = MagicMock()

        result = lambda_function.lambda_handler(event, None)

        assert result["statusCode"] == 400
        assert invalid_arn in result["body"]
        # AgentCoreService should never be instantiated for invalid ARNs
        mock_ac_service_cls.assert_not_called()
        _mock_invocation_service.invoke_lambda.assert_not_called()


# ---------------------------------------------------------------------------
# Property 5: Callback publishes to response channel
# For any event string received by the InvocationCallback,
# AppsyncService.publish_event is called exactly once with the configured
# Response Channel and the event string wrapped in a list.
# ---------------------------------------------------------------------------


class TestCallbackPublishesToResponseChannel:
    """Property 5: Callback publishes to response channel.

    For any event string, InvocationCallback calls
    AppsyncService.publish_event exactly once with the configured
    response channel and the event wrapped in a list.

    **Validates: Requirements 5.1, 5.2**
    """

    @pytest.mark.parametrize(
        "event_string",
        [
            '{"type": "message", "content": "Hello"}',
            '{"type": "complete", "answer": "Done"}',
            '{"type": "tool_call", "tool": "search", "input": {}}',
            "simple plain text event",
            "",
            '{"type": "message", "content": "日本語テスト 🎉 émojis"}',
            '{"nested": {"deep": {"value": true}}}',
            "a" * 10000,
        ],
        ids=[
            "json-message",
            "json-complete",
            "json-tool-call",
            "plain-text",
            "empty-string",
            "unicode-emoji",
            "nested-json",
            "large-string",
        ],
    )
    def test_publish_event_called_once_with_channel_and_wrapped_event(
        self, event_string
    ):
        """publish_event is called exactly once with [event].

        **Validates: Requirements 5.1, 5.2**
        """
        mock_appsync = MagicMock()
        channel = "response/messages/user1/session1/evt-001"

        callback = lambda_function.InvocationCallback(channel, mock_appsync)
        callback(event_string)

        mock_appsync.publish_event.assert_called_once_with(channel, [event_string])

    def test_callback_uses_configured_channel(self):
        """The callback publishes to the channel provided at init time.

        **Validates: Requirements 5.1**
        """
        mock_appsync = MagicMock()
        channel = "response/custom/path/evt-xyz"

        callback = lambda_function.InvocationCallback(channel, mock_appsync)
        callback("test-event")

        mock_appsync.publish_event.assert_called_once_with(
            "response/custom/path/evt-xyz", ["test-event"]
        )

    def test_multiple_calls_each_publish_exactly_once(self):
        """Each call to the callback results in exactly one publish_event call.

        **Validates: Requirements 5.2**
        """
        mock_appsync = MagicMock()
        channel = "response/messages/user1/session1/evt-001"

        callback = lambda_function.InvocationCallback(channel, mock_appsync)

        events = ["event-1", "event-2", "event-3"]
        for evt in events:
            callback(evt)

        assert mock_appsync.publish_event.call_count == 3
        for i, evt in enumerate(events):
            assert mock_appsync.publish_event.call_args_list[i] == (
                (channel, [evt]),
            )


# ---------------------------------------------------------------------------
# Property 6: Response channel construction
# For any AppSync event with a channel path and event ID, the Publish Lambda
# constructs the Response Channel as {RESPONSE_NAMESPACE}{channel_path}/{event_id}
# where channel_path has the leading `/` stripped.
# ---------------------------------------------------------------------------


class TestResponseChannelConstruction:
    """Property 6: Response channel construction.

    For any AppSync event with a channel path and event ID, the Publish Lambda
    constructs the Response Channel as {RESPONSE_NAMESPACE}{channel_path}/{event_id}
    where channel_path has the leading `/` stripped.

    **Validates: Requirement 5.3**
    """

    @pytest.mark.parametrize(
        "channel_path, event_id, expected_channel",
        [
            (
                "messages/user1/session1",
                "evt-001",
                "/response/messages/user1/session1/evt-001",
            ),
            (
                "/messages/user1/session1",
                "evt-001",
                "/response/messages/user1/session1/evt-001",
            ),
            (
                "deep/nested/path/here",
                "abc-def-123",
                "/response/deep/nested/path/here/abc-def-123",
            ),
            (
                "/deep/nested/path/here",
                "abc-def-123",
                "/response/deep/nested/path/here/abc-def-123",
            ),
            (
                "single",
                "12345",
                "/response/single/12345",
            ),
            (
                "messages/user1/session1",
                "abc-def-123",
                "/response/messages/user1/session1/abc-def-123",
            ),
            (
                "/messages/user1/session1",
                "12345",
                "/response/messages/user1/session1/12345",
            ),
            (
                "deep/nested/path/here",
                "evt-001",
                "/response/deep/nested/path/here/evt-001",
            ),
            (
                "/single",
                "evt-001",
                "/response/single/evt-001",
            ),
        ],
        ids=[
            "no-slash-evt001",
            "leading-slash-evt001",
            "deep-path-abc-def",
            "leading-slash-deep-abc-def",
            "single-segment-12345",
            "no-slash-abc-def",
            "leading-slash-12345",
            "deep-path-evt001",
            "leading-slash-single-evt001",
        ],
    )
    def test_response_channel_format(self, channel_path, event_id, expected_channel):
        """Response channel is /{RESPONSE_NAMESPACE}{channel_path}/{event_id}.

        AppSync Events channel paths carry a leading slash (info.channel.path
        is e.g. "/default/user/john"), so the published channel is prefixed
        with "/". The incoming channel_path is lstrip("/")-normalized first to
        avoid a doubled slash.

        **Validates: Requirement 5.3**
        """
        payload = {
            "target_arn": "arn:aws:lambda:us-east-1:123456789012:function:my-target",
            "message": "Hello",
        }
        event = {
            "info": {
                "operation": "PUBLISH",
                "channel": {"path": channel_path},
            },
            "events": [
                {
                    "id": event_id,
                    "payload": payload,
                }
            ],
        }

        lambda_function.lambda_handler(event, None)

        _mock_invocation_service.invoke_lambda.assert_called_once()
        enriched = _mock_invocation_service.invoke_lambda.call_args[0][1]
        assert enriched["channel"] == expected_channel


# ---------------------------------------------------------------------------
# Property 7: Error event publication
# For any exception raised by AgentCoreService.invoke(), the Publish Lambda
# publishes a JSON event with type "error" and error set to the exception
# message string to the Response Channel, and returns statusCode 500.
# ---------------------------------------------------------------------------


class TestErrorEventPublication:
    """Property 7: Error event publication.

    For any exception raised by AgentCoreService.invoke(), the Publish Lambda
    publishes a JSON event with type "error" and error set to str(e) to the
    Response Channel, and returns statusCode 500 with body
    "AgentCore invocation failed".

    **Validates: Requirements 6.1, 6.2**
    """

    @pytest.mark.parametrize(
        "exception, expected_error_str",
        [
            (RuntimeError("Connection timeout"), "Connection timeout"),
            (ValueError("Invalid payload"), "Invalid payload"),
            (Exception("Generic error"), "Generic error"),
            (Exception("Unicode error: 日本語 🔥"), "Unicode error: 日本語 🔥"),
        ],
        ids=[
            "runtime-error",
            "value-error",
            "generic-exception",
            "unicode-exception",
        ],
    )
    def test_error_event_published_and_500_returned(
        self, exception, expected_error_str
    ):
        """When invoke() raises, an error event is published and 500 is returned.

        **Validates: Requirements 6.1, 6.2**
        """
        from unittest.mock import patch, MagicMock

        payload = {"agent_arn": VALID_AGENT_ARN, "message": "Hello"}
        event = _make_event(
            channel_path="messages/user1/session1", payload=payload
        )

        mock_ac_service_cls = MagicMock()
        mock_ac_instance = MagicMock()
        mock_ac_service_cls.return_value = mock_ac_instance
        mock_ac_instance.invoke.side_effect = exception

        mock_appsync_cls = MagicMock()
        mock_appsync_instance = MagicMock()
        mock_appsync_cls.return_value = mock_appsync_instance

        with patch.dict(
            "sys.modules",
            {
                "agent_core_service": MagicMock(AgentCoreService=mock_ac_service_cls),
                "appsync_service": MagicMock(AppsyncService=mock_appsync_cls),
            },
        ):
            result = lambda_function.lambda_handler(event, None)

        # Verify 500 response
        assert result["statusCode"] == 500
        assert result["body"] == "AgentCore invocation failed"

        # Verify error event was published to the response channel
        expected_channel = "/response/messages/user1/session1/evt-001"
        mock_appsync_instance.publish_event.assert_called_once()
        call_args = mock_appsync_instance.publish_event.call_args
        assert call_args[0][0] == expected_channel
        published_events = call_args[0][1]
        assert len(published_events) == 1
        parsed = json.loads(published_events[0])
        assert parsed["type"] == "error"
        assert parsed["error"] == expected_error_str
        assert parsed["agent_arn"] == VALID_AGENT_ARN
        assert "timestamp" in parsed

    def test_error_event_json_structure(self):
        """The published error event is valid JSON with exactly type and error keys.

        **Validates: Requirements 6.1**
        """
        from unittest.mock import patch, MagicMock

        payload = {"agent_arn": VALID_AGENT_ARN, "message": "Hello"}
        event = _make_event(
            channel_path="messages/user1/session1", payload=payload
        )

        mock_ac_service_cls = MagicMock()
        mock_ac_instance = MagicMock()
        mock_ac_service_cls.return_value = mock_ac_instance
        mock_ac_instance.invoke.side_effect = RuntimeError("test failure")

        mock_appsync_cls = MagicMock()
        mock_appsync_instance = MagicMock()
        mock_appsync_cls.return_value = mock_appsync_instance

        with patch.dict(
            "sys.modules",
            {
                "agent_core_service": MagicMock(AgentCoreService=mock_ac_service_cls),
                "appsync_service": MagicMock(AppsyncService=mock_appsync_cls),
            },
        ):
            lambda_function.lambda_handler(event, None)

        # Extract the published event and parse it
        call_args = mock_appsync_instance.publish_event.call_args
        published_events = call_args[0][1]
        assert len(published_events) == 1

        parsed = json.loads(published_events[0])
        assert parsed["type"] == "error"
        assert parsed["error"] == "test failure"
        assert parsed["agent_arn"] == VALID_AGENT_ARN
        assert "timestamp" in parsed
        assert set(parsed.keys()) == {"type", "error", "agent_arn", "timestamp"}


# ---------------------------------------------------------------------------
# Property 8: Payload isolation
# For any input event dictionary and payload dictionary, after the Publish
# Lambda handler completes execution (on both the AgentCore path and the
# Lambda path), the original event and payload dictionaries are unchanged
# from their state before the call.
# ---------------------------------------------------------------------------

import copy


class TestPayloadIsolationLambdaPath:
    """Property 8 (Lambda path): Payload isolation.

    After handler execution on the Lambda path, the original ``event`` and
    ``payload`` dicts are unchanged.

    **Validates: Requirements 8.1, 8.2**
    """

    @pytest.mark.parametrize(
        "payload",
        [
            # Simple payload
            {
                "target_arn": VALID_TARGET_ARN,
                "message": "Hello",
            },
            # Payload with nested dicts and lists
            {
                "target_arn": VALID_TARGET_ARN,
                "message": "Hello",
                "metadata": {"key": "value", "nested": {"deep": True}},
                "tags": ["tag1", "tag2", "tag3"],
            },
            # Payload with deeply nested structures
            {
                "target_arn": VALID_TARGET_ARN,
                "message": "Hello",
                "config": {
                    "level1": {
                        "level2": {
                            "level3": [1, 2, {"inner": "data"}],
                        },
                    },
                },
                "items": [{"id": 1, "sub": [10, 20]}, {"id": 2}],
            },
        ],
        ids=[
            "simple-payload",
            "nested-dicts-and-lists",
            "deeply-nested-structures",
        ],
    )
    def test_event_and_payload_unchanged_after_lambda_path(self, payload):
        """Original event and payload dicts are not mutated by the Lambda path.

        **Validates: Requirements 8.1, 8.2**
        """
        event = _make_event(payload=payload)
        event_snapshot = copy.deepcopy(event)

        lambda_function.lambda_handler(event, None)

        assert event == event_snapshot, "Original event dict was mutated by Lambda path"


class TestPayloadIsolationAgentCorePath:
    """Property 8 (AgentCore path): Payload isolation.

    After handler execution on the AgentCore path, the original ``event`` and
    ``payload`` dicts are unchanged.

    **Validates: Requirements 8.1, 8.2**
    """

    @pytest.mark.parametrize(
        "payload",
        [
            # Simple AgentCore payload
            {
                "agent_arn": VALID_AGENT_ARN,
                "message": "Hello",
            },
            # AgentCore payload with optional fields and nested data
            {
                "agent_arn": VALID_AGENT_ARN,
                "message": "Hello",
                "session_id": "sess-001",
                "user_id": "user-001",
                "agent_qualifier": "PROD",
                "files": [{"name": "doc.pdf", "content": "base64data"}],
                "selected_tools": ["tool_a", "tool_b"],
            },
            # AgentCore payload with deeply nested structures
            {
                "agent_arn": VALID_AGENT_ARN,
                "message": "Hello",
                "metadata": {
                    "context": {
                        "history": [
                            {"role": "user", "parts": [{"text": "hi"}]},
                            {"role": "assistant", "parts": [{"text": "hello"}]},
                        ],
                    },
                },
                "files": [{"name": "a.txt", "meta": {"size": 100}}],
            },
        ],
        ids=[
            "simple-agentcore-payload",
            "full-agentcore-payload",
            "deeply-nested-agentcore-payload",
        ],
    )
    def test_event_and_payload_unchanged_after_agentcore_path(self, payload):
        """Original event and payload dicts are not mutated by the AgentCore path.

        **Validates: Requirements 8.1, 8.2**
        """
        from unittest.mock import patch, MagicMock

        event = _make_event(payload=payload)
        event_snapshot = copy.deepcopy(event)

        mock_ac_service_cls = MagicMock()
        mock_ac_instance = MagicMock()
        mock_ac_service_cls.return_value = mock_ac_instance
        mock_ac_instance.invoke.return_value = []

        mock_appsync_cls = MagicMock()
        mock_appsync_instance = MagicMock()
        mock_appsync_cls.return_value = mock_appsync_instance

        with patch.dict(
            "sys.modules",
            {
                "agent_core_service": MagicMock(AgentCoreService=mock_ac_service_cls),
                "appsync_service": MagicMock(AppsyncService=mock_appsync_cls),
            },
        ):
            lambda_function.lambda_handler(event, None)

        assert event == event_snapshot, "Original event dict was mutated by AgentCore path"


# ---------------------------------------------------------------------------
# Task 9: Unit tests for modified Publish Lambda — Chat Persistence
# ---------------------------------------------------------------------------


class TestPersistenceCalledWithConversationId:
    """9.1: When conversation_id and user_id are present, ChatPersistenceService
    is instantiated and save_user_message() is called before AgentCore invocation.

    **Validates: Requirements 2.2, 2.6**
    """

    def test_persistence_service_instantiated_and_save_user_message_called(self, monkeypatch):
        """ChatPersistenceService is created and save_user_message called with correct args."""
        from unittest.mock import patch, MagicMock

        monkeypatch.setenv("CHAT_MESSAGES_TABLE_PARAM", "/table/chat_messages")

        # Extend SSM side_effect to include the table param
        _mock_config_service.get_ssm_parameter.side_effect = lambda name: {
            "/appsync/http_endpoint": "abc123.appsync-api.us-east-1.amazonaws.com",
            "/appsync/api_key": "da2-fakeapikey",
            "/table/chat_messages": "ChatMessagesTable-ABC123",
        }.get(name, "unknown")

        # Mock ChatPersistenceService
        mock_persistence_cls = MagicMock()
        mock_persistence_instance = MagicMock()
        mock_persistence_cls.return_value = mock_persistence_instance

        mock_chat_persistence_module = MagicMock()
        mock_chat_persistence_module.ChatPersistenceService = mock_persistence_cls

        # Mock AgentCore and AppSync services
        mock_ac_service_cls = MagicMock()
        mock_ac_instance = MagicMock()
        mock_ac_service_cls.return_value = mock_ac_instance
        mock_ac_instance.invoke.return_value = []

        mock_appsync_cls = MagicMock()
        mock_appsync_instance = MagicMock()
        mock_appsync_cls.return_value = mock_appsync_instance

        payload = {
            "agent_arn": VALID_AGENT_ARN,
            "message": "Hello world",
            "user_id": "user-abc",
            "conversation_id": "conv-123",
        }
        event = _make_event(payload=payload)

        with patch.dict(
            "sys.modules",
            {
                "agent_core_service": MagicMock(AgentCoreService=mock_ac_service_cls),
                "appsync_service": MagicMock(AppsyncService=mock_appsync_cls),
                "chat_persistence_service": mock_chat_persistence_module,
            },
        ):
            result = lambda_function.lambda_handler(event, None)

        assert result["statusCode"] == 200

        # Verify ChatPersistenceService was instantiated with the table name
        mock_persistence_cls.assert_called_once_with("ChatMessagesTable-ABC123")

        # Verify ensure_conversation_exists was called
        mock_persistence_instance.ensure_conversation_exists.assert_called_once_with(
            "user-abc", "conv-123",
            agent_arn=VALID_AGENT_ARN, model_id=None,
        )

        # Verify save_user_message was called with correct args
        mock_persistence_instance.save_user_message.assert_called_once_with(
            "user-abc", "conv-123", "Hello world", attachments=None
        )

    def test_persistence_called_with_camel_case_keys(self, monkeypatch):
        """Persistence works with camelCase keys (userId, conversationId)."""
        from unittest.mock import patch, MagicMock

        monkeypatch.setenv("CHAT_MESSAGES_TABLE_PARAM", "/table/chat_messages")

        _mock_config_service.get_ssm_parameter.side_effect = lambda name: {
            "/appsync/http_endpoint": "abc123.appsync-api.us-east-1.amazonaws.com",
            "/appsync/api_key": "da2-fakeapikey",
            "/table/chat_messages": "ChatMessagesTable-ABC123",
        }.get(name, "unknown")

        mock_persistence_cls = MagicMock()
        mock_persistence_instance = MagicMock()
        mock_persistence_cls.return_value = mock_persistence_instance

        mock_chat_persistence_module = MagicMock()
        mock_chat_persistence_module.ChatPersistenceService = mock_persistence_cls

        mock_ac_service_cls = MagicMock()
        mock_ac_instance = MagicMock()
        mock_ac_service_cls.return_value = mock_ac_instance
        mock_ac_instance.invoke.return_value = []

        mock_appsync_cls = MagicMock()
        mock_appsync_instance = MagicMock()
        mock_appsync_cls.return_value = mock_appsync_instance

        payload = {
            "agent_arn": VALID_AGENT_ARN,
            "message": "Hi there",
            "userId": "user-xyz",
            "conversationId": "conv-456",
        }
        event = _make_event(payload=payload)

        with patch.dict(
            "sys.modules",
            {
                "agent_core_service": MagicMock(AgentCoreService=mock_ac_service_cls),
                "appsync_service": MagicMock(AppsyncService=mock_appsync_cls),
                "chat_persistence_service": mock_chat_persistence_module,
            },
        ):
            result = lambda_function.lambda_handler(event, None)

        assert result["statusCode"] == 200
        mock_persistence_cls.assert_called_once()
        mock_persistence_instance.save_user_message.assert_called_once_with(
            "user-xyz", "conv-456", "Hi there", attachments=None
        )

    def test_persistence_with_dict_message(self, monkeypatch):
        """When message is a dict with 'content' key, content is extracted correctly."""
        from unittest.mock import patch, MagicMock

        monkeypatch.setenv("CHAT_MESSAGES_TABLE_PARAM", "/table/chat_messages")

        _mock_config_service.get_ssm_parameter.side_effect = lambda name: {
            "/appsync/http_endpoint": "abc123.appsync-api.us-east-1.amazonaws.com",
            "/appsync/api_key": "da2-fakeapikey",
            "/table/chat_messages": "ChatMessagesTable-ABC123",
        }.get(name, "unknown")

        mock_persistence_cls = MagicMock()
        mock_persistence_instance = MagicMock()
        mock_persistence_cls.return_value = mock_persistence_instance

        mock_chat_persistence_module = MagicMock()
        mock_chat_persistence_module.ChatPersistenceService = mock_persistence_cls

        mock_ac_service_cls = MagicMock()
        mock_ac_instance = MagicMock()
        mock_ac_service_cls.return_value = mock_ac_instance
        mock_ac_instance.invoke.return_value = []

        mock_appsync_cls = MagicMock()
        mock_appsync_instance = MagicMock()
        mock_appsync_cls.return_value = mock_appsync_instance

        payload = {
            "agent_arn": VALID_AGENT_ARN,
            "message": {"content": "Structured message content"},
            "user_id": "user-abc",
            "conversation_id": "conv-789",
        }
        event = _make_event(payload=payload)

        with patch.dict(
            "sys.modules",
            {
                "agent_core_service": MagicMock(AgentCoreService=mock_ac_service_cls),
                "appsync_service": MagicMock(AppsyncService=mock_appsync_cls),
                "chat_persistence_service": mock_chat_persistence_module,
            },
        ):
            result = lambda_function.lambda_handler(event, None)

        assert result["statusCode"] == 200
        mock_persistence_instance.save_user_message.assert_called_once_with(
            "user-abc", "conv-789", "Structured message content", attachments=None
        )

    def test_persistence_with_message_attachments(self, monkeypatch):
        """Files on the message are normalized and passed to save_user_message."""
        from unittest.mock import patch, MagicMock

        monkeypatch.setenv("CHAT_MESSAGES_TABLE_PARAM", "/table/chat_messages")

        _mock_config_service.get_ssm_parameter.side_effect = lambda name: {
            "/appsync/http_endpoint": "abc123.appsync-api.us-east-1.amazonaws.com",
            "/appsync/api_key": "da2-fakeapikey",
            "/table/chat_messages": "ChatMessagesTable-ABC123",
        }.get(name, "unknown")

        mock_persistence_cls = MagicMock()
        mock_persistence_instance = MagicMock()
        mock_persistence_cls.return_value = mock_persistence_instance

        mock_chat_persistence_module = MagicMock()
        mock_chat_persistence_module.ChatPersistenceService = mock_persistence_cls

        mock_ac_service_cls = MagicMock()
        mock_ac_instance = MagicMock()
        mock_ac_service_cls.return_value = mock_ac_instance
        mock_ac_instance.invoke.return_value = []

        mock_appsync_cls = MagicMock()
        mock_appsync_instance = MagicMock()
        mock_appsync_cls.return_value = mock_appsync_instance

        payload = {
            "agent_arn": VALID_AGENT_ARN,
            "message": {
                "content": "See attached",
                "files": [
                    {
                        "name": "report.eml",
                        "type": "message/rfc822",
                        "size": 1234,
                        "uploadedFile": {"url": "https://b.s3.us-east-1.amazonaws.com/k/report.eml"},
                    }
                ],
            },
            "user_id": "user-abc",
            "conversation_id": "conv-789",
        }
        event = _make_event(payload=payload)

        with patch.dict(
            "sys.modules",
            {
                "agent_core_service": MagicMock(AgentCoreService=mock_ac_service_cls),
                "appsync_service": MagicMock(AppsyncService=mock_appsync_cls),
                "chat_persistence_service": mock_chat_persistence_module,
            },
        ):
            result = lambda_function.lambda_handler(event, None)

        assert result["statusCode"] == 200
        mock_persistence_instance.save_user_message.assert_called_once_with(
            "user-abc",
            "conv-789",
            "See attached",
            attachments=[
                {
                    "name": "report.eml",
                    "url": "https://b.s3.us-east-1.amazonaws.com/k/report.eml",
                    "type": "message/rfc822",
                    "size": 1234,
                }
            ],
        )


class TestNoPersistenceWithoutConversationId:
    """9.2: When conversation_id is absent, no ChatPersistenceService is instantiated.

    **Validates: Requirements 2.5**
    """

    def test_no_persistence_without_conversation_id(self, monkeypatch):
        """No ChatPersistenceService instantiated when conversation_id is absent."""
        from unittest.mock import patch, MagicMock

        monkeypatch.setenv("CHAT_MESSAGES_TABLE_PARAM", "/table/chat_messages")

        _mock_config_service.get_ssm_parameter.side_effect = lambda name: {
            "/appsync/http_endpoint": "abc123.appsync-api.us-east-1.amazonaws.com",
            "/appsync/api_key": "da2-fakeapikey",
            "/table/chat_messages": "ChatMessagesTable-ABC123",
        }.get(name, "unknown")

        mock_persistence_cls = MagicMock()
        mock_chat_persistence_module = MagicMock()
        mock_chat_persistence_module.ChatPersistenceService = mock_persistence_cls

        mock_ac_service_cls = MagicMock()
        mock_ac_instance = MagicMock()
        mock_ac_service_cls.return_value = mock_ac_instance
        mock_ac_instance.invoke.return_value = []

        mock_appsync_cls = MagicMock()
        mock_appsync_instance = MagicMock()
        mock_appsync_cls.return_value = mock_appsync_instance

        # Payload with user_id but NO conversation_id
        payload = {
            "agent_arn": VALID_AGENT_ARN,
            "message": "Hello",
            "user_id": "user-abc",
        }
        event = _make_event(payload=payload)

        with patch.dict(
            "sys.modules",
            {
                "agent_core_service": MagicMock(AgentCoreService=mock_ac_service_cls),
                "appsync_service": MagicMock(AppsyncService=mock_appsync_cls),
                "chat_persistence_service": mock_chat_persistence_module,
            },
        ):
            result = lambda_function.lambda_handler(event, None)

        assert result["statusCode"] == 200
        # ChatPersistenceService should NOT have been instantiated
        mock_persistence_cls.assert_not_called()

    def test_no_persistence_without_user_id(self, monkeypatch):
        """No ChatPersistenceService instantiated when user_id is absent."""
        from unittest.mock import patch, MagicMock

        monkeypatch.setenv("CHAT_MESSAGES_TABLE_PARAM", "/table/chat_messages")

        _mock_config_service.get_ssm_parameter.side_effect = lambda name: {
            "/appsync/http_endpoint": "abc123.appsync-api.us-east-1.amazonaws.com",
            "/appsync/api_key": "da2-fakeapikey",
            "/table/chat_messages": "ChatMessagesTable-ABC123",
        }.get(name, "unknown")

        mock_persistence_cls = MagicMock()
        mock_chat_persistence_module = MagicMock()
        mock_chat_persistence_module.ChatPersistenceService = mock_persistence_cls

        mock_ac_service_cls = MagicMock()
        mock_ac_instance = MagicMock()
        mock_ac_service_cls.return_value = mock_ac_instance
        mock_ac_instance.invoke.return_value = []

        mock_appsync_cls = MagicMock()
        mock_appsync_instance = MagicMock()
        mock_appsync_cls.return_value = mock_appsync_instance

        # Payload with conversation_id but NO user_id
        payload = {
            "agent_arn": VALID_AGENT_ARN,
            "message": "Hello",
            "conversation_id": "conv-123",
        }
        event = _make_event(payload=payload)

        with patch.dict(
            "sys.modules",
            {
                "agent_core_service": MagicMock(AgentCoreService=mock_ac_service_cls),
                "appsync_service": MagicMock(AppsyncService=mock_appsync_cls),
                "chat_persistence_service": mock_chat_persistence_module,
            },
        ):
            result = lambda_function.lambda_handler(event, None)

        assert result["statusCode"] == 200
        # ChatPersistenceService should NOT have been instantiated
        mock_persistence_cls.assert_not_called()


class TestFinalizeCallsSaveAssistantMessage:
    """9.3: AgentCoreStreamProcessor.finalize() calls save_assistant_message()
    with the complete answer when persistence is active.

    **Validates: Requirements 2.3**
    """

    def test_finalize_calls_save_assistant_message(self):
        """finalize() persists the assistant answer via save_assistant_message()."""
        mock_appsync = MagicMock()
        mock_persistence = MagicMock()

        processor = lambda_function.AgentCoreStreamProcessor(
            response_channel="response/test/channel/evt-001",
            appsync_service=mock_appsync,
            persistence_service=mock_persistence,
            user_id="user-abc",
            conversation_id="conv-123",
        )

        # Simulate a completed stream with last_message_text set
        processor.last_message_text = "The weather today is sunny."

        processor.finalize()

        # Verify save_assistant_message was called with the answer
        mock_persistence.save_assistant_message.assert_called_once_with(
            "user-abc", "conv-123", "The weather today is sunny."
        )

    def test_finalize_uses_cycle_text_parts_when_no_last_message(self):
        """finalize() uses cycle_text_parts if last_message_text is empty."""
        mock_appsync = MagicMock()
        mock_persistence = MagicMock()

        processor = lambda_function.AgentCoreStreamProcessor(
            response_channel="response/test/channel/evt-001",
            appsync_service=mock_appsync,
            persistence_service=mock_persistence,
            user_id="user-abc",
            conversation_id="conv-123",
        )

        # Simulate accumulated text parts without a final message
        processor.cycle_text_parts = ["Part 1. ", "Part 2."]

        processor.finalize()

        mock_persistence.save_assistant_message.assert_called_once_with(
            "user-abc", "conv-123", "Part 1. Part 2."
        )

    def test_finalize_does_not_call_persistence_when_not_set(self):
        """finalize() does not call save_assistant_message when persistence is None."""
        mock_appsync = MagicMock()

        processor = lambda_function.AgentCoreStreamProcessor(
            response_channel="response/test/channel/evt-001",
            appsync_service=mock_appsync,
            persistence_service=None,
            user_id="user-abc",
            conversation_id="conv-123",
        )

        processor.last_message_text = "Some answer"

        processor.finalize()

        # No persistence call since persistence_service is None
        # Just verify no exception is raised and complete event is published
        mock_appsync.publish_event.assert_called_once()

    def test_finalize_does_not_persist_empty_answer(self):
        """finalize() does not persist when the answer is empty/whitespace."""
        mock_appsync = MagicMock()
        mock_persistence = MagicMock()

        processor = lambda_function.AgentCoreStreamProcessor(
            response_channel="response/test/channel/evt-001",
            appsync_service=mock_appsync,
            persistence_service=mock_persistence,
            user_id="user-abc",
            conversation_id="conv-123",
        )

        # Empty answer
        processor.last_message_text = ""
        processor.cycle_text_parts = []

        processor.finalize()

        # No persistence call since answer is empty
        mock_persistence.save_assistant_message.assert_not_called()

    def test_passthrough_complete_event_persists_assistant_message(self):
        """When a pre-processed complete event arrives, the assistant answer is persisted."""
        mock_appsync = MagicMock()
        mock_persistence = MagicMock()

        processor = lambda_function.AgentCoreStreamProcessor(
            response_channel="response/test/channel/evt-001",
            appsync_service=mock_appsync,
            persistence_service=mock_persistence,
            user_id="user-abc",
            conversation_id="conv-123",
        )

        # Simulate a passthrough complete event (pre-processed by agent)
        complete_event = json.dumps({"type": "complete", "answer": "Here is the answer."})
        processor(complete_event)

        mock_persistence.save_assistant_message.assert_called_once_with(
            "user-abc", "conv-123", "Here is the answer."
        )

    def test_passthrough_complete_event_does_not_persist_empty_answer(self):
        """Passthrough complete with empty answer does not trigger persistence."""
        mock_appsync = MagicMock()
        mock_persistence = MagicMock()

        processor = lambda_function.AgentCoreStreamProcessor(
            response_channel="response/test/channel/evt-001",
            appsync_service=mock_appsync,
            persistence_service=mock_persistence,
            user_id="user-abc",
            conversation_id="conv-123",
        )

        complete_event = json.dumps({"type": "complete", "answer": ""})
        processor(complete_event)

        mock_persistence.save_assistant_message.assert_not_called()

    def test_passthrough_complete_skips_persistence_when_no_service(self):
        """Passthrough complete without persistence_service does not error."""
        mock_appsync = MagicMock()

        processor = lambda_function.AgentCoreStreamProcessor(
            response_channel="response/test/channel/evt-001",
            appsync_service=mock_appsync,
            persistence_service=None,
            user_id="user-abc",
            conversation_id="conv-123",
        )

        complete_event = json.dumps({"type": "complete", "answer": "Some answer"})
        processor(complete_event)

        # No exception raised, event still published
        mock_appsync.publish_event.assert_called_once()


class TestPersistenceFailureDoesNotBreakLambda:
    """9.4: A DynamoDB failure in persistence does not prevent the Lambda
    from returning statusCode 200.

    **Validates: Requirements 2.4**
    """

    def test_save_user_message_failure_still_returns_200(self, monkeypatch):
        """Lambda returns 200 even when save_user_message raises an exception."""
        from unittest.mock import patch, MagicMock

        monkeypatch.setenv("CHAT_MESSAGES_TABLE_PARAM", "/table/chat_messages")

        _mock_config_service.get_ssm_parameter.side_effect = lambda name: {
            "/appsync/http_endpoint": "abc123.appsync-api.us-east-1.amazonaws.com",
            "/appsync/api_key": "da2-fakeapikey",
            "/table/chat_messages": "ChatMessagesTable-ABC123",
        }.get(name, "unknown")

        mock_persistence_cls = MagicMock()
        mock_persistence_instance = MagicMock()
        mock_persistence_cls.return_value = mock_persistence_instance
        # Make save_user_message raise an exception
        mock_persistence_instance.save_user_message.side_effect = Exception(
            "DynamoDB write failed"
        )

        mock_chat_persistence_module = MagicMock()
        mock_chat_persistence_module.ChatPersistenceService = mock_persistence_cls

        mock_ac_service_cls = MagicMock()
        mock_ac_instance = MagicMock()
        mock_ac_service_cls.return_value = mock_ac_instance
        mock_ac_instance.invoke.return_value = []

        mock_appsync_cls = MagicMock()
        mock_appsync_instance = MagicMock()
        mock_appsync_cls.return_value = mock_appsync_instance

        payload = {
            "agent_arn": VALID_AGENT_ARN,
            "message": "Hello",
            "user_id": "user-abc",
            "conversation_id": "conv-123",
        }
        event = _make_event(payload=payload)

        with patch.dict(
            "sys.modules",
            {
                "agent_core_service": MagicMock(AgentCoreService=mock_ac_service_cls),
                "appsync_service": MagicMock(AppsyncService=mock_appsync_cls),
                "chat_persistence_service": mock_chat_persistence_module,
            },
        ):
            result = lambda_function.lambda_handler(event, None)

        # Lambda should still return 200 despite persistence failure
        assert result["statusCode"] == 200
        assert result["body"] == "OK"

    def test_ensure_conversation_exists_failure_still_returns_200(self, monkeypatch):
        """Lambda returns 200 even when ensure_conversation_exists raises."""
        from unittest.mock import patch, MagicMock

        monkeypatch.setenv("CHAT_MESSAGES_TABLE_PARAM", "/table/chat_messages")

        _mock_config_service.get_ssm_parameter.side_effect = lambda name: {
            "/appsync/http_endpoint": "abc123.appsync-api.us-east-1.amazonaws.com",
            "/appsync/api_key": "da2-fakeapikey",
            "/table/chat_messages": "ChatMessagesTable-ABC123",
        }.get(name, "unknown")

        mock_persistence_cls = MagicMock()
        mock_persistence_instance = MagicMock()
        mock_persistence_cls.return_value = mock_persistence_instance
        # Make ensure_conversation_exists raise
        mock_persistence_instance.ensure_conversation_exists.side_effect = Exception(
            "DynamoDB connection timeout"
        )

        mock_chat_persistence_module = MagicMock()
        mock_chat_persistence_module.ChatPersistenceService = mock_persistence_cls

        mock_ac_service_cls = MagicMock()
        mock_ac_instance = MagicMock()
        mock_ac_service_cls.return_value = mock_ac_instance
        mock_ac_instance.invoke.return_value = []

        mock_appsync_cls = MagicMock()
        mock_appsync_instance = MagicMock()
        mock_appsync_cls.return_value = mock_appsync_instance

        payload = {
            "agent_arn": VALID_AGENT_ARN,
            "message": "Hello",
            "user_id": "user-abc",
            "conversation_id": "conv-123",
        }
        event = _make_event(payload=payload)

        with patch.dict(
            "sys.modules",
            {
                "agent_core_service": MagicMock(AgentCoreService=mock_ac_service_cls),
                "appsync_service": MagicMock(AppsyncService=mock_appsync_cls),
                "chat_persistence_service": mock_chat_persistence_module,
            },
        ):
            result = lambda_function.lambda_handler(event, None)

        # Lambda should still return 200
        assert result["statusCode"] == 200
        assert result["body"] == "OK"

    def test_finalize_persistence_failure_does_not_break_response(self):
        """finalize() still publishes complete event even if persistence fails."""
        mock_appsync = MagicMock()
        mock_persistence = MagicMock()
        mock_persistence.save_assistant_message.side_effect = Exception(
            "DynamoDB throttled"
        )

        processor = lambda_function.AgentCoreStreamProcessor(
            response_channel="response/test/channel/evt-001",
            appsync_service=mock_appsync,
            persistence_service=mock_persistence,
            user_id="user-abc",
            conversation_id="conv-123",
        )

        processor.last_message_text = "The answer is 42."

        # Should not raise
        processor.finalize()

        # The complete event should still be published to AppSync
        mock_appsync.publish_event.assert_called_once()
        published_payload = json.loads(
            mock_appsync.publish_event.call_args[0][1][0]
        )
        assert published_payload["type"] == "complete"
        assert published_payload["answer"] == "The answer is 42."
