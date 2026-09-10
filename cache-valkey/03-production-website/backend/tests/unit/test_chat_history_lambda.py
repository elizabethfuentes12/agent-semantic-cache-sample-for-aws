"""Tests for chat_history lambda_function module.

Unit tests for action routing, input validation, and error handling.

Validates: Requirements 3.2, 3.8, 3.9, 3.10
"""

import importlib.util
import json
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Mock config_service, boto3, and chat_history_service at sys.modules level
# before importing lambda_function, since the module imports them at top level.
# ---------------------------------------------------------------------------
_mock_config_service = MagicMock()
_mock_config_service.get_ssm_parameter.return_value = "mock-chat-messages-table"

_mock_boto3 = MagicMock()

_mock_chat_history_service_module = MagicMock()
_MockChatHistoryService = MagicMock()
_mock_chat_history_service_module.ChatHistoryService = _MockChatHistoryService

_mock_title_generator_module = MagicMock()
_mock_title_generator_module.TitleGeneratorService = MagicMock()

sys.modules["config_service"] = _mock_config_service
sys.modules["boto3"] = _mock_boto3
sys.modules["chat_history_service"] = _mock_chat_history_service_module
sys.modules["title_generator_service"] = _mock_title_generator_module

# Import lambda_function via importlib.util
_MODULE_DIR = os.path.join(
    os.path.dirname(__file__), "..", "..", "lambdas", "code", "chat_history"
)
_MODULE_PATH = os.path.join(_MODULE_DIR, "lambda_function.py")

_spec = importlib.util.spec_from_file_location("chat_history_lambda_function", _MODULE_PATH)
lambda_function = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lambda_function)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

EVENT_ID = "evt-001"


def _make_event(payload):
    """Create an AppSync Events format event with the given payload."""
    return {
        "events": [
            {
                "id": EVENT_ID,
                "payload": payload,
            }
        ]
    }


def _get_payload(result):
    """Extract the payload from an AppSync Events response."""
    return result["events"][0]["payload"]


def _get_status_code(result):
    """Extract the statusCode from an AppSync Events response payload."""
    return _get_payload(result)["statusCode"]


def _get_event_id(result):
    """Extract the event ID from an AppSync Events response."""
    return result["events"][0]["id"]


@pytest.fixture(autouse=True)
def _reset_mocks():
    """Reset the mock service instance before each test."""
    _mock_service_instance = MagicMock()
    lambda_function.chat_history_service = _mock_service_instance
    yield _mock_service_instance


# ---------------------------------------------------------------------------
# Task 8.1: Action routing tests
# ---------------------------------------------------------------------------


class TestActionRouting:
    """Tests that each valid action delegates to the correct ChatHistoryService method.

    Validates: Requirement 3.2
    """

    def test_list_conversations_delegates_to_service(self, _reset_mocks):
        """list_conversations action calls chat_history_service.list_conversations."""
        mock_service = _reset_mocks
        mock_service.list_conversations.return_value = {
            "conversations": [],
            "next_token": None,
        }

        event = _make_event({
            "action": "list_conversations",
            "user_id": "user-123",
            "limit": 10,
            "next_token": "some-token",
        })

        result = lambda_function.lambda_handler(event, None)

        assert _get_status_code(result) == 200
        mock_service.list_conversations.assert_called_once_with(
            user_id="user-123", limit=10, next_token="some-token"  # nosec B106 - test pagination token, not a credential
        )

    def test_get_messages_delegates_to_service(self, _reset_mocks):
        """get_messages action calls chat_history_service.get_messages."""
        mock_service = _reset_mocks
        mock_service.get_messages.return_value = {
            "messages": [],
            "next_token": None,
        }

        event = _make_event({
            "action": "get_messages",
            "user_id": "user-123",
            "conversation_id": "conv-456",
            "limit": 25,
            "next_token": "page-token",
        })

        result = lambda_function.lambda_handler(event, None)

        assert _get_status_code(result) == 200
        mock_service.get_messages.assert_called_once_with(
            user_id="user-123",
            conversation_id="conv-456",
            limit=25,
            next_token="page-token",  # nosec B106 - test pagination token, not a credential
        )

    def test_create_conversation_delegates_to_service(self, _reset_mocks):
        """create_conversation action calls chat_history_service.create_conversation."""
        mock_service = _reset_mocks
        mock_service.create_conversation.return_value = {
            "conversation_id": "new-conv-id",
            "title": "My Chat",
            "created_at": "2025-01-15T10:30:00Z",
            "updated_at": "2025-01-15T10:30:00Z",
        }

        event = _make_event({
            "action": "create_conversation",
            "user_id": "user-123",
            "title": "My Chat",
        })

        result = lambda_function.lambda_handler(event, None)

        assert _get_status_code(result) == 200
        mock_service.create_conversation.assert_called_once_with(
            user_id="user-123", title="My Chat"
        )

    def test_delete_conversation_delegates_to_service(self, _reset_mocks):
        """delete_conversation action calls chat_history_service.delete_conversation."""
        mock_service = _reset_mocks
        mock_service.delete_conversation.return_value = True

        event = _make_event({
            "action": "delete_conversation",
            "user_id": "user-123",
            "conversation_id": "conv-789",
        })

        result = lambda_function.lambda_handler(event, None)

        assert _get_status_code(result) == 200
        mock_service.delete_conversation.assert_called_once_with(
            user_id="user-123", conversation_id="conv-789"
        )

    def test_update_conversation_delegates_to_service(self, _reset_mocks):
        """update_conversation action calls chat_history_service.update_conversation."""
        mock_service = _reset_mocks
        mock_service.update_conversation.return_value = {
            "conversation_id": "conv-789",
            "title": "Updated Title",
            "updated_at": "2025-01-15T11:00:00Z",
        }

        event = _make_event({
            "action": "update_conversation",
            "user_id": "user-123",
            "conversation_id": "conv-789",
            "title": "Updated Title",
        })

        result = lambda_function.lambda_handler(event, None)

        assert _get_status_code(result) == 200
        mock_service.update_conversation.assert_called_once_with(
            user_id="user-123", conversation_id="conv-789", title="Updated Title"
        )

    def test_auto_rename_conversation_delegates_to_service(self, _reset_mocks):
        """auto_rename_conversation action calls chat_history_service.auto_rename_conversation."""
        mock_service = _reset_mocks
        mock_service.auto_rename_conversation.return_value = {
            "conversation_id": "conv-789",
            "title": "Refactoring the auth module",
            "updated_at": "2025-01-15T11:00:00Z",
        }

        event = _make_event({
            "action": "auto_rename_conversation",
            "user_id": "user-123",
            "conversation_id": "conv-789",
        })

        result = lambda_function.lambda_handler(event, None)

        assert _get_status_code(result) == 200
        mock_service.auto_rename_conversation.assert_called_once_with(
            user_id="user-123", conversation_id="conv-789"
        )
        assert _get_payload(result)["title"] == "Refactoring the auth module"

    def test_list_conversations_returns_data_in_payload(self, _reset_mocks):
        """list_conversations returns result data in the AppSync Events payload."""
        mock_service = _reset_mocks
        expected_data = {"conversations": [{"conversation_id": "c1"}], "next_token": None}
        mock_service.list_conversations.return_value = expected_data

        event = _make_event({
            "action": "list_conversations",
            "user_id": "user-123",
        })

        result = lambda_function.lambda_handler(event, None)

        payload = _get_payload(result)
        assert payload["statusCode"] == 200
        assert payload["conversations"] == [{"conversation_id": "c1"}]
        assert payload["next_token"] is None

    def test_response_preserves_event_id(self, _reset_mocks):
        """Response event ID matches the incoming event ID."""
        mock_service = _reset_mocks
        mock_service.list_conversations.return_value = {
            "conversations": [],
            "next_token": None,
        }

        event = _make_event({
            "action": "list_conversations",
            "user_id": "user-123",
        })

        result = lambda_function.lambda_handler(event, None)

        assert _get_event_id(result) == EVENT_ID

    def test_response_has_events_array(self, _reset_mocks):
        """Response follows AppSync Events format with events array."""
        mock_service = _reset_mocks
        mock_service.list_conversations.return_value = {
            "conversations": [],
            "next_token": None,
        }

        event = _make_event({
            "action": "list_conversations",
            "user_id": "user-123",
        })

        result = lambda_function.lambda_handler(event, None)

        assert "events" in result
        assert isinstance(result["events"], list)
        assert len(result["events"]) == 1
        assert "id" in result["events"][0]
        assert "payload" in result["events"][0]


# ---------------------------------------------------------------------------
# Task 8.2: Error handling tests
# ---------------------------------------------------------------------------


class TestErrorHandling:
    """Tests for invalid action, missing parameters, and conversation not found.

    Validates: Requirements 3.8, 3.9, 3.10
    """

    def test_invalid_action_returns_400(self, _reset_mocks):
        """An unrecognized action returns statusCode 400."""
        event = _make_event({
            "action": "unknown_action",
            "user_id": "user-123",
        })

        result = lambda_function.lambda_handler(event, None)

        payload = _get_payload(result)
        assert payload["statusCode"] == 400
        assert payload["error"] == "Invalid action: unknown_action"

    def test_missing_user_id_returns_400(self, _reset_mocks):
        """Missing user_id returns statusCode 400."""
        event = _make_event({
            "action": "list_conversations",
        })

        result = lambda_function.lambda_handler(event, None)

        payload = _get_payload(result)
        assert payload["statusCode"] == 400
        assert payload["error"] == "Missing required parameter: user_id"

    def test_missing_conversation_id_for_get_messages_returns_400(self, _reset_mocks):
        """Missing conversation_id for get_messages returns statusCode 400."""
        event = _make_event({
            "action": "get_messages",
            "user_id": "user-123",
        })

        result = lambda_function.lambda_handler(event, None)

        payload = _get_payload(result)
        assert payload["statusCode"] == 400
        assert payload["error"] == "Missing required parameter: conversation_id"

    def test_missing_title_for_update_conversation_returns_400(self, _reset_mocks):
        """Missing title for update_conversation returns statusCode 400."""
        event = _make_event({
            "action": "update_conversation",
            "user_id": "user-123",
            "conversation_id": "conv-789",
        })

        result = lambda_function.lambda_handler(event, None)

        payload = _get_payload(result)
        assert payload["statusCode"] == 400
        assert payload["error"] == "Missing required parameter: title"

    def test_get_messages_conversation_not_found_returns_404(self, _reset_mocks):
        """get_messages raises LookupError → returns statusCode 404."""
        mock_service = _reset_mocks
        mock_service.get_messages.side_effect = LookupError("Conversation not found")

        event = _make_event({
            "action": "get_messages",
            "user_id": "user-123",
            "conversation_id": "conv-nonexistent",
        })

        result = lambda_function.lambda_handler(event, None)

        payload = _get_payload(result)
        assert payload["statusCode"] == 404
        assert payload["error"] == "Conversation not found"

    def test_delete_conversation_not_found_returns_404(self, _reset_mocks):
        """delete_conversation raises LookupError → returns statusCode 404."""
        mock_service = _reset_mocks
        mock_service.delete_conversation.side_effect = LookupError("Conversation not found")

        event = _make_event({
            "action": "delete_conversation",
            "user_id": "user-123",
            "conversation_id": "conv-nonexistent",
        })

        result = lambda_function.lambda_handler(event, None)

        payload = _get_payload(result)
        assert payload["statusCode"] == 404
        assert payload["error"] == "Conversation not found"

    def test_update_conversation_not_found_returns_404(self, _reset_mocks):
        """update_conversation raises LookupError → returns statusCode 404."""
        mock_service = _reset_mocks
        mock_service.update_conversation.side_effect = LookupError("Conversation not found")

        event = _make_event({
            "action": "update_conversation",
            "user_id": "user-123",
            "conversation_id": "conv-nonexistent",
            "title": "New Title",
        })

        result = lambda_function.lambda_handler(event, None)

        payload = _get_payload(result)
        assert payload["statusCode"] == 404
        assert payload["error"] == "Conversation not found"

    def test_missing_conversation_id_for_auto_rename_returns_400(self, _reset_mocks):
        """Missing conversation_id for auto_rename_conversation returns statusCode 400."""
        event = _make_event({
            "action": "auto_rename_conversation",
            "user_id": "user-123",
        })

        result = lambda_function.lambda_handler(event, None)

        payload = _get_payload(result)
        assert payload["statusCode"] == 400
        assert payload["error"] == "Missing required parameter: conversation_id"

    def test_auto_rename_conversation_not_found_returns_404(self, _reset_mocks):
        """auto_rename_conversation raises LookupError → returns statusCode 404."""
        mock_service = _reset_mocks
        mock_service.auto_rename_conversation.side_effect = LookupError("Conversation not found")

        event = _make_event({
            "action": "auto_rename_conversation",
            "user_id": "user-123",
            "conversation_id": "conv-nonexistent",
        })

        result = lambda_function.lambda_handler(event, None)

        payload = _get_payload(result)
        assert payload["statusCode"] == 404
        assert payload["error"] == "Conversation not found"

    def test_auto_rename_conversation_no_messages_returns_400(self, _reset_mocks):
        """auto_rename_conversation raises ValueError (no dialogue) → returns statusCode 400."""
        mock_service = _reset_mocks
        mock_service.auto_rename_conversation.side_effect = ValueError(
            "Conversation has no messages to summarize"
        )

        event = _make_event({
            "action": "auto_rename_conversation",
            "user_id": "user-123",
            "conversation_id": "conv-empty",
        })

        result = lambda_function.lambda_handler(event, None)

        payload = _get_payload(result)
        assert payload["statusCode"] == 400
        assert payload["error"] == "Conversation has no messages to summarize"

    def test_error_response_preserves_event_id(self, _reset_mocks):
        """Error responses also preserve the incoming event ID."""
        event = _make_event({
            "action": "unknown_action",
            "user_id": "user-123",
        })

        result = lambda_function.lambda_handler(event, None)

        assert _get_event_id(result) == EVENT_ID

    def test_unhandled_exception_returns_500(self, _reset_mocks):
        """Unhandled exception returns statusCode 500 in AppSync Events format."""
        mock_service = _reset_mocks
        mock_service.list_conversations.side_effect = RuntimeError("Unexpected")

        event = _make_event({
            "action": "list_conversations",
            "user_id": "user-123",
        })

        result = lambda_function.lambda_handler(event, None)

        payload = _get_payload(result)
        assert payload["statusCode"] == 500
        assert payload["error"] == "Internal server error"
