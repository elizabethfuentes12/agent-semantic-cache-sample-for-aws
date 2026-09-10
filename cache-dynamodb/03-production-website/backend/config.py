# SSM Parameter Names — /dynamodb-cache/ prefix avoids conflicts with SemanticCacheWebBackendStack
APPSYNC_HTTP_ENDPOINT_PARAM_NAME   = "/dynamodb-cache/appsync/http_endpoint"
APPSYNC_REALTIME_ENDPOINT_PARAM_NAME = "/dynamodb-cache/appsync/realtime_endpoint"
APPSYNC_API_KEY_PARAM_NAME         = "/dynamodb-cache/appsync/api_key"
MEDIA_SESSIONS_BUCKET_PARAM_NAME   = "/dynamodb-cache/bucket/media_sessions"
CHAT_MESSAGES_TABLE_PARAM_NAME     = "/dynamodb-cache/table/chat_messages"

# SSM param that holds the cache-inventory Lambda function name (from 01-cache-layers-dynamodb)
CACHE_INVENTORY_FUNCTION_PARAM_NAME = "/dynamodb-cache/cache-inventory-function-name"

# Shared Constants
RESPONSE_NAMESPACE = "response/"

# Model used by the chat history Lambda to auto-generate conversation titles.
TITLE_MODEL_ID = "global.anthropic.claude-haiku-4-5-20251001-v1:0"

# Cognito Configuration
COGNITO_USER_POOL_ID = None
