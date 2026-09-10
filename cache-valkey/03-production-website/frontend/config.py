# config.py

# Frontend build
FRONTEND_SOURCE_DIR = "dashboard"
WEBSITE_ASSETS_PATH = "dashboard/dist"
FRONTEND_BUILD_COMMAND = "bash build.sh"

# S3 deployment
DESTINATION_KEY_PREFIX = ""

# CloudFront
DEFAULT_ROOT_OBJECT = "index.html"
INVALIDATION_PATHS = ["/index.html"]
PRICE_CLASS = "PRICE_CLASS_100"
HTTP_VERSION = "HTTP2"
VIEWER_PROTOCOL_POLICY = "REDIRECT_TO_HTTPS"

# SPA error responses
SPA_ERROR_RESPONSES = [
    {
        "http_status": 403,
        "response_http_status": 200,
        "response_page_path": "/index.html",
        "ttl_seconds": 0,
    },
    {
        "http_status": 404,
        "response_http_status": 200,
        "response_page_path": "/index.html",
        "ttl_seconds": 0,
    },
]

# SSM parameter names
DISTRIBUTION_DOMAIN_PARAM_NAME = "/cloudfront/distribution-domain"
DISTRIBUTION_ID_PARAM_NAME = "/cloudfront/distribution-id"
SITE_BUCKET_PARAM_NAME = "/s3/site-bucket"
AGENTS_WEBSITE_PARAM_NAME = "/agents/website"
MODELS_WEBSITE_PARAM_NAME = "/models/website"
