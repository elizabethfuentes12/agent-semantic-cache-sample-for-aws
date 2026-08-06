"""Chat persistence service for saving messages to DynamoDB.

Provides fire-and-forget message persistence during the publish Lambda flow.
All methods log errors and return None on failure — they never raise exceptions.
"""

import logging
import uuid
from datetime import datetime, timezone

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)


class ChatPersistenceService:
    """Persists chat messages to DynamoDB during event processing."""

    def __init__(self, table_name: str):
        """Initialize with the DynamoDB table name.

        Args:
            table_name: The name of the ChatMessages DynamoDB table.
        """
        self._table = boto3.resource("dynamodb").Table(table_name)

    @staticmethod
    def _now_iso():
        """Return current UTC timestamp with millisecond precision for ordering."""
        now = datetime.now(timezone.utc)
        return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"

    def save_user_message(
        self, user_id: str, conversation_id: str, content: str, attachments=None
    ) -> dict:
        """Persist a user message to DynamoDB.

        Args:
            user_id: The Cognito user sub.
            conversation_id: The conversation UUID.
            content: The message text content.
            attachments: Optional list of normalized attachment dicts
                (``{"name", "url", "type", "size"}``) describing files the
                user attached to this message.

        Returns:
            A dict with message_id and created_at on success, or None on failure.
        """
        try:
            message_id = str(uuid.uuid4())
            created_at = self._now_iso()
            sk = f"MSG#{created_at}#{message_id}"

            item = {
                "PK": f"CONV#{conversation_id}",
                "SK": sk,
                "GSI1PK": f"CONV#{conversation_id}",
                "GSI1SK": sk,
                "user_id": user_id,
                "conversation_id": conversation_id,
                "message_id": message_id,
                "role": "user",
                "content": content,
                "created_at": created_at,
            }

            # Persist attachment metadata so the chip and re-download survive
            # a page reload / reopening the conversation.
            if attachments:
                item["attachments"] = attachments

            self._table.put_item(Item=item)
            logger.info("Saved user message %s to conversation %s", message_id, conversation_id)
            return {"message_id": message_id, "created_at": created_at}
        except Exception:
            logger.exception("Failed to save user message for conversation %s", conversation_id)
            return None

    def save_assistant_message(self, user_id: str, conversation_id: str, content: str) -> dict:
        """Persist an assistant response to DynamoDB.

        Also updates the conversation's updated_at field.

        Args:
            user_id: The Cognito user sub.
            conversation_id: The conversation UUID.
            content: The complete assistant answer text.

        Returns:
            A dict with message_id and created_at on success, or None on failure.
        """
        try:
            message_id = str(uuid.uuid4())
            created_at = self._now_iso()
            sk = f"MSG#{created_at}#{message_id}"

            item = {
                "PK": f"CONV#{conversation_id}",
                "SK": sk,
                "GSI1PK": f"CONV#{conversation_id}",
                "GSI1SK": sk,
                "user_id": user_id,
                "conversation_id": conversation_id,
                "message_id": message_id,
                "role": "assistant",
                "content": content,
                "created_at": created_at,
            }

            self._table.put_item(Item=item)

            # Update conversation's updated_at timestamp
            try:
                self._table.update_item(
                    Key={
                        "PK": f"USER#{user_id}",
                        "SK": f"CONV#{conversation_id}",
                    },
                    UpdateExpression="SET updated_at = :ts",
                    ExpressionAttributeValues={":ts": created_at},
                )
            except Exception:
                logger.warning(
                    "Failed to update conversation updated_at for %s", conversation_id
                )

            logger.info(
                "Saved assistant message %s to conversation %s", message_id, conversation_id
            )
            return {"message_id": message_id, "created_at": created_at}
        except Exception:
            logger.exception(
                "Failed to save assistant message for conversation %s", conversation_id
            )
            return None

    def save_event(self, user_id: str, conversation_id: str, event_data: dict) -> dict:
        """Persist an intermediate agent event (tool_call, tool_result, message) to DynamoDB.

        These events are stored with role="event" and the full event payload
        in the 'content' field as JSON, allowing the frontend to reconstruct
        the full agent reasoning trace.

        Args:
            user_id: The Cognito user sub.
            conversation_id: The conversation UUID.
            event_data: The event dict (e.g. {"type": "tool_call", "tool": "...", ...}).

        Returns:
            A dict with message_id and created_at on success, or None on failure.
        """
        try:
            import json
            message_id = str(uuid.uuid4())
            created_at = self._now_iso()
            sk = f"MSG#{created_at}#{message_id}"

            event_type = event_data.get("type", "unknown")

            item = {
                "PK": f"CONV#{conversation_id}",
                "SK": sk,
                "GSI1PK": f"CONV#{conversation_id}",
                "GSI1SK": sk,
                "user_id": user_id,
                "conversation_id": conversation_id,
                "message_id": message_id,
                "role": event_type,
                "content": json.dumps(event_data),
                "created_at": created_at,
            }

            self._table.put_item(Item=item)
            logger.info(
                "Saved %s event %s to conversation %s",
                event_type, message_id, conversation_id,
            )
            return {"message_id": message_id, "created_at": created_at}
        except Exception:
            logger.exception(
                "Failed to save %s event for conversation %s",
                event_data.get("type", "unknown"), conversation_id,
            )
            return None

    def ensure_conversation_exists(
        self, user_id: str, conversation_id: str, title: str | None = None,
        agent_arn: str | None = None, model_id: str | None = None,
    ) -> None:
        """Create a conversation metadata item if it doesn't already exist.

        Uses a conditional put_item with attribute_not_exists to avoid
        overwriting existing conversations. If the conversation already exists,
        updates the updated_at timestamp and refreshes agent_arn/model_id.

        Args:
            user_id: The Cognito user sub.
            conversation_id: The conversation UUID.
            title: Optional conversation title.
            agent_arn: Optional ARN of the agent handling this conversation.
            model_id: Optional model ID used for this conversation.
        """
        try:
            now = self._now_iso()
            item = {
                "PK": f"USER#{user_id}",
                "SK": f"CONV#{conversation_id}",
                "user_id": user_id,
                "conversation_id": conversation_id,
                "title": title or "New Conversation",
                "created_at": now,
                "updated_at": now,
            }
            if agent_arn:
                item["agent_arn"] = agent_arn
            if model_id:
                item["model_id"] = model_id

            self._table.put_item(
                Item=item,
                ConditionExpression="attribute_not_exists(PK)",
            )
            logger.info("Created conversation %s for user %s", conversation_id, user_id)
        except self._table.meta.client.exceptions.ConditionalCheckFailedException:
            # Conversation already exists — update updated_at and agent/model info
            try:
                now = self._now_iso()
                update_expr = "SET updated_at = :ts"
                expr_values = {":ts": now}
                if agent_arn:
                    update_expr += ", agent_arn = :arn"
                    expr_values[":arn"] = agent_arn
                if model_id:
                    update_expr += ", model_id = :mid"
                    expr_values[":mid"] = model_id

                self._table.update_item(
                    Key={
                        "PK": f"USER#{user_id}",
                        "SK": f"CONV#{conversation_id}",
                    },
                    UpdateExpression=update_expr,
                    ExpressionAttributeValues=expr_values,
                )
            except Exception:
                logger.warning(
                    "Failed to update updated_at for existing conversation %s",
                    conversation_id,
                )
        except Exception:
            logger.exception(
                "Failed to ensure conversation exists: %s", conversation_id
            )
