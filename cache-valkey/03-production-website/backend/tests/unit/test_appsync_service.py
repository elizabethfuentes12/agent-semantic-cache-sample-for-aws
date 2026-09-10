"""Tests for appsync_service module (lambdas/code/publish/appsync_service.py).

Validates: Requirements 4.2, 4.3, 4.4, 4.5, 4.6, 4.7
"""

import importlib.util
import json
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Import appsync_service via importlib.util with sys.path manipulation
# (same pattern as test_config_service.py).
# ---------------------------------------------------------------------------
_MODULE_DIR = os.path.join(
    os.path.dirname(__file__), "..", "..", "lambdas", "code", "publish"
)
_MODULE_PATH = os.path.join(_MODULE_DIR, "appsync_service.py")

_spec = importlib.util.spec_from_file_location("appsync_service", _MODULE_PATH)
appsync_service = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(appsync_service)

AppsyncService = appsync_service.AppsyncService


# ---------------------------------------------------------------------------
# Property 4: HTTP request construction
# Feature: appsync-events-api, Property 4: HTTP request construction
# ---------------------------------------------------------------------------
class TestHttpRequestConstruction:
    """Verify POST URL, headers, and body for various input combinations.

    Validates: Requirements 4.2, 4.3, 4.4
    """

    @pytest.mark.parametrize(
        "endpoint, api_key, channel, events",
        [
            (
                "abc123.appsync-api.us-east-1.amazonaws.com",
                "da2-fakekey111",
                "messages/user1/session1",
                ['{"message": "hello"}'],
            ),
            (
                "xyz789.appsync-api.eu-west-1.amazonaws.com",
                "da2-fakekey222",
                "response/messages/user2/session2/evt-001",
                ['{"message": "world"}', '{"message": "foo"}'],
            ),
            (
                "endpoint.example.com",
                "key-with-special-chars!@#",
                "ch/deep/nested/path",
                ['{"data": "unicode: ñ é ü 日本語"}'],
            ),
            (
                "simple.endpoint",
                "simple-key",
                "single",
                ['{"msg": ""}'],
            ),
            (
                "multi.events.endpoint",
                "multi-key",
                "bulk/channel",
                ['{"a":1}', '{"b":2}', '{"c":3}'],
            ),
        ],
        ids=[
            "basic",
            "multi-event-eu-endpoint",
            "unicode-payload",
            "minimal-channel",
            "three-events",
        ],
    )
    @patch("urllib.request.urlopen")
    def test_request_url_headers_and_body(
        self, mock_urlopen, endpoint, api_key, channel, events
    ):
        """publish_event constructs correct POST URL, headers, and JSON body."""
        mock_response = MagicMock()
        mock_response.status = 200
        mock_urlopen.return_value = mock_response

        svc = AppsyncService(endpoint, api_key)
        svc.publish_event(channel, events)

        # Extract the Request object passed to urlopen
        call_args = mock_urlopen.call_args
        request_obj = call_args[0][0]

        # Verify URL
        assert request_obj.full_url == f"https://{endpoint}/event"

        # Verify method
        assert request_obj.method == "POST"

        # Verify headers
        assert request_obj.get_header("X-api-key") == api_key
        assert request_obj.get_header("Content-type") == "application/json"

        # Verify body
        body = json.loads(request_obj.data.decode("utf-8"))
        assert body["channel"] == channel
        assert body["events"] == events


# ---------------------------------------------------------------------------
# Property 5: Non-200 HTTP responses return False
# Feature: appsync-events-api, Property 5: Non-200 HTTP responses return False
# ---------------------------------------------------------------------------
class TestNon200ResponsesReturnFalse:
    """Verify that non-200 status codes cause publish_event to return False.

    Validates: Requirement 4.6
    """

    @pytest.mark.parametrize(
        "status_code",
        [400, 403, 404, 500, 502, 503],
        ids=["400", "403", "404", "500", "502", "503"],
    )
    @patch("urllib.request.urlopen")
    def test_non_200_returns_false(self, mock_urlopen, status_code):
        """publish_event returns False for any non-200 HTTP status code."""
        mock_response = MagicMock()
        mock_response.status = status_code
        mock_response.read.return_value = b"error body"
        mock_urlopen.return_value = mock_response

        svc = AppsyncService("test.endpoint", "test-key")
        result = svc.publish_event("some/channel", ['{"msg": "hi"}'])

        assert result is False


# ---------------------------------------------------------------------------
# Successful publish returns True
# ---------------------------------------------------------------------------
class TestSuccessfulPublish:
    """Verify that a 200 response causes publish_event to return True.

    Validates: Requirement 4.5
    """

    @patch("urllib.request.urlopen")
    def test_200_returns_true(self, mock_urlopen):
        """publish_event returns True when HTTP response status is 200."""
        mock_response = MagicMock()
        mock_response.status = 200
        mock_urlopen.return_value = mock_response

        svc = AppsyncService("ok.endpoint", "ok-key")
        result = svc.publish_event("channel/ok", ['{"msg": "success"}'])

        assert result is True


# ---------------------------------------------------------------------------
# Exception during HTTP request returns False
# ---------------------------------------------------------------------------
class TestExceptionReturnsFalse:
    """Verify that exceptions during HTTP request cause publish_event to return False.

    Validates: Requirement 4.7
    """

    @patch("urllib.request.urlopen")
    def test_urlopen_exception_returns_false(self, mock_urlopen):
        """publish_event returns False when urlopen raises an exception."""
        mock_urlopen.side_effect = Exception("Connection refused")

        svc = AppsyncService("bad.endpoint", "bad-key")
        result = svc.publish_event("channel/err", ['{"msg": "fail"}'])

        assert result is False
