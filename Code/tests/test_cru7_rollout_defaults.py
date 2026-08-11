from __future__ import annotations

import prompt_toolkit

from autonomous_iteration.core_completion_handoff import (
    core_post_core_integration_enabled,
)
from core.tool_event_loop import model_visible_protocol_repair_enabled
from ui import enhanced_cli


class _Console:
    def __init__(self) -> None:
        self.messages: list[str] = []

    def print(self, *args, **_kwargs) -> None:
        self.messages.append(" ".join(str(arg) for arg in args))


class _UI:
    def __init__(self) -> None:
        self.console = _Console()


class _Tracker:
    def __init__(self) -> None:
        self.stopped = False

    def start_tracking(self) -> None:
        return None

    def stop_tracking(self) -> None:
        self.stopped = True


def test_accepted_core_flags_default_on_with_explicit_rollback_switches(
    monkeypatch,
) -> None:
    monkeypatch.delenv("OPENPILOT_UNIFIED_AUTONOMOUS_ENTRY_ENABLED", raising=False)
    monkeypatch.delenv("OPENPILOT_GOVERNED_DECOMPOSITION", raising=False)
    monkeypatch.delenv("OPENPILOT_MODEL_VISIBLE_PROTOCOL_REPAIR", raising=False)
    monkeypatch.delenv("OPENPILOT_CORE_POST_CORE_INTEGRATION", raising=False)

    assert enhanced_cli._unified_autonomous_entry_enabled() is True
    assert enhanced_cli._governed_decomposition_enabled() is True
    assert model_visible_protocol_repair_enabled() is False
    assert core_post_core_integration_enabled() is False

    monkeypatch.setenv("OPENPILOT_UNIFIED_AUTONOMOUS_ENTRY_ENABLED", "false")
    monkeypatch.setenv("OPENPILOT_GOVERNED_DECOMPOSITION", "false")
    monkeypatch.setenv("OPENPILOT_MODEL_VISIBLE_PROTOCOL_REPAIR", "false")

    assert enhanced_cli._unified_autonomous_entry_enabled() is False
    assert enhanced_cli._governed_decomposition_enabled() is False
    assert model_visible_protocol_repair_enabled() is False


def test_interactive_ctrl_c_during_task_returns_to_prompt_without_traceback(
    monkeypatch,
) -> None:
    prompts = iter(("run a task", "/exit"))

    class _PromptSession:
        def __init__(self, **_kwargs) -> None:
            pass

        def prompt(self, _prompt: str) -> str:
            return next(prompts)

    monkeypatch.setattr(prompt_toolkit, "PromptSession", _PromptSession)
    monkeypatch.setattr(
        enhanced_cli,
        "_execute_goal_interactive",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(KeyboardInterrupt()),
    )
    ui = _UI()
    tracker = _Tracker()

    status = enhanced_cli._run_interactive_mode(
        ui,
        tracker,
        logger=None,
        settings=object(),
        args=object(),
        llm_client=object(),
        runtime_options=enhanced_cli.OpenPilotRuntimeOptions(),
    )

    assert status == 0
    assert tracker.stopped is True
    assert any("Interrupted. Type /exit to quit." in message for message in ui.console.messages)
    assert not any("Traceback" in message for message in ui.console.messages)
