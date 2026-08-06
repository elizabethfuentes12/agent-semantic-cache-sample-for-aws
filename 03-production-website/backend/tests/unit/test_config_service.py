"""Tests for config_service module (lambdas/code/publish/config_service.py).

Validates: Requirements 5.5, 5.6
"""

import importlib.util
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Mock boto3 before importing config_service, since the module calls
# boto3.client("ssm") at import time and boto3 is not installed in the
# test virtualenv.
# ---------------------------------------------------------------------------
_mock_boto3 = MagicMock()
_mock_ssm_client = MagicMock()
_mock_boto3.client.return_value = _mock_ssm_client

# Set up the ParameterNotFound exception class on the mock client
_mock_ssm_client.exceptions.ParameterNotFound = type(
    "ParameterNotFound", (Exception,), {}
)

sys.modules.setdefault("boto3", _mock_boto3)

# Import config_service via importlib.util with sys.path manipulation
_MODULE_DIR = os.path.join(
    os.path.dirname(__file__), "..", "..", "lambdas", "code", "publish"
)
_MODULE_PATH = os.path.join(_MODULE_DIR, "config_service.py")

_spec = importlib.util.spec_from_file_location("config_service", _MODULE_PATH)
config_service = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(config_service)


@pytest.fixture(autouse=True)
def _reset_mock():
    """Reset the mock SSM client before each test."""
    _mock_ssm_client.reset_mock()


class TestGetSsmParameterSuccess:
    """Test successful SSM parameter retrieval.

    Validates: Requirement 5.5
    """

    def test_returns_parameter_value(self):
        """get_ssm_parameter returns the value from SSM for a valid parameter name."""
        _mock_ssm_client.get_parameter.return_value = {
            "Parameter": {"Value": "https://example.appsync-api.amazonaws.com"}
        }

        result = config_service.get_ssm_parameter("/appsync/http_endpoint")

        assert result == "https://example.appsync-api.amazonaws.com"
        _mock_ssm_client.get_parameter.assert_called_once_with(
            Name="/appsync/http_endpoint", WithDecryption=True
        )

    def test_calls_ssm_with_decryption(self):
        """get_ssm_parameter always passes WithDecryption=True."""
        _mock_ssm_client.get_parameter.return_value = {
            "Parameter": {"Value": "some-api-key-value"}
        }

        config_service.get_ssm_parameter("/appsync/api_key")

        call_kwargs = _mock_ssm_client.get_parameter.call_args[1]
        assert call_kwargs["WithDecryption"] is True


class TestGetSsmParameterEmptyName:
    """Test that empty parameter names raise ValueError.

    Validates: Requirement 5.6
    """

    @pytest.mark.parametrize(
        "empty_value",
        [
            "",
            None,
        ],
        ids=["empty_string", "none"],
    )
    def test_empty_parameter_name_raises_value_error(self, empty_value):
        """get_ssm_parameter raises ValueError when parameter name is empty or None."""
        with pytest.raises(ValueError, match="must not be empty"):
            config_service.get_ssm_parameter(empty_value)

        # SSM should never be called for empty names
        _mock_ssm_client.get_parameter.assert_not_called()


class TestGetSsmParameterNotFound:
    """Test that ParameterNotFound from SSM raises ValueError.

    Validates: Requirement 5.6
    """

    def test_parameter_not_found_raises_value_error(self):
        """get_ssm_parameter raises ValueError when SSM parameter does not exist."""
        _mock_ssm_client.get_parameter.side_effect = (
            _mock_ssm_client.exceptions.ParameterNotFound(
                {"Error": {"Code": "ParameterNotFound"}}, "GetParameter"
            )
        )

        with pytest.raises(ValueError, match="SSM parameter not found"):
            config_service.get_ssm_parameter("/appsync/nonexistent")
