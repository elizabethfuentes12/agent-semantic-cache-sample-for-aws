"""Tests for agent_core_service module (lambdas/code/publish/agent_core_service.py).

Property 3: AgentCore parameter forwarding — verifies that invoke_agent_runtime
is called with the correct kwargs for all input combinations.

Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7
"""

import importlib.util
import json
import os
import sys
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Mock boto3 before importing agent_core_service, since the module calls
# boto3.client("bedrock-agentcore") at class instantiation time.
# ---------------------------------------------------------------------------
_mock_boto3 = MagicMock()
_mock_agentcore_client = MagicMock()
_mock_boto3.client.return_value = _mock_agentcore_client

_original_boto3 = sys.modules.get("boto3")
sys.modules["boto3"] = _mock_boto3

# Import agent_core_service via importlib.util
_MODULE_DIR = os.path.join(
    os.path.dirname(__file__), "..", "..", "lambdas", "code", "publish"
)
_MODULE_PATH = os.path.join(_MODULE_DIR, "agent_core_service.py")

_spec = importlib.util.spec_from_file_location("agent_core_service", _MODULE_PATH)
agent_core_service = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(agent_core_service)

# Restore original boto3 so other tests are not affected
if _original_boto3 is not None:
    sys.modules["boto3"] = _original_boto3
else:
    del sys.modules["boto3"]


@pytest.fixture(autouse=True)
def _reset_mock():
    """Reset the mock AgentCore client before each test."""
    _mock_agentcore_client.reset_mock()
    # Default: invoke_agent_runtime returns a non-SSE response with empty list
    _mock_agentcore_client.invoke_agent_runtime.return_value = {
        "contentType": "application/json",
        "response": [],
    }


# ---------------------------------------------------------------------------
# Property 3: AgentCore parameter forwarding
# ---------------------------------------------------------------------------

VALID_ARN = "arn:aws:bedrock-agentcore:us-east-1:123456789012:runtime/my-agent"


class TestAgentRuntimeArnForwarding:
    """Test that agentRuntimeArn is always set to the provided agent_arn.

    **Validates: Requirements 3.1**
    """

    @pytest.mark.parametrize(
        "agent_arn",
        [
            "arn:aws:bedrock-agentcore:us-east-1:123456789012:runtime/agent-1",
            "arn:aws:bedrock-agentcore:eu-west-1:999888777666:runtime/my_agent",
            "arn:aws:bedrock-agentcore:ap-southeast-1:000000000000:runtime/A-B_C",
        ],
        ids=["us-east-1", "eu-west-1", "ap-southeast-1"],
    )
    def test_agent_runtime_arn_forwarded(self, agent_arn):
        """agentRuntimeArn kwarg matches the agent_arn passed to __init__."""
        svc = agent_core_service.AgentCoreService(agent_arn)
        svc.invoke(payload={"prompt": "hello"})

        call_kwargs = _mock_agentcore_client.invoke_agent_runtime.call_args[1]
        assert call_kwargs["agentRuntimeArn"] == agent_arn


class TestQualifierForwarding:
    """Test that qualifier defaults to DEFAULT and respects explicit values.

    **Validates: Requirements 3.4**
    """

    @pytest.mark.parametrize(
        "qualifier_arg, expected_qualifier",
        [
            (None, "DEFAULT"),
            ("PROD", "PROD"),
            ("v2", "v2"),
            ("my-qualifier_1", "my-qualifier_1"),
        ],
        ids=["default-when-absent", "explicit-PROD", "explicit-v2", "complex-qualifier"],
    )
    def test_qualifier_forwarded(self, qualifier_arg, expected_qualifier):
        """qualifier kwarg matches the agent_qualifier or defaults to DEFAULT."""
        if qualifier_arg is None:
            svc = agent_core_service.AgentCoreService(VALID_ARN)
        else:
            svc = agent_core_service.AgentCoreService(VALID_ARN, agent_qualifier=qualifier_arg)

        svc.invoke(payload={"prompt": "hello"})

        call_kwargs = _mock_agentcore_client.invoke_agent_runtime.call_args[1]
        assert call_kwargs["qualifier"] == expected_qualifier


class TestPayloadSerialization:
    """Test that payload is JSON-serialized and forwarded correctly.

    **Validates: Requirements 3.5, 3.6, 3.7**
    """

    @pytest.mark.parametrize(
        "payload",
        [
            {"prompt": "What is the weather?"},
            {"prompt": "Hello", "files": [{"name": "doc.pdf"}]},
            {"prompt": "Use tools", "selected_tools": ["weather_tool", "search"]},
            {"prompt": "All fields", "files": [], "selected_tools": ["t1"]},
            {"prompt": "日本語テスト 🎉"},
        ],
        ids=[
            "prompt-only",
            "with-files",
            "with-selected-tools",
            "with-files-and-tools",
            "unicode-prompt",
        ],
    )
    def test_payload_serialized_correctly(self, payload):
        """payload kwarg is the JSON-serialized bytes of the input dict."""
        svc = agent_core_service.AgentCoreService(VALID_ARN)
        svc.invoke(payload=payload)

        call_kwargs = _mock_agentcore_client.invoke_agent_runtime.call_args[1]
        sent_payload = call_kwargs["payload"]
        assert json.loads(sent_payload) == payload


class TestSessionIdForwarding:
    """Test that runtimeSessionId is included only when session_id is provided.

    **Validates: Requirements 3.2**
    """

    def test_session_id_included_when_provided(self):
        """runtimeSessionId is present in kwargs when session_id is given, padded to 33 chars."""
        svc = agent_core_service.AgentCoreService(VALID_ARN)
        svc.invoke(payload={"prompt": "hi"}, session_id="session-abc-123")

        call_kwargs = _mock_agentcore_client.invoke_agent_runtime.call_args[1]
        assert call_kwargs["runtimeSessionId"] == "session-abc-123".ljust(33, "0")
        assert len(call_kwargs["runtimeSessionId"]) >= 33

    def test_session_id_long_enough_not_padded(self):
        """runtimeSessionId that already meets 33 chars is not altered."""
        long_id = "a" * 40
        svc = agent_core_service.AgentCoreService(VALID_ARN)
        svc.invoke(payload={"prompt": "hi"}, session_id=long_id)

        call_kwargs = _mock_agentcore_client.invoke_agent_runtime.call_args[1]
        assert call_kwargs["runtimeSessionId"] == long_id

    def test_session_id_omitted_when_absent(self):
        """runtimeSessionId is NOT in kwargs when session_id is None."""
        svc = agent_core_service.AgentCoreService(VALID_ARN)
        svc.invoke(payload={"prompt": "hi"})

        call_kwargs = _mock_agentcore_client.invoke_agent_runtime.call_args[1]
        assert "runtimeSessionId" not in call_kwargs


class TestUserIdForwarding:
    """Test that runtimeUserId is included only when user_id is provided.

    **Validates: Requirements 3.3**
    """

    def test_user_id_included_when_provided(self):
        """runtimeUserId is present in kwargs when user_id is given."""
        svc = agent_core_service.AgentCoreService(VALID_ARN)
        svc.invoke(payload={"prompt": "hi"}, user_id="user-456")

        call_kwargs = _mock_agentcore_client.invoke_agent_runtime.call_args[1]
        assert call_kwargs["runtimeUserId"] == "user-456"

    def test_user_id_omitted_when_absent(self):
        """runtimeUserId is NOT in kwargs when user_id is None."""
        svc = agent_core_service.AgentCoreService(VALID_ARN)
        svc.invoke(payload={"prompt": "hi"})

        call_kwargs = _mock_agentcore_client.invoke_agent_runtime.call_args[1]
        assert "runtimeUserId" not in call_kwargs


class TestOptionalFieldCombinations:
    """Test all combinations of optional fields (session_id, user_id).

    **Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7**
    """

    @pytest.mark.parametrize(
        "session_id, user_id, payload, qualifier",
        [
            # Neither optional field
            (None, None, {"prompt": "hi"}, None),
            # Only session_id
            ("sess-1", None, {"prompt": "hi"}, None),
            # Only user_id
            (None, "user-1", {"prompt": "hi"}, None),
            # Both optional fields
            ("sess-2", "user-2", {"prompt": "hi"}, None),
            # All fields with custom qualifier
            ("sess-3", "user-3", {"prompt": "hi", "files": [], "selected_tools": ["t"]}, "PROD"),
            # Payload with files only, no session/user
            (None, None, {"prompt": "test", "files": [{"name": "f.txt"}]}, None),
            # Payload with selected_tools only, no session/user
            (None, None, {"prompt": "test", "selected_tools": ["tool1"]}, "v2"),
        ],
        ids=[
            "no-optionals",
            "session-only",
            "user-only",
            "both-session-and-user",
            "all-fields-custom-qualifier",
            "files-no-session-user",
            "tools-custom-qualifier",
        ],
    )
    def test_parameter_combination(self, session_id, user_id, payload, qualifier):
        """All provided parameters are forwarded; absent ones are omitted."""
        if qualifier is not None:
            svc = agent_core_service.AgentCoreService(VALID_ARN, agent_qualifier=qualifier)
        else:
            svc = agent_core_service.AgentCoreService(VALID_ARN)

        svc.invoke(payload=payload, session_id=session_id, user_id=user_id)

        call_kwargs = _mock_agentcore_client.invoke_agent_runtime.call_args[1]

        # Always present
        assert call_kwargs["agentRuntimeArn"] == VALID_ARN
        assert call_kwargs["qualifier"] == (qualifier if qualifier else "DEFAULT")
        assert json.loads(call_kwargs["payload"]) == payload

        # Conditionally present
        if session_id is not None:
            assert call_kwargs["runtimeSessionId"] == session_id.ljust(33, "0")
        else:
            assert "runtimeSessionId" not in call_kwargs

        if user_id is not None:
            assert call_kwargs["runtimeUserId"] == user_id
        else:
            assert "runtimeUserId" not in call_kwargs


# ---------------------------------------------------------------------------
# Property 4: Stream event delivery and callback correspondence
# ---------------------------------------------------------------------------


class TestSSEDataPrefixStripping:
    """Test that the 'data: ' prefix is stripped from each SSE stream line.

    **Validates: Requirements 4.1, 4.2**
    """

    @pytest.mark.parametrize(
        "raw_lines, expected_data",
        [
            # Single data line
            ([b"data: hello world"], ["hello world"]),
            # Multiple data lines
            (
                [b"data: first", b"data: second", b"data: third"],
                ["first", "second", "third"],
            ),
            # JSON data lines
            (
                [
                    b'data: {"type": "message", "content": "hi"}',
                    b'data: {"type": "complete", "answer": "done"}',
                ],
                [
                    '{"type": "message", "content": "hi"}',
                    '{"type": "complete", "answer": "done"}',
                ],
            ),
            # Data with special characters
            ([b"data: line with spaces  ", b"data: \xe2\x9c\x93 unicode"], ["line with spaces  ", "✓ unicode"]),
            # Empty data after prefix
            ([b"data: "], [""]),
        ],
        ids=[
            "single-line",
            "multiple-lines",
            "json-data-lines",
            "special-characters",
            "empty-data-after-prefix",
        ],
    )
    def test_data_prefix_stripped(self, raw_lines, expected_data):
        """Each line's 'data: ' prefix is removed; only the payload is returned."""
        mock_response = MagicMock()
        mock_response.iter_lines.return_value = raw_lines
        _mock_agentcore_client.invoke_agent_runtime.return_value = {
            "contentType": "text/event-stream",
            "response": mock_response,
        }

        svc = agent_core_service.AgentCoreService(VALID_ARN)
        result = svc.invoke(payload={"prompt": "test"})

        assert result == expected_data


class TestCallbackInvokedPerDataLine:
    """Test that the callback is invoked exactly once per data line, in stream order.

    **Validates: Requirements 4.2, 4.3**
    """

    @pytest.mark.parametrize(
        "raw_lines, expected_callback_args",
        [
            # No data lines → no callback calls
            ([], []),
            # Single line
            ([b"data: event-1"], ["event-1"]),
            # Multiple lines — order preserved
            (
                [b"data: alpha", b"data: beta", b"data: gamma"],
                ["alpha", "beta", "gamma"],
            ),
            # Lines with empty bytes (falsy) are skipped by the `if line:` guard
            ([b"data: first", b"", b"data: second"], ["first", "second"]),
        ],
        ids=[
            "no-data-lines",
            "single-callback",
            "multiple-callbacks-in-order",
            "empty-lines-skipped",
        ],
    )
    def test_callback_invoked_in_order(self, raw_lines, expected_callback_args):
        """Callback receives each stripped data value exactly once, in stream order."""
        mock_response = MagicMock()
        mock_response.iter_lines.return_value = raw_lines
        _mock_agentcore_client.invoke_agent_runtime.return_value = {
            "contentType": "text/event-stream",
            "response": mock_response,
        }

        callback = MagicMock()
        svc = agent_core_service.AgentCoreService(VALID_ARN)
        svc.invoke(payload={"prompt": "test"}, invocation_callback=callback)

        actual_args = [call.args[0] for call in callback.call_args_list]
        assert actual_args == expected_callback_args
        assert callback.call_count == len(expected_callback_args)


class TestReturnedListLengthEqualsCallbackCount:
    """Test that the returned list length equals the number of callback invocations.

    **Validates: Requirements 4.4, 4.6**
    """

    @pytest.mark.parametrize(
        "raw_lines",
        [
            [],
            [b"data: one"],
            [b"data: a", b"data: b"],
            [b"data: x", b"data: y", b"data: z", b"data: w"],
            [b"data: 1", b"", b"data: 2", b"", b"data: 3"],
        ],
        ids=["zero-lines", "one-line", "two-lines", "four-lines", "with-empty-gaps"],
    )
    def test_list_length_matches_callback_count(self, raw_lines):
        """len(result) == callback.call_count for any stream."""
        mock_response = MagicMock()
        mock_response.iter_lines.return_value = raw_lines
        _mock_agentcore_client.invoke_agent_runtime.return_value = {
            "contentType": "text/event-stream",
            "response": mock_response,
        }

        callback = MagicMock()
        svc = agent_core_service.AgentCoreService(VALID_ARN)
        result = svc.invoke(payload={"prompt": "test"}, invocation_callback=callback)

        assert len(result) == callback.call_count


class TestNonStreamingFallback:
    """Test that non-SSE responses are processed as a list of event strings.

    **Validates: Requirements 4.5, 4.6**
    """

    @pytest.mark.parametrize(
        "content_type, events",
        [
            ("application/json", ["event-a", "event-b"]),
            ("text/plain", ["single-event"]),
            ("", ["e1", "e2", "e3"]),
            ("application/json", []),
            (
                "application/octet-stream",
                ['{"type":"message","content":"hi"}', '{"type":"complete","answer":"done"}'],
            ),
        ],
        ids=[
            "json-content-type",
            "text-plain-single",
            "empty-content-type",
            "empty-event-list",
            "octet-stream-json-events",
        ],
    )
    def test_non_streaming_fallback(self, content_type, events):
        """When contentType is not text/event-stream, events are returned as-is."""
        _mock_agentcore_client.invoke_agent_runtime.return_value = {
            "contentType": content_type,
            "response": events,
        }

        callback = MagicMock()
        svc = agent_core_service.AgentCoreService(VALID_ARN)
        result = svc.invoke(payload={"prompt": "test"}, invocation_callback=callback)

        assert result == events
        assert callback.call_count == len(events)
        # Verify callback received events in order
        for i, event in enumerate(events):
            assert callback.call_args_list[i].args[0] == event


class TestNoCallbackSSEStream:
    """Test SSE stream processing when no callback is provided.

    **Validates: Requirements 4.1, 4.4**
    """

    @pytest.mark.parametrize(
        "raw_lines, expected_data",
        [
            ([b"data: alpha", b"data: beta"], ["alpha", "beta"]),
            ([], []),
        ],
        ids=["lines-without-callback", "empty-stream-without-callback"],
    )
    def test_sse_without_callback(self, raw_lines, expected_data):
        """Events are collected and returned even when invocation_callback is None."""
        mock_response = MagicMock()
        mock_response.iter_lines.return_value = raw_lines
        _mock_agentcore_client.invoke_agent_runtime.return_value = {
            "contentType": "text/event-stream",
            "response": mock_response,
        }

        svc = agent_core_service.AgentCoreService(VALID_ARN)
        result = svc.invoke(payload={"prompt": "test"}, invocation_callback=None)

        assert result == expected_data


class TestNoCallbackNonStreaming:
    """Test non-streaming fallback when no callback is provided.

    **Validates: Requirements 4.5**
    """

    @pytest.mark.parametrize(
        "events",
        [
            ["event-1", "event-2"],
            [],
        ],
        ids=["events-without-callback", "empty-without-callback"],
    )
    def test_non_streaming_without_callback(self, events):
        """Events are collected and returned even when invocation_callback is None."""
        _mock_agentcore_client.invoke_agent_runtime.return_value = {
            "contentType": "application/json",
            "response": events,
        }

        svc = agent_core_service.AgentCoreService(VALID_ARN)
        result = svc.invoke(payload={"prompt": "test"}, invocation_callback=None)

        assert result == events
