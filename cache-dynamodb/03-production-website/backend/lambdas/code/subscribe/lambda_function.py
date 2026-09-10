"""Subscribe handler for the AppSync Events 'response' channel namespace.

Validates that the authenticated Cognito user is only subscribing to
channels that belong to them. The user_id is extracted from the Cognito
identity claims and compared against the channel path.

For the 'response' namespace, the channel path received by this handler is:
    /response/{namespace}/{user_id}/{session_id}/{event_id}

AppSync Events subscribe handler contract (direct Lambda integration):
- Return None to ALLOW the subscription.
- Return {"error": "message"} to DENY the subscription.
"""

import logging

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def lambda_handler(event, context):
    """Validate subscription requests based on Cognito user identity.

    Args:
        event: AppSync Events subscribe invocation payload.
        context: Lambda execution context.

    Returns:
        None to allow the subscription, or {"error": "..."} to deny.
    """
    try:
        logger.info("Subscribe event: %s", _safe_log(event))

        # Extract identity from the event
        identity = event.get("identity")

        # If no identity (API_KEY auth without Cognito), allow the subscription
        if not identity:
            logger.info("No identity (API_KEY auth) — allowing subscription")
            return None

        # Get the Cognito user sub (user_id)
        cognito_sub = identity.get("sub")
        if not cognito_sub:
            claims = identity.get("claims", {})
            cognito_sub = claims.get("sub")

        # If authenticated but no sub claim, allow (non-Cognito auth)
        if not cognito_sub:
            logger.info("Identity present but no sub claim — allowing subscription")
            return None

        # Extract channel path
        channel_path = event.get("info", {}).get("channel", {}).get("path", "")
        channel_path = channel_path.lstrip("/")

        logger.info(
            "Subscribe request: user=%s channel=%s", cognito_sub, channel_path
        )

        # Extract user_id from channel path
        channel_user_id = _extract_user_id_from_channel(channel_path)

        if not channel_user_id:
            # If we can't parse a user_id from the path, allow it
            logger.info(
                "Could not extract user_id from channel path: %s — allowing",
                channel_path,
            )
            return None

        # Validate the user owns this channel
        if channel_user_id != cognito_sub:
            logger.warning(
                "User %s attempted to subscribe to channel owned by %s",
                cognito_sub, channel_user_id,
            )
            return {"error": f"Unauthorized: channel does not belong to user {cognito_sub}"}

        logger.info("Subscribe authorized for user %s on %s", cognito_sub, channel_path)
        return None

    except Exception:
        logger.exception("Unhandled error in subscribe handler")
        return {"error": "Internal server error"}


def _extract_user_id_from_channel(channel_path):
    """Extract the user_id segment from a channel path.

    The channel path for the 'response' namespace is:
        response/messages/{user_id}/{session_id}/{event_id}
        response/{sub_namespace}/{user_id}/...

    Without the namespace prefix (if AppSync strips it):
        messages/{user_id}/{session_id}/{event_id}
        {sub_namespace}/{user_id}/...

    Args:
        channel_path: The channel path string (without leading slash).

    Returns:
        The user_id string, or None if it cannot be extracted.
    """
    parts = channel_path.split("/")

    # Full path: response/{sub_namespace}/{user_id}/...
    if len(parts) >= 3 and parts[0] == "response":
        return parts[2]

    # Stripped path: {sub_namespace}/{user_id}/...
    if len(parts) >= 2 and parts[0] != "response":
        return parts[1]

    return None


def _safe_log(event):
    """Create a safe-to-log summary of the event (no sensitive data)."""
    return {
        "identity_present": "identity" in event,
        "identity_type": type(event.get("identity")).__name__ if event.get("identity") else None,
        "info": event.get("info"),
    }
