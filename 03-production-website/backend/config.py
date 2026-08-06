# SSM Parameter Names
APPSYNC_HTTP_ENDPOINT_PARAM_NAME = "/semantic-cache/appsync/http_endpoint"
APPSYNC_REALTIME_ENDPOINT_PARAM_NAME = "/semantic-cache/appsync/realtime_endpoint"
APPSYNC_API_KEY_PARAM_NAME = "/semantic-cache/appsync/api_key"
MEDIA_SESSIONS_BUCKET_PARAM_NAME = "/semantic-cache/bucket/media_sessions"
CHAT_MESSAGES_TABLE_PARAM_NAME = "/semantic-cache/table/chat_messages"

# Shared Constants
RESPONSE_NAMESPACE = "response/"

# Model used by the chat history Lambda to auto-generate conversation titles.
# Any Bedrock model/inference-profile id that supports the Converse API works.
TITLE_MODEL_ID = "global.anthropic.claude-haiku-4-5-20251001-v1:0"

# Cognito Configuration
# Set to an existing User Pool ID to reuse it, or None to have the stack
# CREATE its own user pool (recommended for a fresh deployment).
COGNITO_USER_POOL_ID = None
