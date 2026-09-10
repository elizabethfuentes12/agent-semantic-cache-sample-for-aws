"""Tests for invocation_service module (lambdas/code/publish/invocation_service.py).

Validates: Requirements 4.1, 4.2
"""

import importlib.util
import json
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Mock boto3 before importing invocation_service, since the module calls
# boto3.client("lambda") at import time.
# ---------------------------------------------------------------------------
_mock_boto3 = MagicMock()
_mock_lambda_client = MagicMock()
_mock_boto3.client.return_value = _mock_lambda_client

# Force our mock into sys.modules regardless of whether boto3 is installed
_original_boto3 = sys.modules.get("boto3")
sys.modules["boto3"] = _mock_boto3

# Import invocation_service via importlib.util with sys.path manipulation
_MODULE_DIR = os.path.join(
    os.path.dirname(__file__), "..", "..", "lambdas", "code", "publish"
)
_MODULE_PATH = os.path.join(_MODULE_DIR, "invocation_service.py")

_spec = importlib.util.spec_from_file_location("invocation_service", _MODULE_PATH)
invocation_service = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(invocation_service)

# Restore original boto3 so other tests (CDK etc.) are not affected
if _original_boto3 is not None:
    sys.modules["boto3"] = _original_boto3
else:
    del sys.modules["boto3"]


@pytest.fixture(autouse=True)
def _reset_mock():
    """Reset the mock Lambda client before each test."""
    _mock_lambda_client.reset_mock()


class TestInvokeLambdaCallsCorrectly:
    """Test that invoke_lambda calls boto3 with the correct parameters.

    Validates: Requirement 4.1
    """

    def test_calls_invoke_with_function_name_and_event_type(self):
        """invoke_lambda passes FunctionName and InvocationType='Event' to boto3."""
        _mock_lambda_client.invoke.return_value = {"StatusCode": 202}

        arn = "arn:aws:lambda:us-east-1:123456789012:function:my-target"
        payload = {"key": "value"}

        invocation_service.invoke_lambda(arn, payload)

        _mock_lambda_client.invoke.assert_called_once()
        call_kwargs = _mock_lambda_client.invoke.call_args[1]
        assert call_kwargs["FunctionName"] == arn
        assert call_kwargs["InvocationType"] == "Event"

    def test_payload_is_json_serialized(self):
        """invoke_lambda JSON-serializes the payload dict as bytes."""
        _mock_lambda_client.invoke.return_value = {"StatusCode": 202}

        arn = "arn:aws:lambda:us-east-1:123456789012:function:my-target"
        payload = {"message": "hello", "count": 42}

        invocation_service.invoke_lambda(arn, payload)

        call_kwargs = _mock_lambda_client.invoke.call_args[1]
        sent_payload = call_kwargs["Payload"]
        assert json.loads(sent_payload) == payload


class TestInvokeLambdaReturnValue:
    """Test that invoke_lambda returns the raw boto3 response.

    Validates: Requirement 4.2
    """

    def test_returns_raw_boto3_response(self):
        """invoke_lambda returns the exact dict returned by lambda_client.invoke."""
        expected_response = {"StatusCode": 202, "Payload": "some-stream"}
        _mock_lambda_client.invoke.return_value = expected_response

        arn = "arn:aws:lambda:us-east-1:123456789012:function:my-target"
        payload = {"data": "test"}

        result = invocation_service.invoke_lambda(arn, payload)

        assert result is expected_response


# Feature: lambda-router, Property 4: Invocation payload serialization round-trip
class TestPayloadSerializationRoundTrip:
    """Property test: Invocation payload serialization round-trip.

    For any enriched payload dict passed to invoke_lambda, the Payload bytes
    sent to the boto3 Lambda invoke API shall deserialize (via json.loads) to
    a dict equal to the original enriched payload.

    Validates: Requirements 4.2
    """

    @pytest.mark.parametrize(
        "payload",
        [
            pytest.param(
                {"message": "hello", "target_arn": "arn:aws:lambda:us-east-1:123456789012:function:my-fn"},
                id="simple_strings",
            ),
            pytest.param(
                {"count": 42, "active": True, "rate": 3.14},
                id="numbers_and_booleans",
            ),
            pytest.param(
                {"metadata": {"key": "value", "nested": {"deep": True}}},
                id="nested_dicts",
            ),
            pytest.param(
                {"items": [1, "two", 3.0, None]},
                id="lists_with_mixed_types",
            ),
            pytest.param(
                {"message": "日本語テスト 🎉 émojis", "name": "José"},
                id="unicode",
            ),
            pytest.param(
                {"a": 1, "b": [1, {"c": True}], "d": {"e": [2, 3]}},
                id="mixed_complex",
            ),
        ],
    )
    def test_payload_round_trips_through_json_serialization(self, payload):
        """Payload bytes sent to boto3 invoke deserialize back to the original dict."""
        _mock_lambda_client.invoke.return_value = {"StatusCode": 202}

        dummy_arn = "arn:aws:lambda:us-east-1:123456789012:function:round-trip"
        invocation_service.invoke_lambda(dummy_arn, payload)

        sent_bytes = _mock_lambda_client.invoke.call_args[1]["Payload"]
        deserialized = json.loads(sent_bytes)
        assert deserialized == payload
