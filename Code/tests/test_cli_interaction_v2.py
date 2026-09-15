from __future__ import annotations

from types import SimpleNamespace

import pytest

from autonomous_iteration.task_consent import TaskConsentRegistry
from metadata import TaskConsentReference
from metadata import TaskRouteMetadata
from ui import enhanced_cli
from ui import cli


class _Console:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def print(self, value="", *args, **kwargs) -> None:
        self.lines.append(str(value))


class _UI:
    def __init__(self) -> None:
        self.console = _Console()
        self.errors: list[tuple[str, str]] = []

    def show_error(self, title: str, detail: str = "") -> None:
        self.errors.append((title, detail))

    def show_success(self, *_args, **_kwargs) -> None:
        pass

    def show_full_task_graph_timeline(self) -> None:
        pass


def _proposal(*, mutation: bool):
    grant = SimpleNamespace(
        admission_id="admission-1",
        task_id="task-1",
        project_root="/workspace",
        protocol_version="cli-v2",
        read_files=["/workspace/service.py"],
        write_files=["/workspace/service.py"] if mutation else [],
        validation=SimpleNamespace(command="python -m pytest -q") if mutation else None,
    )
    return SimpleNamespace(
        proposal_id="proposal-1",
        goal="Repair service" if mutation else "Inspect service",
        is_mutation=mutation,
        admission=SimpleNamespace(grant=grant),
    )


def test_once_mutation_prints_typed_proposal_without_execution(monkeypatch) -> None:
    ui = _UI()
    proposal = _proposal(mutation=True)
    executions: list[object] = []

    class Controller:
        def propose(self, *_args, **_kwargs):
            return proposal

        def execute(self, *_args, **_kwargs):
            executions.append(True)
            return {"success": True}

    monkeypatch.setattr(enhanced_cli, "_new_cli_interaction_controller", lambda **_kwargs: Controller())
    monkeypatch.setattr(
        enhanced_cli,
        "_classify_task_route",
        lambda _goal: TaskRouteMetadata(route="autonomous_iteration", confidence=1.0, reason="test"),
    )
    monkeypatch.setattr(enhanced_cli, "_show_task_route", lambda *_args: None)
    monkeypatch.setattr(enhanced_cli, "_runtime_diagnostics_enabled", lambda: False)

    result = enhanced_cli._run_once_mode(
        "Repair service",
        ui,
        tracker=None,
        logger=None,
        settings=SimpleNamespace(),
        runtime_options=enhanced_cli.OpenPilotRuntimeOptions(),
        llm_client=object(),
        project_path="/workspace",
    )

    assert result == 3
    assert executions == []
    assert any('"admission_id": "admission-1"' in line for line in ui.console.lines)


def test_once_read_only_executes_the_shared_controller(monkeypatch) -> None:
    ui = _UI()
    proposal = _proposal(mutation=False)
    executions: list[tuple[str, str]] = []

    class Controller:
        def propose(self, *_args, **_kwargs):
            return proposal

        def execute(self, proposal_id, *, conversation_id, approval=None):
            executions.append((proposal_id, conversation_id))
            assert approval is None
            return {"success": True, "response": "inspected"}

    monkeypatch.setattr(enhanced_cli, "_new_cli_interaction_controller", lambda **_kwargs: Controller())
    monkeypatch.setattr(
        enhanced_cli,
        "_classify_task_route",
        lambda _goal: TaskRouteMetadata(route="autonomous_iteration", confidence=1.0, reason="test"),
    )
    monkeypatch.setattr(enhanced_cli, "_show_task_route", lambda *_args: None)
    monkeypatch.setattr(enhanced_cli, "_runtime_diagnostics_enabled", lambda: False)

    result = enhanced_cli._run_once_mode(
        "Inspect service",
        ui,
        tracker=None,
        logger=None,
        settings=SimpleNamespace(),
        runtime_options=enhanced_cli.OpenPilotRuntimeOptions(),
        llm_client=object(),
        project_path="/workspace",
    )

    assert result == 0
    assert executions and executions[0][0] == "proposal-1"


def test_interactive_goal_uses_shared_controller_for_read_only_proposal(monkeypatch) -> None:
    ui = _UI()
    proposal = _proposal(mutation=False)
    calls: list[tuple[str, object]] = []

    class Controller:
        def propose(self, goal, *, project_root, conversation_id):
            calls.append(("propose", (goal, str(project_root), conversation_id)))
            return proposal

        def execute(self, proposal_id, *, conversation_id, approval=None):
            calls.append(("execute", (proposal_id, conversation_id, approval)))
            return {"success": True, "response": "inspected"}

    monkeypatch.setattr(
        enhanced_cli,
        "_classify_task_route",
        lambda _goal: TaskRouteMetadata(route="autonomous_iteration", confidence=1.0, reason="test"),
    )
    monkeypatch.setattr(enhanced_cli, "_show_task_route", lambda *_args: None)
    monkeypatch.setattr(enhanced_cli, "_runtime_diagnostics_enabled", lambda: False)

    result = enhanced_cli._execute_goal_interactive(
        "Inspect service",
        ui,
        tracker=None,
        llm_client=object(),
        logger=None,
        runtime_options=enhanced_cli.OpenPilotRuntimeOptions(),
        interaction_controller=Controller(),
    )

    assert result == {"success": True, "response": "inspected"}
    assert [name for name, _value in calls] == ["propose", "execute"]
    assert any("inspected" in line for line in ui.console.lines)


def test_bare_openpilot_invocation_defaults_to_run(monkeypatch) -> None:
    captured: list[object] = []

    def run_openpilot(args, _console, _client):
        captured.append(args)
        return 0

    monkeypatch.setattr(cli, "_run_openpilot", run_openpilot)

    assert cli.main([], llm_client=object()) == 0
    assert captured[0].command == "run"


def test_revoke_command_persists_a_cross_process_mutation_consent_revoke(tmp_path) -> None:
    consent = TaskConsentReference(
        consent_id="consent-1",
        approval_id="approval-1",
        proposal_id="proposal-1",
        admission_id="admission-1",
        task_id="task-1",
        project_root=str(tmp_path),
        conversation_id="conversation-1",
        run_id="run-1",
    )
    registry = TaskConsentRegistry(state_directory=tmp_path / ".openpilot" / "consents")
    registry.activate(consent)

    assert cli.main(
        [
            "revoke",
            "--project-path",
            str(tmp_path),
            "--run-id",
            consent.run_id,
            "--consent-id",
            consent.consent_id,
        ],
        llm_client=object(),
    ) == 0

    with pytest.raises(PermissionError, match="revoked"):
        with registry.authorize(consent, run_id=consent.run_id):
            pass


def test_body_free_project_inventory_has_a_directory_walk_bound(tmp_path) -> None:
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    (tmp_path / "c").mkdir()
    (tmp_path / "c" / "late.py").write_text("VALUE = 1\n", encoding="utf-8")

    inventory = enhanced_cli._project_file_inventory(
        tmp_path,
        limit=160,
        max_directories=2,
    )

    assert inventory == []
