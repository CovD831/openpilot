from __future__ import annotations

import pytest
from pydantic import ValidationError

from core.config import LLMSettings
from autonomous_iteration.intelligent_autopilot import IntelligentAutopilot


class _ConfiguredLLM:
    def __init__(self, settings: LLMSettings) -> None:
        self.settings = settings

    def complete(self, request):  # pragma: no cover - construction only
        raise AssertionError(f"provider must not be called during construction: {request}")


def test_rolling_summary_settings_are_default_off_and_bounded() -> None:
    settings = LLMSettings()

    assert settings.rolling_summary_enabled is False
    assert settings.rolling_summary_token_limit == 256
    assert settings.provider_context_window_tokens is None
    assert settings.provider_max_output_tokens is None
    assert settings.context_soft_limit_ratio == 0.7
    assert settings.context_safety_reserve_tokens == 1_024


def test_provider_budget_settings_parse_typed_environment_values(monkeypatch) -> None:
    monkeypatch.setenv("OPENPILOT_LLM_CONTEXT_WINDOW_TOKENS", "1000000")
    monkeypatch.setenv("OPENPILOT_LLM_MAX_OUTPUT_TOKENS", "128000")
    monkeypatch.setenv("OPENPILOT_CONTEXT_SOFT_LIMIT_RATIO", "0.75")
    monkeypatch.setenv("OPENPILOT_CONTEXT_SAFETY_RESERVE_TOKENS", "20000")

    settings = LLMSettings()

    assert settings.provider_context_window_tokens == 1_000_000
    assert settings.provider_max_output_tokens == 128_000
    assert settings.context_soft_limit_ratio == 0.75
    assert settings.context_safety_reserve_tokens == 20_000


@pytest.mark.parametrize("value", ["0", "1.01"])
def test_context_soft_limit_ratio_rejects_invalid_values(value: str) -> None:
    with pytest.raises(ValidationError):
        LLMSettings(OPENPILOT_CONTEXT_SOFT_LIMIT_RATIO=value)


def test_rolling_summary_settings_parse_typed_environment_values(monkeypatch) -> None:
    monkeypatch.setenv("OPENPILOT_ROLLING_SUMMARY_ENABLED", "true")
    monkeypatch.setenv("OPENPILOT_ROLLING_SUMMARY_TOKEN_LIMIT", "512")

    settings = LLMSettings()

    assert settings.rolling_summary_enabled is True
    assert settings.rolling_summary_token_limit == 512


@pytest.mark.parametrize("value", ["0", "-1", "4097"])
def test_rolling_summary_token_limit_rejects_out_of_range_values(value: str) -> None:
    with pytest.raises(ValidationError):
        LLMSettings(OPENPILOT_ROLLING_SUMMARY_TOKEN_LIMIT=value)


def test_intelligent_autopilot_injects_factory_only_when_flag_is_enabled(tmp_path) -> None:
    settings = LLMSettings(
        api_key="test-key",
        base_url="https://api.example.test/v1",
        model="unknown-model",
        rolling_summary_enabled=True,
        rolling_summary_token_limit=384,
    )
    autopilot = IntelligentAutopilot(
        _ConfiguredLLM(settings),
        log_file=tmp_path / "autopilot.jsonl",
        skill_roots=[tmp_path / "missing-skills"],
    )

    builder = autopilot.memory_context_builder
    assert builder is not None
    assert builder.rolling_summary_enabled is True
    assert builder.rolling_summary_token_limit == 384
    assert builder.rolling_summary_adapter is not None
    assert builder.rolling_summary_request_factory is not None


def test_intelligent_autopilot_default_keeps_factory_disabled(tmp_path) -> None:
    settings = LLMSettings(
        api_key="test-key",
        base_url="https://api.example.test/v1",
        model="unknown-model",
    )
    autopilot = IntelligentAutopilot(
        _ConfiguredLLM(settings),
        log_file=tmp_path / "autopilot.jsonl",
        skill_roots=[tmp_path / "missing-skills"],
    )

    builder = autopilot.memory_context_builder
    assert builder is not None
    assert builder.rolling_summary_enabled is False
    assert builder.rolling_summary_adapter is None
    assert builder.rolling_summary_request_factory is None
