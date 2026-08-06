"""Tests for chat_history_service module (lambdas/code/chat_history/chat_history_service.py).

Validates: Requirements 3.1, 3.3, 3.4, 3.5, 3.6, 3.7
"""

import base64
import importlib.util
import json
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Mock boto3 before importing chat_history_service, since the module calls
# boto3.resource("dynamodb").Table(table_name) at init time.
# ---------------------------------------------------------------------------
_mock_boto3 = MagicMock()
_mock_dynamodb_resource = MagicMock()
_mock_table = MagicMock()
_mock_boto3.resource.return_value = _mock_dynamodb_resource
_mock_dynamodb_resource.Table.return_value = _mock_table

# Force our mock into sys.modules
_original_boto3 = sys.modules.get("boto3")
sys.modules["boto3"] = _mock_boto3

# Import chat_history_service via importlib.util
_MODULE_DIR = os.path.join(
    os.path.dirname(__file__), "..", "..", "lambdas", "code", "chat_history"
)
_MODULE_PATH = os.path.join(_MODULE_DIR, "chat_history_service.py")

_spec = importlib.util.spec_from_file_location("chat_history_service", _MODULE_PATH)
chat_history_service = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(chat_history_service)

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
    """Create a ChatHistoryService instance with the mocked table."""
    svc = chat_history_service.ChatHistoryService("test-table")
    svc.table = _mock_table
    return svc


# ===========================================================================
# 7.1 — Basic CRUD tests
# ===========================================================================


class TestListConversations:
    """Test list_conversations queries DynamoDB correctly.

    Validates: Requirement 3.3
    """

    def test_query_uses_correct_pk(self, service):
        """list_conversations queries with PK=USER#{user_id}."""
        _mock_table.query.return_value = {"Items": []}

        service.list_conversations("user-123")

        call_kwargs = _mock_table.query.call_args[1]
        assert ":pk" in call_kwargs["ExpressionAttributeValues"]
        assert call_kwargs["ExpressionAttributeValues"][":pk"] == "USER#user-123"

    def test_query_uses_conv_sk_prefix(self, service):
        """list_conversations queries with SK begins_with CONV#."""
        _mock_table.query.return_value = {"Items": []}

        service.list_conversations("user-123")

        call_kwargs = _mock_table.query.call_args[1]
        assert call_kwargs["ExpressionAttributeValues"][":sk_prefix"] == "CONV#"

    def test_returns_conversations_with_expected_fields(self, service):
        """list_conversations returns conversations with expected fields."""
        _mock_table.query.return_value = {
            "Items": [
                {
                    "conversation_id": "conv-abc",
                    "title": "Test Chat",
                    "created_at": "2025-01-15T10:30:00Z",
                    "updated_at": "2025-01-15T11:00:00Z",
                    "user_id": "user-123",
                }
            ]
        }

        result = service.list_conversations("user-123")

        assert len(result["conversations"]) == 1
        conv = result["conversations"][0]
        assert conv["conversation_id"] == "conv-abc"
        assert conv["title"] == "Test Chat"
        assert conv["created_at"] == "2025-01-15T10:30:00Z"
        assert conv["updated_at"] == "2025-01-15T11:00:00Z"
        assert conv["user_id"] == "user-123"

    def test_returns_none_next_token_when_no_more_pages(self, service):
        """list_conversations returns next_token=None when no LastEvaluatedKey."""
        _mock_table.query.return_value = {"Items": []}

        result = service.list_conversations("user-123")

        assert result["next_token"] is None

    def test_respects_limit_parameter(self, service):
        """list_conversations passes limit to DynamoDB query."""
        _mock_table.query.return_value = {"Items": []}

        service.list_conversations("user-123", limit=10)

        call_kwargs = _mock_table.query.call_args[1]
        assert call_kwargs["Limit"] == 10


class TestGetMessages:
    """Test get_messages verifies ownership and queries messages.

    Validates: Requirement 3.4
    """

    def test_calls_get_item_for_ownership_check(self, service):
        """get_messages calls get_item to verify conversation ownership."""
        _mock_table.get_item.return_value = {
            "Item": {"PK": "USER#user-123", "SK": "CONV#conv-abc"}
        }
        _mock_table.query.return_value = {"Items": []}

        service.get_messages("user-123", "conv-abc")

        _mock_table.get_item.assert_called_once_with(
            Key={"PK": "USER#user-123", "SK": "CONV#conv-abc"}
        )

    def test_queries_with_correct_pk_and_sk_prefix(self, service):
        """get_messages queries with PK=CONV#{conversation_id} and SK begins_with MSG#."""
        _mock_table.get_item.return_value = {
            "Item": {"PK": "USER#user-123", "SK": "CONV#conv-abc"}
        }
        _mock_table.query.return_value = {"Items": []}

        service.get_messages("user-123", "conv-abc")

        call_kwargs = _mock_table.query.call_args[1]
        assert call_kwargs["ExpressionAttributeValues"][":pk"] == "CONV#conv-abc"
        assert call_kwargs["ExpressionAttributeValues"][":sk_prefix"] == "MSG#"

    def test_raises_lookup_error_when_conversation_not_found(self, service):
        """get_messages raises LookupError when conversation doesn't exist."""
        _mock_table.get_item.return_value = {}

        with pytest.raises(LookupError, match="Conversation not found"):
            service.get_messages("user-123", "conv-abc")

    def test_returns_messages_with_expected_fields(self, service):
        """get_messages returns messages with expected fields."""
        _mock_table.get_item.return_value = {
            "Item": {"PK": "USER#user-123", "SK": "CONV#conv-abc"}
        }
        _mock_table.query.return_value = {
            "Items": [
                {
                    "message_id": "msg-001",
                    "role": "user",
                    "content": "Hello",
                    "created_at": "2025-01-15T10:30:00Z",
                    "conversation_id": "conv-abc",
                    "user_id": "user-123",
                }
            ]
        }

        result = service.get_messages("user-123", "conv-abc")

        assert len(result["messages"]) == 1
        msg = result["messages"][0]
        assert msg["message_id"] == "msg-001"
        assert msg["role"] == "user"
        assert msg["content"] == "Hello"

    def test_returns_attachments_when_present(self, service):
        """get_messages surfaces persisted attachment metadata."""
        attachments = [
            {"name": "a.eml", "url": "https://b.s3.us-east-1.amazonaws.com/k/a.eml"}
        ]
        _mock_table.get_item.return_value = {
            "Item": {"PK": "USER#user-123", "SK": "CONV#conv-abc"}
        }
        _mock_table.query.return_value = {
            "Items": [
                {
                    "message_id": "msg-001",
                    "role": "user",
                    "content": "See attached",
                    "created_at": "2025-01-15T10:30:00Z",
                    "conversation_id": "conv-abc",
                    "user_id": "user-123",
                    "attachments": attachments,
                }
            ]
        }

        result = service.get_messages("user-123", "conv-abc")

        assert result["messages"][0]["attachments"] == attachments

    def test_omits_attachments_key_when_absent(self, service):
        """get_messages does not add an attachments key for plain messages."""
        _mock_table.get_item.return_value = {
            "Item": {"PK": "USER#user-123", "SK": "CONV#conv-abc"}
        }
        _mock_table.query.return_value = {
            "Items": [
                {
                    "message_id": "msg-001",
                    "role": "user",
                    "content": "Hello",
                    "created_at": "2025-01-15T10:30:00Z",
                    "conversation_id": "conv-abc",
                    "user_id": "user-123",
                }
            ]
        }

        result = service.get_messages("user-123", "conv-abc")

        assert "attachments" not in result["messages"][0]


class TestCreateConversation:
    """Test create_conversation creates item with UUID and timestamps.

    Validates: Requirement 3.5
    """

    def test_calls_put_item_with_correct_pk(self, service):
        """create_conversation calls put_item with PK=USER#{user_id}."""
        service.create_conversation("user-123", title="My Chat")

        _mock_table.put_item.assert_called_once()
        item = _mock_table.put_item.call_args[1]["Item"]
        assert item["PK"] == "USER#user-123"

    def test_sk_starts_with_conv_prefix(self, service):
        """create_conversation creates SK starting with CONV#."""
        service.create_conversation("user-123")

        item = _mock_table.put_item.call_args[1]["Item"]
        assert item["SK"].startswith("CONV#")

    def test_generates_uuid_conversation_id(self, service):
        """create_conversation generates a valid UUID for conversation_id."""
        import uuid

        result = service.create_conversation("user-123")

        # Should not raise ValueError if it's a valid UUID
        uuid.UUID(result["conversation_id"])

    def test_includes_timestamps(self, service):
        """create_conversation returns created_at and updated_at timestamps."""
        result = service.create_conversation("user-123")

        assert "created_at" in result
        assert "updated_at" in result
        assert result["created_at"] == result["updated_at"]

    def test_uses_provided_title(self, service):
        """create_conversation uses the provided title."""
        result = service.create_conversation("user-123", title="My Chat")

        item = _mock_table.put_item.call_args[1]["Item"]
        assert item["title"] == "My Chat"
        assert result["title"] == "My Chat"

    def test_uses_default_title_when_none(self, service):
        """create_conversation uses default title when none provided."""
        result = service.create_conversation("user-123")

        assert result["title"] == "New Conversation"


# ===========================================================================
# 7.2 — Delete tests
# ===========================================================================


class TestDeleteConversation:
    """Test delete_conversation verifies ownership and deletes items.

    Validates: Requirement 3.6
    """

    def test_calls_get_item_for_ownership_check(self, service):
        """delete_conversation calls get_item to verify ownership."""
        _mock_table.get_item.return_value = {
            "Item": {"PK": "USER#user-123", "SK": "CONV#conv-abc"}
        }
        _mock_table.query.return_value = {"Items": []}
        _mock_batch_writer = MagicMock()
        _mock_table.batch_writer.return_value.__enter__ = MagicMock(
            return_value=_mock_batch_writer
        )
        _mock_table.batch_writer.return_value.__exit__ = MagicMock(return_value=False)

        service.delete_conversation("user-123", "conv-abc")

        _mock_table.get_item.assert_called_once_with(
            Key={"PK": "USER#user-123", "SK": "CONV#conv-abc"}
        )

    def test_queries_messages_for_batch_delete(self, service):
        """delete_conversation queries all messages to collect keys."""
        _mock_table.get_item.return_value = {
            "Item": {"PK": "USER#user-123", "SK": "CONV#conv-abc"}
        }
        _mock_table.query.return_value = {
            "Items": [
                {"PK": "CONV#conv-abc", "SK": "MSG#2025-01-15T10:30:00Z#msg-001"}
            ]
        }
        _mock_batch_writer = MagicMock()
        _mock_table.batch_writer.return_value.__enter__ = MagicMock(
            return_value=_mock_batch_writer
        )
        _mock_table.batch_writer.return_value.__exit__ = MagicMock(return_value=False)

        service.delete_conversation("user-123", "conv-abc")

        # Verify query was called to collect message keys
        _mock_table.query.assert_called()
        call_kwargs = _mock_table.query.call_args[1]
        assert call_kwargs["ExpressionAttributeValues"][":pk"] == "CONV#conv-abc"
        assert call_kwargs["ExpressionAttributeValues"][":sk_prefix"] == "MSG#"

    def test_batch_deletes_messages(self, service):
        """delete_conversation uses batch_writer to delete messages."""
        _mock_table.get_item.return_value = {
            "Item": {"PK": "USER#user-123", "SK": "CONV#conv-abc"}
        }
        _mock_table.query.return_value = {
            "Items": [
                {"PK": "CONV#conv-abc", "SK": "MSG#2025-01-15T10:30:00Z#msg-001"},
                {"PK": "CONV#conv-abc", "SK": "MSG#2025-01-15T10:31:00Z#msg-002"},
            ]
        }
        _mock_batch_writer = MagicMock()
        _mock_table.batch_writer.return_value.__enter__ = MagicMock(
            return_value=_mock_batch_writer
        )
        _mock_table.batch_writer.return_value.__exit__ = MagicMock(return_value=False)

        service.delete_conversation("user-123", "conv-abc")

        # batch_writer should be used
        _mock_table.batch_writer.assert_called()
        # delete_item should be called for each message
        assert _mock_batch_writer.delete_item.call_count == 2

    def test_deletes_metadata_item(self, service):
        """delete_conversation deletes the conversation metadata item."""
        _mock_table.get_item.return_value = {
            "Item": {"PK": "USER#user-123", "SK": "CONV#conv-abc"}
        }
        _mock_table.query.return_value = {"Items": []}
        _mock_batch_writer = MagicMock()
        _mock_table.batch_writer.return_value.__enter__ = MagicMock(
            return_value=_mock_batch_writer
        )
        _mock_table.batch_writer.return_value.__exit__ = MagicMock(return_value=False)

        service.delete_conversation("user-123", "conv-abc")

        _mock_table.delete_item.assert_called_once_with(
            Key={"PK": "USER#user-123", "SK": "CONV#conv-abc"}
        )

    def test_returns_true_when_conversation_not_found(self, service):
        """delete_conversation returns True when conversation doesn't exist (idempotent)."""
        _mock_table.get_item.return_value = {}

        result = service.delete_conversation("user-123", "conv-nonexistent")

        assert result is True
        # Should not attempt to query or delete messages
        _mock_table.query.assert_not_called()
        _mock_table.delete_item.assert_not_called()

    def test_returns_true_on_successful_delete(self, service):
        """delete_conversation returns True on successful deletion."""
        _mock_table.get_item.return_value = {
            "Item": {"PK": "USER#user-123", "SK": "CONV#conv-abc"}
        }
        _mock_table.query.return_value = {"Items": []}
        _mock_batch_writer = MagicMock()
        _mock_table.batch_writer.return_value.__enter__ = MagicMock(
            return_value=_mock_batch_writer
        )
        _mock_table.batch_writer.return_value.__exit__ = MagicMock(return_value=False)

        result = service.delete_conversation("user-123", "conv-abc")

        assert result is True


# ===========================================================================
# 7.3 — Update tests
# ===========================================================================


class TestUpdateConversation:
    """Test update_conversation verifies ownership and updates item.

    Validates: Requirement 3.7
    """

    def test_calls_get_item_for_ownership_check(self, service):
        """update_conversation calls get_item to verify ownership."""
        _mock_table.get_item.return_value = {
            "Item": {"PK": "USER#user-123", "SK": "CONV#conv-abc"}
        }

        service.update_conversation("user-123", "conv-abc", "New Title")

        _mock_table.get_item.assert_called_once_with(
            Key={"PK": "USER#user-123", "SK": "CONV#conv-abc"}
        )

    def test_calls_update_item_with_new_title(self, service):
        """update_conversation calls update_item with the new title."""
        _mock_table.get_item.return_value = {
            "Item": {"PK": "USER#user-123", "SK": "CONV#conv-abc"}
        }

        service.update_conversation("user-123", "conv-abc", "New Title")

        _mock_table.update_item.assert_called_once()
        call_kwargs = _mock_table.update_item.call_args[1]
        assert call_kwargs["ExpressionAttributeValues"][":title"] == "New Title"

    def test_calls_update_item_with_updated_at(self, service):
        """update_conversation calls update_item with updated_at timestamp."""
        _mock_table.get_item.return_value = {
            "Item": {"PK": "USER#user-123", "SK": "CONV#conv-abc"}
        }

        service.update_conversation("user-123", "conv-abc", "New Title")

        call_kwargs = _mock_table.update_item.call_args[1]
        assert ":updated_at" in call_kwargs["ExpressionAttributeValues"]
        # Verify it's an ISO timestamp format
        updated_at = call_kwargs["ExpressionAttributeValues"][":updated_at"]
        assert "T" in updated_at
        assert updated_at.endswith("Z")

    def test_raises_lookup_error_when_conversation_not_found(self, service):
        """update_conversation raises LookupError when conversation doesn't exist."""
        _mock_table.get_item.return_value = {}

        with pytest.raises(LookupError, match="Conversation not found"):
            service.update_conversation("user-123", "conv-abc", "New Title")

    def test_returns_updated_conversation_details(self, service):
        """update_conversation returns dict with conversation_id, title, updated_at."""
        _mock_table.get_item.return_value = {
            "Item": {"PK": "USER#user-123", "SK": "CONV#conv-abc"}
        }

        result = service.update_conversation("user-123", "conv-abc", "New Title")

        assert result["conversation_id"] == "conv-abc"
        assert result["title"] == "New Title"
        assert "updated_at" in result


class TestAutoRenameConversation:
    """Test auto_rename_conversation builds a transcript, calls the generator, and persists.

    Validates: auto-rename feature.
    """

    def _make_generator(self, title="Generated Title"):
        gen = MagicMock()
        gen.generate_title.return_value = title
        return gen

    def test_raises_when_no_generator_configured(self, service):
        """auto_rename_conversation raises RuntimeError if no generator is set."""
        service.title_generator = None
        with pytest.raises(RuntimeError, match="Title generator is not configured"):
            service.auto_rename_conversation("user-123", "conv-abc")

    def test_raises_lookup_error_when_conversation_not_found(self, service):
        """auto_rename_conversation raises LookupError when conversation doesn't exist."""
        service.title_generator = self._make_generator()
        _mock_table.get_item.return_value = {}

        with pytest.raises(LookupError, match="Conversation not found"):
            service.auto_rename_conversation("user-123", "conv-abc")

    def test_raises_value_error_when_no_dialogue(self, service):
        """auto_rename_conversation raises ValueError when there is no usable dialogue."""
        service.title_generator = self._make_generator()
        _mock_table.get_item.return_value = {
            "Item": {"PK": "USER#user-123", "SK": "CONV#conv-abc"}
        }
        # Only non-dialogue events present
        _mock_table.query.return_value = {
            "Items": [
                {"role": "tool_call", "content": "{}"},
                {"role": "tool_result", "content": "{}"},
            ]
        }

        with pytest.raises(ValueError, match="no messages to summarize"):
            service.auto_rename_conversation("user-123", "conv-abc")

    def test_transcript_includes_only_user_and_assistant_turns(self, service):
        """The transcript passed to the generator includes only user/assistant turns."""
        service.title_generator = self._make_generator()
        _mock_table.get_item.return_value = {
            "Item": {"PK": "USER#user-123", "SK": "CONV#conv-abc"}
        }
        _mock_table.query.return_value = {
            "Items": [
                {"role": "user", "content": "How do I center a div?"},
                {"role": "tool_call", "content": "{}"},
                {"role": "assistant", "content": "Use flexbox."},
            ]
        }

        service.auto_rename_conversation("user-123", "conv-abc")

        transcript = service.title_generator.generate_title.call_args[0][0]
        assert "User: How do I center a div?" in transcript
        assert "Assistant: Use flexbox." in transcript
        assert "tool_call" not in transcript

    def test_persists_generated_title_with_update_item(self, service):
        """auto_rename_conversation persists the generated title via update_item."""
        service.title_generator = self._make_generator("Centering a div with flexbox")
        _mock_table.get_item.return_value = {
            "Item": {"PK": "USER#user-123", "SK": "CONV#conv-abc"}
        }
        _mock_table.query.return_value = {
            "Items": [{"role": "user", "content": "How do I center a div?"}]
        }

        result = service.auto_rename_conversation("user-123", "conv-abc")

        _mock_table.update_item.assert_called_once()
        call_kwargs = _mock_table.update_item.call_args[1]
        assert call_kwargs["ExpressionAttributeValues"][":title"] == "Centering a div with flexbox"
        assert call_kwargs["Key"] == {"PK": "USER#user-123", "SK": "CONV#conv-abc"}
        assert result["title"] == "Centering a div with flexbox"
        assert result["conversation_id"] == "conv-abc"
        assert "updated_at" in result


# ===========================================================================
# 7.4 — Pagination tests
# ===========================================================================


class TestPagination:
    """Test pagination for list_conversations and get_messages.

    Validates: Requirement 3.3, 3.4 (pagination support)
    """

    def test_list_conversations_returns_next_token_when_last_evaluated_key(self, service):
        """list_conversations returns next_token when DynamoDB has LastEvaluatedKey."""
        last_key = {"PK": "USER#user-123", "SK": "CONV#conv-abc"}
        _mock_table.query.return_value = {
            "Items": [
                {
                    "conversation_id": "conv-abc",
                    "title": "Chat",
                    "created_at": "2025-01-15T10:30:00Z",
                    "updated_at": "2025-01-15T10:30:00Z",
                    "user_id": "user-123",
                }
            ],
            "LastEvaluatedKey": last_key,
        }

        result = service.list_conversations("user-123")

        assert result["next_token"] is not None
        # Verify it's a valid base64-encoded JSON of the last key
        decoded = json.loads(base64.b64decode(result["next_token"]).decode("utf-8"))
        assert decoded == last_key

    def test_list_conversations_sets_exclusive_start_key_from_next_token(self, service):
        """list_conversations sets ExclusiveStartKey when next_token is provided."""
        last_key = {"PK": "USER#user-123", "SK": "CONV#conv-abc"}
        next_token = base64.b64encode(json.dumps(last_key).encode("utf-8")).decode("utf-8")
        _mock_table.query.return_value = {"Items": []}

        service.list_conversations("user-123", next_token=next_token)

        call_kwargs = _mock_table.query.call_args[1]
        assert call_kwargs["ExclusiveStartKey"] == last_key

    def test_get_messages_returns_next_token_when_last_evaluated_key(self, service):
        """get_messages returns next_token when DynamoDB has LastEvaluatedKey."""
        _mock_table.get_item.return_value = {
            "Item": {"PK": "USER#user-123", "SK": "CONV#conv-abc"}
        }
        last_key = {"PK": "CONV#conv-abc", "SK": "MSG#2025-01-15T10:30:00Z#msg-001"}
        _mock_table.query.return_value = {
            "Items": [
                {
                    "message_id": "msg-001",
                    "role": "user",
                    "content": "Hello",
                    "created_at": "2025-01-15T10:30:00Z",
                    "conversation_id": "conv-abc",
                    "user_id": "user-123",
                }
            ],
            "LastEvaluatedKey": last_key,
        }

        result = service.get_messages("user-123", "conv-abc")

        assert result["next_token"] is not None
        decoded = json.loads(base64.b64decode(result["next_token"]).decode("utf-8"))
        assert decoded == last_key

    def test_get_messages_sets_exclusive_start_key_from_next_token(self, service):
        """get_messages sets ExclusiveStartKey when next_token is provided."""
        _mock_table.get_item.return_value = {
            "Item": {"PK": "USER#user-123", "SK": "CONV#conv-abc"}
        }
        last_key = {"PK": "CONV#conv-abc", "SK": "MSG#2025-01-15T10:30:00Z#msg-001"}
        next_token = base64.b64encode(json.dumps(last_key).encode("utf-8")).decode("utf-8")
        _mock_table.query.return_value = {"Items": []}

        service.get_messages("user-123", "conv-abc", next_token=next_token)

        call_kwargs = _mock_table.query.call_args[1]
        assert call_kwargs["ExclusiveStartKey"] == last_key
