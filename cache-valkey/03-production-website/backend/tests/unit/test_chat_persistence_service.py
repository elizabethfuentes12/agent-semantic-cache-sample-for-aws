"""Tests for chat_persistence_service module (lambdas/code/publish/chat_persistence_service.py).

Validates: Requirements 2.1, 2.2, 2.4, 2.6
"""

import importlib.util
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Mock boto3 before importing chat_persistence_service, since the module calls
# boto3.resource("dynamodb").Table(table_name) at init time.
# ---------------------------------------------------------------------------
_mock_boto3 = MagicMock()
_mock_dynamodb_resource = MagicMock()
_mock_table = MagicMock()
_mock_boto3.resource.return_value = _mock_dynamodb_resource
_mock_dynamodb_resource.Table.return_value = _mock_table

# Set up ConditionalCheckFailedException as a real exception class on the mock
_ConditionalCheckFailedException = type(
    "ConditionalCheckFailedException", (Exception,), {}
)
_mock_table.meta.client.exceptions.ConditionalCheckFailedException = (
    _ConditionalCheckFailedException
)

# Force our mock into sys.modules
_original_boto3 = sys.modules.get("boto3")
sys.modules["boto3"] = _mock_boto3

# Import chat_persistence_service via importlib.util
_MODULE_DIR = os.path.join(
    os.path.dirname(__file__), "..", "..", "lambdas", "code", "publish"
)
_MODULE_PATH = os.path.join(_MODULE_DIR, "chat_persistence_service.py")

_spec = importlib.util.spec_from_file_location("chat_persistence_service", _MODULE_PATH)
chat_persistence_service = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(chat_persistence_service)

# Restore original boto3 so other tests are not affected
if _original_boto3 is not None:
    sys.modules["boto3"] = _original_boto3
else:
    del sys.modules["boto3"]


@pytest.fixture(autouse=True)
def _reset_mock():
    """Reset the mock DynamoDB table before each test."""
    _mock_table.reset_mock()


@pytest.fixture
def service():
    """Create a ChatPersistenceService instance with the mocked table."""
    svc = chat_persistence_service.ChatPersistenceService("test-table")
    # Ensure the service uses our mock table
    svc._table = _mock_table
    return svc


class TestSaveUserMessage:
    """Test save_user_message writes correct item to DynamoDB.

    Validates: Requirement 2.1, 2.6
    """

    def test_calls_put_item_with_correct_pk(self, service):
        """save_user_message calls put_item with PK=CONV#{conversation_id}."""
        service.save_user_message("user-123", "conv-abc", "Hello world")

        _mock_table.put_item.assert_called_once()
        item = _mock_table.put_item.call_args[1]["Item"]
        assert item["PK"] == "CONV#conv-abc"

    def test_sk_starts_with_msg_prefix(self, service):
        """save_user_message creates SK starting with MSG#."""
        service.save_user_message("user-123", "conv-abc", "Hello world")

        item = _mock_table.put_item.call_args[1]["Item"]
        assert item["SK"].startswith("MSG#")

    def test_role_is_user(self, service):
        """save_user_message sets role='user' on the item."""
        service.save_user_message("user-123", "conv-abc", "Hello world")

        item = _mock_table.put_item.call_args[1]["Item"]
        assert item["role"] == "user"

    def test_content_matches_input(self, service):
        """save_user_message stores the provided content."""
        service.save_user_message("user-123", "conv-abc", "Test message content")

        item = _mock_table.put_item.call_args[1]["Item"]
        assert item["content"] == "Test message content"

    def test_attachments_persisted_when_provided(self, service):
        """save_user_message stores attachments when files are attached."""
        attachments = [
            {"name": "a.eml", "url": "https://b.s3.us-east-1.amazonaws.com/k/a.eml"}
        ]
        service.save_user_message(
            "user-123", "conv-abc", "See attached", attachments=attachments
        )

        item = _mock_table.put_item.call_args[1]["Item"]
        assert item["attachments"] == attachments

    def test_attachments_absent_when_none(self, service):
        """save_user_message omits the attachments attribute when none given."""
        service.save_user_message("user-123", "conv-abc", "No files")

        item = _mock_table.put_item.call_args[1]["Item"]
        assert "attachments" not in item

    def test_user_id_matches_input(self, service):
        """save_user_message stores the provided user_id."""
        service.save_user_message("user-456", "conv-abc", "Hello")

        item = _mock_table.put_item.call_args[1]["Item"]
        assert item["user_id"] == "user-456"

    def test_returns_message_id_and_created_at(self, service):
        """save_user_message returns dict with message_id and created_at."""
        result = service.save_user_message("user-123", "conv-abc", "Hello")

        assert result is not None
        assert "message_id" in result
        assert "created_at" in result


class TestSaveAssistantMessage:
    """Test save_assistant_message writes correct item to DynamoDB.

    Validates: Requirement 2.2
    """

    def test_role_is_assistant(self, service):
        """save_assistant_message sets role='assistant' on the item."""
        service.save_assistant_message("user-123", "conv-abc", "I can help with that")

        item = _mock_table.put_item.call_args[1]["Item"]
        assert item["role"] == "assistant"

    def test_calls_put_item_with_correct_pk(self, service):
        """save_assistant_message calls put_item with PK=CONV#{conversation_id}."""
        service.save_assistant_message("user-123", "conv-xyz", "Response text")

        item = _mock_table.put_item.call_args[1]["Item"]
        assert item["PK"] == "CONV#conv-xyz"

    def test_content_matches_input(self, service):
        """save_assistant_message stores the provided content."""
        service.save_assistant_message("user-123", "conv-abc", "Assistant response")

        item = _mock_table.put_item.call_args[1]["Item"]
        assert item["content"] == "Assistant response"

    def test_calls_update_item_for_conversation_updated_at(self, service):
        """save_assistant_message calls update_item to update conversation's updated_at."""
        service.save_assistant_message("user-123", "conv-abc", "Response")

        _mock_table.update_item.assert_called_once()
        call_kwargs = _mock_table.update_item.call_args[1]
        assert call_kwargs["Key"]["PK"] == "USER#user-123"
        assert call_kwargs["Key"]["SK"] == "CONV#conv-abc"
        assert "updated_at" in call_kwargs["UpdateExpression"]


class TestEnsureConversationExists:
    """Test ensure_conversation_exists creates conversation metadata.

    Validates: Requirement 2.7
    """

    def test_calls_put_item_with_user_pk(self, service):
        """ensure_conversation_exists calls put_item with PK=USER#{user_id}."""
        service.ensure_conversation_exists("user-123", "conv-abc")

        _mock_table.put_item.assert_called_once()
        call_kwargs = _mock_table.put_item.call_args[1]
        assert call_kwargs["Item"]["PK"] == "USER#user-123"

    def test_calls_put_item_with_conv_sk(self, service):
        """ensure_conversation_exists calls put_item with SK=CONV#{conversation_id}."""
        service.ensure_conversation_exists("user-123", "conv-abc")

        call_kwargs = _mock_table.put_item.call_args[1]
        assert call_kwargs["Item"]["SK"] == "CONV#conv-abc"

    def test_uses_condition_expression(self, service):
        """ensure_conversation_exists uses ConditionExpression='attribute_not_exists(PK)'."""
        service.ensure_conversation_exists("user-123", "conv-abc")

        call_kwargs = _mock_table.put_item.call_args[1]
        assert call_kwargs["ConditionExpression"] == "attribute_not_exists(PK)"

    def test_updates_existing_conversation_on_condition_failure(self, service):
        """When conversation already exists, ensure_conversation_exists updates updated_at."""
        _mock_table.put_item.side_effect = _ConditionalCheckFailedException(
            "Condition not met"
        )

        service.ensure_conversation_exists("user-123", "conv-abc")

        _mock_table.update_item.assert_called_once()
        call_kwargs = _mock_table.update_item.call_args[1]
        assert call_kwargs["Key"]["PK"] == "USER#user-123"
        assert call_kwargs["Key"]["SK"] == "CONV#conv-abc"


class TestPersistenceFailureHandling:
    """Test that DynamoDB exceptions return None and do not raise.

    Validates: Requirement 2.4
    """

    def test_save_user_message_returns_none_on_exception(self, service):
        """save_user_message returns None when put_item raises an exception."""
        _mock_table.put_item.side_effect = Exception("DynamoDB service error")

        result = service.save_user_message("user-123", "conv-abc", "Hello")

        assert result is None

    def test_save_user_message_does_not_raise_on_exception(self, service):
        """save_user_message does not propagate DynamoDB exceptions."""
        _mock_table.put_item.side_effect = Exception("DynamoDB service error")

        # Should not raise
        service.save_user_message("user-123", "conv-abc", "Hello")

    def test_save_assistant_message_returns_none_on_exception(self, service):
        """save_assistant_message returns None when put_item raises an exception."""
        _mock_table.put_item.side_effect = Exception("DynamoDB service error")

        result = service.save_assistant_message("user-123", "conv-abc", "Response")

        assert result is None

    def test_save_assistant_message_does_not_raise_on_exception(self, service):
        """save_assistant_message does not propagate DynamoDB exceptions."""
        _mock_table.put_item.side_effect = Exception("DynamoDB service error")

        # Should not raise
        service.save_assistant_message("user-123", "conv-abc", "Response")


class TestMessageChronologicalOrdering:
    """Test that message SK format ensures chronological ordering.

    Validates: Requirement 2.6 — Property 2.6
    """

    def test_sequential_messages_have_ordered_sks(self, service):
        """Two messages saved sequentially have SK₁ < SK₂ (lexicographic)."""
        from datetime import datetime, timezone
        from unittest.mock import patch as mock_patch

        # Use controlled timestamps to guarantee ordering
        time1 = datetime(2025, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
        time2 = datetime(2025, 1, 15, 10, 30, 1, tzinfo=timezone.utc)

        # Create a mock datetime class that returns controlled values
        mock_datetime_1 = MagicMock(wraps=datetime)
        mock_datetime_1.now.return_value = time1

        with mock_patch.object(chat_persistence_service, "datetime", mock_datetime_1):
            service.save_user_message("user-123", "conv-abc", "First message")

        first_call_item = _mock_table.put_item.call_args_list[0][1]["Item"]
        sk1 = first_call_item["SK"]

        mock_datetime_2 = MagicMock(wraps=datetime)
        mock_datetime_2.now.return_value = time2

        with mock_patch.object(chat_persistence_service, "datetime", mock_datetime_2):
            service.save_user_message("user-123", "conv-abc", "Second message")

        second_call_item = _mock_table.put_item.call_args_list[1][1]["Item"]
        sk2 = second_call_item["SK"]

        assert sk1 < sk2, f"Expected SK1 ({sk1}) < SK2 ({sk2}) for chronological ordering"
