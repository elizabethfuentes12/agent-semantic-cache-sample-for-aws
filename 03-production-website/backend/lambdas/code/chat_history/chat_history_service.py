import base64
import json
import logging
import uuid
from datetime import datetime, timezone

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)


class ChatHistoryService:
    """CRUD operations for chat conversations and messages."""

    def __init__(self, table_name, title_generator=None):
        """Initialize with DynamoDB table name.

        Args:
            table_name: The name of the DynamoDB table.
            title_generator: Optional object exposing ``generate_title(transcript)``.
                Required only for the auto-rename operation.
        """
        dynamodb = boto3.resource("dynamodb")
        self.table = dynamodb.Table(table_name)
        self.title_generator = title_generator

    def list_conversations(self, user_id, limit=20, next_token=None):
        """List conversations for a user, ordered by most recent first.

        Args:
            user_id: The Cognito user sub.
            limit: Maximum number of conversations to return (default 20).
            next_token: Base64-encoded pagination token (optional).

        Returns:
            Dict with 'conversations' list and 'next_token' (or None).
        """
        query_params = {
            "KeyConditionExpression": "PK = :pk AND begins_with(SK, :sk_prefix)",
            "ExpressionAttributeValues": {
                ":pk": f"USER#{user_id}",
                ":sk_prefix": "CONV#",
            },
            "Limit": limit,
        }

        if next_token:
            try:
                exclusive_start_key = json.loads(
                    base64.b64decode(next_token).decode("utf-8")
                )
                query_params["ExclusiveStartKey"] = exclusive_start_key
            except (json.JSONDecodeError, ValueError, base64.binascii.Error):
                raise ValueError("Invalid pagination token")

        response = self.table.query(**query_params)

        conversations = []
        for item in response.get("Items", []):
            conv = {
                "conversation_id": item.get("conversation_id"),
                "title": item.get("title"),
                "created_at": item.get("created_at"),
                "updated_at": item.get("updated_at"),
                "user_id": item.get("user_id"),
            }
            if item.get("agent_arn"):
                conv["agent_arn"] = item["agent_arn"]
            if item.get("model_id"):
                conv["model_id"] = item["model_id"]
            conversations.append(conv)

        # Sort by updated_at descending
        conversations.sort(
            key=lambda c: c.get("updated_at") or "", reverse=True
        )

        result_next_token = None
        if "LastEvaluatedKey" in response:
            result_next_token = base64.b64encode(
                json.dumps(response["LastEvaluatedKey"]).encode("utf-8")
            ).decode("utf-8")

        return {
            "conversations": conversations,
            "next_token": result_next_token,
        }

    def get_messages(self, user_id, conversation_id, limit=50, next_token=None):
        """Get messages in a conversation, ordered chronologically.

        Verifies that the conversation belongs to the requesting user
        before returning messages.

        Args:
            user_id: The Cognito user sub.
            conversation_id: The conversation UUID.
            limit: Maximum number of messages to return (default 50).
            next_token: Base64-encoded pagination token (optional).

        Returns:
            Dict with 'messages' list and 'next_token' (or None).

        Raises:
            LookupError: If conversation not found or doesn't belong to user.
        """
        # Verify ownership
        conv_response = self.table.get_item(
            Key={
                "PK": f"USER#{user_id}",
                "SK": f"CONV#{conversation_id}",
            }
        )
        if "Item" not in conv_response:
            raise LookupError("Conversation not found")

        conv_item = conv_response["Item"]

        query_params = {
            "KeyConditionExpression": "PK = :pk AND begins_with(SK, :sk_prefix)",
            "ExpressionAttributeValues": {
                ":pk": f"CONV#{conversation_id}",
                ":sk_prefix": "MSG#",
            },
            "Limit": limit,
        }

        if next_token:
            try:
                exclusive_start_key = json.loads(
                    base64.b64decode(next_token).decode("utf-8")
                )
                query_params["ExclusiveStartKey"] = exclusive_start_key
            except (json.JSONDecodeError, ValueError, base64.binascii.Error):
                raise ValueError("Invalid pagination token")

        response = self.table.query(**query_params)

        messages = []
        for item in response.get("Items", []):
            message = {
                "message_id": item.get("message_id"),
                "role": item.get("role"),
                "content": item.get("content"),
                "created_at": item.get("created_at"),
                "conversation_id": item.get("conversation_id"),
                "user_id": item.get("user_id"),
            }
            # Surface any persisted attachment metadata so the frontend can
            # re-render the attachment chip and offer a re-download.
            if item.get("attachments"):
                message["attachments"] = item["attachments"]
            messages.append(message)

        result_next_token = None
        if "LastEvaluatedKey" in response:
            result_next_token = base64.b64encode(
                json.dumps(response["LastEvaluatedKey"]).encode("utf-8")
            ).decode("utf-8")

        result = {
            "messages": messages,
            "next_token": result_next_token,
        }
        if conv_item.get("agent_arn"):
            result["agent_arn"] = conv_item["agent_arn"]
        if conv_item.get("model_id"):
            result["model_id"] = conv_item["model_id"]

        return result

    def create_conversation(self, user_id, title=None):
        """Create a new conversation.

        Args:
            user_id: The Cognito user sub.
            title: Optional conversation title.

        Returns:
            Dict with 'conversation_id', 'title', 'created_at', 'updated_at'.
        """
        conversation_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        item = {
            "PK": f"USER#{user_id}",
            "SK": f"CONV#{conversation_id}",
            "user_id": user_id,
            "conversation_id": conversation_id,
            "title": title or "New Conversation",
            "created_at": now,
            "updated_at": now,
        }

        self.table.put_item(Item=item)

        return {
            "conversation_id": conversation_id,
            "title": item["title"],
            "created_at": now,
            "updated_at": now,
        }

    def delete_conversation(self, user_id, conversation_id):
        """Delete a conversation and all its messages.

        Verifies ownership before deleting. Idempotent — returns True
        if conversation doesn't exist.

        Args:
            user_id: The Cognito user sub.
            conversation_id: The conversation UUID.

        Returns:
            True if deletion succeeded or conversation didn't exist.
        """
        # Verify ownership
        conv_response = self.table.get_item(
            Key={
                "PK": f"USER#{user_id}",
                "SK": f"CONV#{conversation_id}",
            }
        )
        if "Item" not in conv_response:
            return True  # Already deleted — idempotent

        # Collect all message keys for this conversation
        all_keys = []
        query_params = {
            "KeyConditionExpression": "PK = :pk AND begins_with(SK, :sk_prefix)",
            "ExpressionAttributeValues": {
                ":pk": f"CONV#{conversation_id}",
                ":sk_prefix": "MSG#",
            },
            "ProjectionExpression": "PK, SK",
        }

        response = self.table.query(**query_params)
        all_keys.extend(response.get("Items", []))

        while "LastEvaluatedKey" in response:
            query_params["ExclusiveStartKey"] = response["LastEvaluatedKey"]
            response = self.table.query(**query_params)
            all_keys.extend(response.get("Items", []))

        # Batch delete messages
        with self.table.batch_writer() as batch:
            for key in all_keys:
                batch.delete_item(Key={"PK": key["PK"], "SK": key["SK"]})

        # Delete conversation metadata item
        self.table.delete_item(
            Key={
                "PK": f"USER#{user_id}",
                "SK": f"CONV#{conversation_id}",
            }
        )

        return True

    def update_conversation(self, user_id, conversation_id, title):
        """Update a conversation's title.

        Verifies ownership before updating.

        Args:
            user_id: The Cognito user sub.
            conversation_id: The conversation UUID.
            title: The new title for the conversation.

        Returns:
            Dict with updated conversation details.

        Raises:
            LookupError: If conversation not found or doesn't belong to user.
        """
        # Verify ownership
        conv_response = self.table.get_item(
            Key={
                "PK": f"USER#{user_id}",
                "SK": f"CONV#{conversation_id}",
            }
        )
        if "Item" not in conv_response:
            raise LookupError("Conversation not found")

        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        self.table.update_item(
            Key={
                "PK": f"USER#{user_id}",
                "SK": f"CONV#{conversation_id}",
            },
            UpdateExpression="SET title = :title, updated_at = :updated_at",
            ExpressionAttributeValues={
                ":title": title,
                ":updated_at": now,
            },
        )

        return {
            "conversation_id": conversation_id,
            "title": title,
            "updated_at": now,
        }

    def _build_transcript(self, conversation_id, max_messages=20):
        """Collect the conversation's user/assistant turns into a transcript.

        Only real dialogue turns (role ``user`` / ``assistant``) are included;
        intermediate tool_call / tool_result events are skipped since they add
        noise without helping title relevance. Messages are read in
        chronological order (SK begins_with MSG#) up to ``max_messages``.

        Args:
            conversation_id: The conversation UUID.
            max_messages: Maximum number of dialogue turns to include.

        Returns:
            A formatted transcript string (may be empty if no dialogue exists).
        """
        query_params = {
            "KeyConditionExpression": "PK = :pk AND begins_with(SK, :sk_prefix)",
            "ExpressionAttributeValues": {
                ":pk": f"CONV#{conversation_id}",
                ":sk_prefix": "MSG#",
            },
        }

        lines = []
        response = self.table.query(**query_params)
        items = response.get("Items", [])

        while len(items) < max_messages and "LastEvaluatedKey" in response:
            query_params["ExclusiveStartKey"] = response["LastEvaluatedKey"]
            response = self.table.query(**query_params)
            items.extend(response.get("Items", []))

        for item in items:
            role = item.get("role")
            if role not in ("user", "assistant"):
                continue
            content = item.get("content")
            if not isinstance(content, str) or not content.strip():
                continue
            speaker = "User" if role == "user" else "Assistant"
            lines.append(f"{speaker}: {content.strip()}")
            if len(lines) >= max_messages:
                break

        return "\n".join(lines)

    def auto_rename_conversation(self, user_id, conversation_id, max_messages=20):
        """Generate and persist a title based on the conversation's dialogue.

        Verifies ownership, builds a transcript from the conversation's
        user/assistant turns, asks the injected title generator for a
        suggested title, persists it, and returns the updated conversation.

        Args:
            user_id: The Cognito user sub.
            conversation_id: The conversation UUID.
            max_messages: Maximum number of dialogue turns to feed the model.

        Returns:
            Dict with 'conversation_id', 'title', and 'updated_at'.

        Raises:
            LookupError: If conversation not found or doesn't belong to user.
            RuntimeError: If no title generator is configured.
            ValueError: If the conversation has no usable dialogue yet.
        """
        if self.title_generator is None:
            raise RuntimeError("Title generator is not configured")

        # Verify ownership
        conv_response = self.table.get_item(
            Key={
                "PK": f"USER#{user_id}",
                "SK": f"CONV#{conversation_id}",
            }
        )
        if "Item" not in conv_response:
            raise LookupError("Conversation not found")

        transcript = self._build_transcript(conversation_id, max_messages=max_messages)
        if not transcript.strip():
            raise ValueError("Conversation has no messages to summarize")

        title = self.title_generator.generate_title(transcript)

        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        self.table.update_item(
            Key={
                "PK": f"USER#{user_id}",
                "SK": f"CONV#{conversation_id}",
            },
            UpdateExpression="SET title = :title, updated_at = :updated_at",
            ExpressionAttributeValues={
                ":title": title,
                ":updated_at": now,
            },
        )

        return {
            "conversation_id": conversation_id,
            "title": title,
            "updated_at": now,
        }
