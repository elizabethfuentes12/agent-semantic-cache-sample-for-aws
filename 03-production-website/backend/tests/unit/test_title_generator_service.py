"""Tests for title_generator_service module.

Covers output sanitization and the Bedrock Converse invocation contract.
"""

import importlib.util
import os
import sys
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Mock boto3 before importing, since the module calls
# boto3.client("bedrock-runtime") at init time.
# ---------------------------------------------------------------------------
_mock_boto3 = MagicMock()
_mock_client = MagicMock()
_mock_boto3.client.return_value = _mock_client

_original_boto3 = sys.modules.get("boto3")
sys.modules["boto3"] = _mock_boto3

_MODULE_DIR = os.path.join(
    os.path.dirname(__file__), "..", "..", "lambdas", "code", "chat_history"
)
_MODULE_PATH = os.path.join(_MODULE_DIR, "title_generator_service.py")

_spec = importlib.util.spec_from_file_location("title_generator_service", _MODULE_PATH)
title_generator_service = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(title_generator_service)

if _original_boto3 is not None:
    sys.modules["boto3"] = _original_boto3
else:
    del sys.modules["boto3"]


def _make_converse_response(text):
    return {"output": {"message": {"content": [{"text": text}]}}}


@pytest.fixture(autouse=True)
def _reset():
    _mock_client.reset_mock()


@pytest.fixture
def gen():
    svc = title_generator_service.TitleGeneratorService("model-x")
    svc._client = _mock_client
    return svc


class TestSanitize:
    def test_strips_surrounding_quotes(self):
        assert title_generator_service.TitleGeneratorService._sanitize('"Hello World"') == "Hello World"

    def test_takes_first_non_empty_line(self):
        assert title_generator_service.TitleGeneratorService._sanitize("\n\nTitle Here\nignored") == "Title Here"

    def test_strips_trailing_punctuation(self):
        assert title_generator_service.TitleGeneratorService._sanitize("A title.") == "A title"

    def test_caps_length(self):
        long = "word " * 40
        result = title_generator_service.TitleGeneratorService._sanitize(long)
        assert len(result) <= title_generator_service.MAX_TITLE_CHARS


class TestGenerateTitle:
    def test_empty_transcript_raises(self, gen):
        with pytest.raises(ValueError):
            gen.generate_title("   ")

    def test_returns_sanitized_title(self, gen):
        _mock_client.converse.return_value = _make_converse_response('"My Great Chat"')
        assert gen.generate_title("User: hi\nAssistant: hello") == "My Great Chat"

    def test_uses_default_model_id(self, gen):
        _mock_client.converse.return_value = _make_converse_response("Title")
        gen.generate_title("User: hi")
        assert _mock_client.converse.call_args[1]["modelId"] == "model-x"

    def test_per_request_model_override(self, gen):
        _mock_client.converse.return_value = _make_converse_response("Title")
        gen.generate_title("User: hi", model_id="model-y")
        assert _mock_client.converse.call_args[1]["modelId"] == "model-y"

    def test_empty_model_output_raises(self, gen):
        _mock_client.converse.return_value = _make_converse_response("")
        with pytest.raises(RuntimeError):
            gen.generate_title("User: hi")
