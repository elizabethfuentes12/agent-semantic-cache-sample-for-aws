"""Tests for config.py constants and default values.

Validates: Requirements 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 1.9, 1.10, 1.11
"""

import re

import pytest

import config
from webhosting.web_hosting import (
    _PRICE_CLASS_MAP,
    _HTTP_VERSION_MAP,
    _VIEWER_PROTOCOL_MAP,
)


class TestConfigPathConstants:
    """Test path and build-related string constants."""

    def test_frontend_source_dir(self):
        assert config.FRONTEND_SOURCE_DIR == "ai-agent-frontend"
        assert isinstance(config.FRONTEND_SOURCE_DIR, str)

    def test_website_assets_path(self):
        assert config.WEBSITE_ASSETS_PATH == "ai-agent-frontend/dist"
        assert isinstance(config.WEBSITE_ASSETS_PATH, str)

    def test_frontend_build_command(self):
        assert config.FRONTEND_BUILD_COMMAND == "pnpm install --frozen-lockfile && pnpm build"
        assert isinstance(config.FRONTEND_BUILD_COMMAND, str)


class TestConfigDeploymentConstants:
    """Test S3 and CloudFront deployment constants."""

    def test_destination_key_prefix(self):
        assert config.DESTINATION_KEY_PREFIX == ""
        assert isinstance(config.DESTINATION_KEY_PREFIX, str)

    def test_default_root_object(self):
        assert config.DEFAULT_ROOT_OBJECT == "index.html"
        assert isinstance(config.DEFAULT_ROOT_OBJECT, str)

    def test_invalidation_paths(self):
        assert config.INVALIDATION_PATHS == ["/index.html"]
        assert isinstance(config.INVALIDATION_PATHS, list)


class TestConfigEnumConstants:
    """Test enum string constants are valid keys in their mapping dictionaries."""

    def test_price_class_default(self):
        assert config.PRICE_CLASS == "PRICE_CLASS_100"

    def test_price_class_in_map(self):
        assert config.PRICE_CLASS in _PRICE_CLASS_MAP

    def test_http_version_default(self):
        assert config.HTTP_VERSION == "HTTP2"

    def test_http_version_in_map(self):
        assert config.HTTP_VERSION in _HTTP_VERSION_MAP

    def test_viewer_protocol_policy_default(self):
        assert config.VIEWER_PROTOCOL_POLICY == "REDIRECT_TO_HTTPS"

    def test_viewer_protocol_policy_in_map(self):
        assert config.VIEWER_PROTOCOL_POLICY in _VIEWER_PROTOCOL_MAP


class TestSpaErrorResponses:
    """Test SPA_ERROR_RESPONSES entries contain required keys and correct values."""

    REQUIRED_KEYS = {"http_status", "response_http_status", "response_page_path", "ttl_seconds"}

    def test_is_list(self):
        assert isinstance(config.SPA_ERROR_RESPONSES, list)

    def test_has_entries(self):
        assert len(config.SPA_ERROR_RESPONSES) == 2

    @pytest.mark.parametrize("index", [0, 1])
    def test_entry_contains_required_keys(self, index):
        entry = config.SPA_ERROR_RESPONSES[index]
        assert self.REQUIRED_KEYS.issubset(entry.keys())

    def test_403_entry(self):
        entry = config.SPA_ERROR_RESPONSES[0]
        assert entry["http_status"] == 403
        assert entry["response_http_status"] == 200
        assert entry["response_page_path"] == "/index.html"
        assert entry["ttl_seconds"] == 0

    def test_404_entry(self):
        entry = config.SPA_ERROR_RESPONSES[1]
        assert entry["http_status"] == 404
        assert entry["response_http_status"] == 200
        assert entry["response_page_path"] == "/index.html"
        assert entry["ttl_seconds"] == 0


class TestSSMParameterNames:
    """Test SSM parameter name constants follow /<category>/<resource> pattern."""

    SSM_PATTERN = re.compile(r"^/[a-z0-9-]+/[a-z0-9-]+$")

    @pytest.mark.parametrize(
        "param_name,expected_value",
        [
            ("DISTRIBUTION_DOMAIN_PARAM_NAME", "/cloudfront/distribution-domain"),
            ("DISTRIBUTION_ID_PARAM_NAME", "/cloudfront/distribution-id"),
            ("SITE_BUCKET_PARAM_NAME", "/s3/site-bucket"),
        ],
    )
    def test_ssm_param_value(self, param_name, expected_value):
        value = getattr(config, param_name)
        assert value == expected_value

    @pytest.mark.parametrize(
        "param_name",
        [
            "DISTRIBUTION_DOMAIN_PARAM_NAME",
            "DISTRIBUTION_ID_PARAM_NAME",
            "SITE_BUCKET_PARAM_NAME",
        ],
    )
    def test_ssm_param_follows_pattern(self, param_name):
        value = getattr(config, param_name)
        assert self.SSM_PATTERN.match(value), (
            f"{param_name}='{value}' does not match /<category>/<resource> pattern"
        )
