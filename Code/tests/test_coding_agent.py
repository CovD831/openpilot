from __future__ import annotations

import sys

from coding_agent import (
    CodingAgent,
    CodingActionKind,
    CodingContext,
    CodingTask,
    OpenPilotWorkspaceAdapter,
    RuleBasedPlanner,
    SimpleVerifier,
    build_coding_context,
)
from evidence_core import EvidenceStore
from evidence_core import validate_trajectory_conformance


def test_rule_based_planner_reads_then_writes_then_runs(tmp_path) -> None:
    task = CodingTask(
        task_id="task-1",
        goal="replace the file",
        workspace_root=str(tmp_path),
        target_path="hello.py",
        draft_text="print('new')\n",
        validation_command=[sys.executable, "-c", "print('ok')"],
    )
    context = CodingContext(
        task_id=task.task_id,
        goal=task.goal,
        workspace_root=task.workspace_root,
        target_path=task.target_path,
        target_exists=True,
        current_text="print('old')\n",
    )
    planner = RuleBasedPlanner()

    read_action = planner.next_action(task, context, [])
    write_context = build_coding_context(task, current_text="print('old')\n", target_exists=True)
    write_history = [type("R", (), {"action": read_action})()]  # simple shim
    write_action = planner.next_action(task, write_context, write_history)  # type: ignore[arg-type]
    run_context = build_coding_context(task, current_text="print('new')\n", target_exists=True)
    run_history = [type("R", (), {"action": read_action})(), type("R", (), {"action": write_action})()]
    run_action = planner.next_action(task, run_context, run_history)  # type: ignore[arg-type]

    assert read_action.kind == CodingActionKind.READ
    assert write_action.kind == CodingActionKind.WRITE
    assert run_action.kind == CodingActionKind.RUN


def test_coding_agent_records_a_closed_loop_trajectory(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = workspace / "hello.py"
    target.write_text("print('old')\n", encoding="utf-8")

    store = EvidenceStore(tmp_path / "evidence")
    agent = CodingAgent(store=store, verifier=SimpleVerifier())
    adapter = OpenPilotWorkspaceAdapter(workspace)
    task = CodingTask(
        task_id="task-closed-loop",
        goal="replace the file and verify it",
        workspace_root=str(workspace),
        session_id="session-1",
        target_path="hello.py",
        draft_text="print('new')\n",
        validation_command=[
            sys.executable,
            "-c",
            f"from pathlib import Path; assert Path(r'{target}').read_text() == \"print('new')\\n\"",
        ],
        max_turns=4,
    )

    result = agent.run(task, adapter)
    replay = store.replay_run("task-closed-loop")
    summary = store.load_run_summary("task-closed-loop")
    conformance = validate_trajectory_conformance(
        replay["events"],
        require_mutation_chain=True,
    )

    assert result.success is True
    assert result.status == "success"
    assert target.read_text(encoding="utf-8") == "print('new')\n"
    assert replay is not None
    assert summary is not None
    assert summary.success is True
    assert summary.final_status == "success"
    assert conformance.valid is True
    assert summary.tool_called_count == 3
    semantic_event_types = [
        event.event_type for event in replay["events"] if event.layer.value == "semantic"
    ]
    assert summary.event_count == len(semantic_event_types)
    assert summary.projection_layer.value == "semantic"
    assert semantic_event_types == [
        "task_received",
        "runtime_phase_changed",
        "tool_called",
        "tool_succeeded",
        "verification_state_changed",
        "runtime_phase_changed",
        "mutation_requested",
        "tool_called",
        "mutation_receipt",
        "tool_succeeded",
        "verification_state_changed",
        "runtime_phase_changed",
        "validation_started",
        "tool_called",
        "validation_completed",
        "tool_succeeded",
        "verification_state_changed",
        "task_finished",
    ]
