from __future__ import annotations

from autonomous_iteration.iteration_turn_store import IterationTurnStore
from core.config import LLMSettings
from metadata import ConversationIdentity, SessionIngressState, TaskRouteMetadata
from ui import enhanced_cli


class _Console:
    def __init__(self) -> None:
        self.messages: list[str] = []

    def print(self, *args, **_kwargs) -> None:
        self.messages.append(" ".join(str(arg) for arg in args))


class _UI:
    def __init__(self) -> None:
        self.console = _Console()


def _route(route: str) -> TaskRouteMetadata:
    return TaskRouteMetadata(route=route, confidence=1.0, reason="test route")


def _settings() -> LLMSettings:
    return LLMSettings(provider="openai", model="gpt-test", api_key="")


def test_feature_flagged_interactive_runtime_question_skips_autopilot(
    tmp_path, monkeypatch
) -> None:
    store = IterationTurnStore(tmp_path)
    ui = _UI()
    monkeypatch.setenv("OPENPILOT_UNIFIED_AUTONOMOUS_ENTRY_ENABLED", "1")
    monkeypatch.setattr(enhanced_cli, "_runtime_diagnostics_enabled", lambda: False)
    monkeypatch.setattr(enhanced_cli, "_iteration_turn_store", lambda: store)
    monkeypatch.setattr(
        enhanced_cli,
        "_classify_task_route",
        lambda _goal: _route("autonomous_iteration"),
    )
    monkeypatch.setattr(
        enhanced_cli,
        "_execute_autopilot",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("autopilot called")),
    )
    ingress = SessionIngressState(
        identity=ConversationIdentity(
            conversation_id="conversation-1",
            run_id="run-0",
            turn_index=0,
            project_root=str(tmp_path.resolve()),
        )
    )

    result = enhanced_cli._execute_goal_interactive(
        "你使用的是什么模型？",
        ui,
        tracker=None,
        llm_client=object(),
        logger=None,
        runtime_options=enhanced_cli.OpenPilotRuntimeOptions(),
        ingress_state=ingress,
        settings=_settings(),
    )

    assert result.turns[-1].role == "assistant"
    assert result.turns[-1].content == "Model: gpt-test"
    assert any("Model: gpt-test" in message for message in ui.console.messages)


def test_feature_flagged_once_runtime_question_skips_runtime_construction(
    tmp_path, monkeypatch
) -> None:
    store = IterationTurnStore(tmp_path)
    ui = _UI()
    monkeypatch.setenv("OPENPILOT_UNIFIED_AUTONOMOUS_ENTRY_ENABLED", "1")
    monkeypatch.setattr(enhanced_cli, "_runtime_diagnostics_enabled", lambda: False)
    monkeypatch.setattr(enhanced_cli, "_iteration_turn_store", lambda: store)
    monkeypatch.setattr(
        enhanced_cli,
        "_classify_task_route",
        lambda _goal: _route("autonomous_iteration"),
    )

    status = enhanced_cli._run_once_mode(
        "What model are you using?",
        ui,
        tracker=None,
        logger=None,
        settings=_settings(),
        runtime_options=enhanced_cli.OpenPilotRuntimeOptions(),
        llm_client=object(),
        project_path=str(tmp_path),
    )

    assert status == 0
    assert any("Model: gpt-test" in message for message in ui.console.messages)


def test_agent_generator_route_bypasses_unified_entry_under_flag(monkeypatch) -> None:
    ui = _UI()
    calls: list[str] = []
    monkeypatch.setenv("OPENPILOT_UNIFIED_AUTONOMOUS_ENTRY_ENABLED", "1")
    monkeypatch.setattr(
        enhanced_cli,
        "_classify_task_route",
        lambda _goal: _route("agent_generator"),
    )
    monkeypatch.setattr(
        enhanced_cli,
        "_execute_agent_generator",
        lambda goal, *_args, **_kwargs: calls.append(goal) or "agent-result",
    )
    monkeypatch.setattr(
        enhanced_cli,
        "_try_deterministic_runtime_response",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("unified entry called")),
    )

    result = enhanced_cli._execute_goal_interactive(
        "Create a reusable research agent",
        ui,
        tracker=None,
        llm_client=object(),
        logger=None,
        runtime_options=enhanced_cli.OpenPilotRuntimeOptions(),
        settings=_settings(),
    )

    assert result == "agent-result"
    assert calls == ["Create a reusable research agent"]
