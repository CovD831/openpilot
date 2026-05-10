import pytest

from openpilot.config import LLMSettings
from openpilot.exceptions import MissingAPIKeyError


def test_config_loads_from_env(monkeypatch):
    monkeypatch.setenv("OPENPILOT_LLM_BASE_URL", "https://example.test/v1")
    monkeypatch.setenv("OPENPILOT_LLM_API_KEY", "test-key")
    monkeypatch.setenv("OPENPILOT_LLM_MODEL", "test-model")

    settings = LLMSettings()

    assert settings.base_url == "https://example.test/v1"
    assert settings.api_key == "test-key"
    assert settings.model == "test-model"
    settings.require_ready()


def test_config_rejects_missing_api_key(monkeypatch):
    monkeypatch.delenv("OPENPILOT_LLM_API_KEY", raising=False)

    settings = LLMSettings(api_key=None)

    with pytest.raises(MissingAPIKeyError):
        settings.require_ready()


def test_missing_fields_detects_missing_api_key():
    settings = LLMSettings(api_key=None)

    assert "OPENPILOT_LLM_API_KEY" in settings.missing_fields()
    assert settings.is_ready() is False


def test_missing_fields_detects_blank_base_url():
    settings = LLMSettings(base_url=" ", api_key="test-key")

    assert "OPENPILOT_LLM_BASE_URL" in settings.missing_fields()
    assert settings.is_ready() is False


