import json
import logging
import os

import config_service
from chat_history_service import ChatHistoryService
from title_generator_service import TitleGeneratorService

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Resolve table name from SSM at cold start
TABLE_NAME = config_service.get_ssm_parameter(
    os.environ.get("CHAT_MESSAGES_TABLE_PARAM", "")
)

# Model used to auto-generate conversation titles.
TITLE_MODEL_ID = os.environ.get(
    "TITLE_MODEL_ID", "global.anthropic.claude-haiku-4-5-20251001-v1:0"
)

title_generator = TitleGeneratorService(TITLE_MODEL_ID)
chat_history_service = ChatHistoryService(TABLE_NAME, title_generator=title_generator)

VALID_ACTIONS = {
    "list_conversations",
    "get_messages",
    "create_conversation",
    "delete_conversation",
    "update_conversation",
    "auto_rename_conversation",
}

# Required parameters per action (beyond user_id which is always required)
ACTION_REQUIRED_PARAMS = {
    "list_conversations": [],
    "get_messages": ["conversation_id"],
    "create_conversation": [],
    "delete_conversation": ["conversation_id"],
    "update_conversation": ["conversation_id", "title"],
    "auto_rename_conversation": ["conversation_id"],
}


def _success_response(event_id, result):
    """Build an AppSync Events success response.

    Args:
        event_id: The incoming event ID from AppSync.
        result: The result dict to include in the payload.

    Returns:
        AppSync Events response with the result in the payload.
    """
    return {
        "events": [
            {
                "id": event_id,
                "payload": {
                    "statusCode": 200,
                    **result,
                },
            }
        ]
    }


def _error_response(event_id, status_code, message):
    """Build an AppSync Events error response.

    Args:
        event_id: The incoming event ID from AppSync.
        status_code: HTTP-style status code for the error.
        message: Error message string.

    Returns:
        AppSync Events response with error in the payload.
    """
    return {
        "events": [
            {
                "id": event_id,
                "payload": {
                    "statusCode": status_code,
                    "error": message,
                },
            }
        ]
    }


def lambda_handler(event, context):
    """Route chat history operations based on action field.

    Extracts the payload from the AppSync Events event, validates the
    action and required parameters, then delegates to ChatHistoryService.

    For direct Lambda integration with REQUEST_RESPONSE invoke type,
    the response must follow the AppSync Events format:
    {"events": [{"id": "<event_id>", "payload": {...}}]}

    Args:
        event: AppSync Events payload.
        context: Lambda execution context.

    Returns:
        AppSync Events formatted response dict.
    """
    event_id = None
    try:
        # Extract event ID and payload from AppSync Events format
        incoming_event = event["events"][0]
        event_id = incoming_event.get("id", "unknown")
        payload = incoming_event["payload"]

        action = payload.get("action")

        # Validate action
        if action not in VALID_ACTIONS:
            return _error_response(event_id, 400, f"Invalid action: {action}")

        # Validate user_id (required for all actions)
        user_id = payload.get("user_id")
        if not user_id:
            return _error_response(event_id, 400, "Missing required parameter: user_id")

        # Validate action-specific required parameters
        for param in ACTION_REQUIRED_PARAMS[action]:
            if not payload.get(param):
                return _error_response(event_id, 400, f"Missing required parameter: {param}")

        # Route to appropriate handler
        if action == "list_conversations":
            return _handle_list_conversations(event_id, payload, user_id)
        elif action == "get_messages":
            return _handle_get_messages(event_id, payload, user_id)
        elif action == "create_conversation":
            return _handle_create_conversation(event_id, payload, user_id)
        elif action == "delete_conversation":
            return _handle_delete_conversation(event_id, payload, user_id)
        elif action == "update_conversation":
            return _handle_update_conversation(event_id, payload, user_id)
        elif action == "auto_rename_conversation":
            return _handle_auto_rename_conversation(event_id, payload, user_id)

    except Exception:
        logger.exception("Unhandled error in chat history handler")
        eid = event_id or "unknown"
        return _error_response(eid, 500, "Internal server error")


def _handle_list_conversations(event_id, payload, user_id):
    """Handle list_conversations action."""
    limit = payload.get("limit", 20)
    next_token = payload.get("next_token")

    try:
        result = chat_history_service.list_conversations(
            user_id=user_id, limit=limit, next_token=next_token
        )
        return _success_response(event_id, result)
    except ValueError as e:
        return _error_response(event_id, 400, str(e))


def _handle_get_messages(event_id, payload, user_id):
    """Handle get_messages action."""
    conversation_id = payload.get("conversation_id")
    limit = payload.get("limit", 50)
    next_token = payload.get("next_token")

    try:
        result = chat_history_service.get_messages(
            user_id=user_id,
            conversation_id=conversation_id,
            limit=limit,
            next_token=next_token,
        )
        return _success_response(event_id, result)
    except LookupError:
        return _error_response(event_id, 404, "Conversation not found")
    except ValueError as e:
        return _error_response(event_id, 400, str(e))


def _handle_create_conversation(event_id, payload, user_id):
    """Handle create_conversation action."""
    title = payload.get("title")

    result = chat_history_service.create_conversation(
        user_id=user_id, title=title
    )
    return _success_response(event_id, result)


def _handle_delete_conversation(event_id, payload, user_id):
    """Handle delete_conversation action."""
    conversation_id = payload.get("conversation_id")

    try:
        result = chat_history_service.delete_conversation(
            user_id=user_id, conversation_id=conversation_id
        )
        return _success_response(event_id, {"deleted": result})
    except LookupError:
        return _error_response(event_id, 404, "Conversation not found")


def _handle_update_conversation(event_id, payload, user_id):
    """Handle update_conversation action."""
    conversation_id = payload.get("conversation_id")
    title = payload.get("title")

    try:
        result = chat_history_service.update_conversation(
            user_id=user_id, conversation_id=conversation_id, title=title
        )
        return _success_response(event_id, result)
    except LookupError:
        return _error_response(event_id, 404, "Conversation not found")


def _handle_auto_rename_conversation(event_id, payload, user_id):
    """Handle auto_rename_conversation action.

    Generates a title from the conversation's dialogue using a model,
    persists it, and returns the updated conversation.
    """
    conversation_id = payload.get("conversation_id")

    try:
        result = chat_history_service.auto_rename_conversation(
            user_id=user_id, conversation_id=conversation_id
        )
        return _success_response(event_id, result)
    except LookupError:
        return _error_response(event_id, 404, "Conversation not found")
    except ValueError as e:
        return _error_response(event_id, 400, str(e))
