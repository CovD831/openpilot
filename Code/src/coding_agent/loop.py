"""Closed-loop orchestration for the standalone coding agent."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Sequence

from autonomous_iteration.application import HarnessApplication
from autonomous_iteration.run_coordinator import RunCoordinator
from autonomous_iteration.verification import CompletionProfile, evaluate_completion
from evidence_core import EvidenceAuthority
from evidence_core.store.fs_store import EvidenceStore

from coding_agent.act import WorkspaceAdapter, execute_action
from coding_agent.context import CodingContext, build_coding_context
from coding_agent.contract import CodingActionResult, CodingActionKind, CodingRunResult, CodingTask
from coding_agent.planner import CodingPlanner, RuleBasedPlanner
from coding_agent.verify import SimpleVerifier, Verifier


class CodingAgent:
    """A tiny evidence-first coding agent loop."""

    def __init__(
        self,
        *,
        store: EvidenceStore | None = None,
        application: HarnessApplication | None = None,
        planner: CodingPlanner | None = None,
        verifier: Verifier | None = None,
    ) -> None:
        if store is not None and application is not None:
            raise ValueError("provide store or application, not both")
        self.application = application or HarnessApplication(store or EvidenceStore())
        self.coordinator: RunCoordinator = self.application.coordinator
        self.store = self.coordinator.evidence
        self.planner = planner or RuleBasedPlanner()
        self.verifier = verifier or SimpleVerifier()

    def run(self, task: CodingTask, adapter: WorkspaceAdapter) -> CodingRunResult:
        workspace_root = Path(task.workspace_root or adapter.root).expanduser().resolve()
        if Path(adapter.root).expanduser().resolve() != workspace_root:
            raise ValueError("adapter root does not match task workspace_root")

        run = self.coordinator.start_run(
            task.task_id,
            source="coding_agent",
            raw_input=task.goal,
            goal=task.goal,
            session_id=task.session_id,
            route=task.route,
        )
        try:
            target_exists = bool(task.target_path and adapter.exists(task.target_path))
            current_text = adapter.read_text(task.target_path) if target_exists and task.target_path else ""
        except (OSError, ValueError) as exc:
            reason = f"blocked: {exc}"
            self._record_event(run.run_id, event_type="task_received", payload={"task": task.model_dump(mode="python"), "workspace_root": str(workspace_root)}, payload_kind="coding_task", task_id=task.task_id, session_id=task.session_id, phase="entry", summary=task.goal)
            self._record_event(run.run_id, event_type="tool_failed", payload={"success": False, "error": str(exc), "path": task.target_path}, phase="act", summary=reason)
            self._record_event(run.run_id, event_type="verification_state_changed", payload={"verification_status": "blocked", "reason": reason}, phase="verify", summary=reason)
            self._finish(
                run.run_id,
                success=False,
                reason=reason,
                profile=CompletionProfile.READ_ONLY,
                final_status="blocked",
            )
            return self._result(run.run_id, task.task_id, [], "blocked", False, "blocked", reason, 0)
        self._record_event(
            run.run_id,
            event_type="task_received",
            payload={
                "task": task.model_dump(mode="python"),
                "workspace_root": str(workspace_root),
                "target_exists": target_exists,
            },
            payload_kind="coding_task",
            task_id=task.task_id,
            session_id=task.session_id,
            phase="entry",
            summary=task.goal,
        )

        history: list[CodingActionResult] = []
        context = build_coding_context(
            task,
            current_text=current_text,
            target_exists=target_exists,
            recent_event_types=["task_received"],
            evidence={},
            metadata={"workspace_root": str(workspace_root)},
        )

        for turn in range(1, task.max_turns + 1):
            self._record_event(
                run.run_id,
                event_type="runtime_phase_changed",
                payload={"phase": "plan", "turn": turn},
                phase="plan",
                summary="planning",
            )
            action = self.planner.next_action(task, context, history)
            if action.kind in {CodingActionKind.WRITE, CodingActionKind.PATCH}:
                self._record_event(
                    run.run_id,
                    event_type="mutation_requested",
                    payload={
                        "action": action.model_dump(mode="python"),
                        "path": action.path,
                    },
                    phase="act",
                    summary="mutation requested",
                )
            if action.kind == CodingActionKind.RUN:
                self._record_event(
                    run.run_id,
                    event_type="validation_started",
                    payload={"action_id": action.action_id, "command": action.command, "reason": action.reason},
                    phase="verify",
                    summary="validation started",
                )
            self._record_event(
                run.run_id,
                event_type="tool_called",
                payload={"action": action.model_dump(mode="python")},
                phase="act",
                summary=action.kind.value,
            )

            action_result = execute_action(adapter, action)
            history.append(action_result)
            self._record_action_result(run.run_id, action_result, task)

            if action.kind in {CodingActionKind.WRITE, CodingActionKind.PATCH}:
                self._record_event(
                    run.run_id,
                    event_type="mutation_receipt",
                    payload={
                        "action_id": action.action_id,
                        "path": action.path,
                        "success": action_result.success,
                        "summary": action_result.summary,
                    },
                    phase="act",
                    summary=action_result.summary or "mutation receipt",
                )
            if action.kind == CodingActionKind.RUN:
                self._record_event(
                    run.run_id,
                    event_type="validation_completed",
                    payload={
                        "command": action.command,
                        "action_id": action.action_id,
                        "success": action_result.success,
                        "exit_code": action_result.exit_code,
                    },
                    phase="verify",
                    summary=action_result.summary or "validation completed",
                )

            self._record_event(
                run.run_id,
                event_type="tool_succeeded" if action_result.success else "tool_failed",
                payload={
                    "action": action_result.action.model_dump(mode="python"),
                    "summary": action_result.summary,
                    "success": action_result.success,
                    "stdout": action_result.stdout[:1200],
                    "stderr": action_result.stderr[:1200],
                    "exit_code": action_result.exit_code,
                },
                phase="act",
                summary=action_result.summary or action.kind.value,
            )

            context = self._refresh_context(task, adapter, history, run.run_id)
            verification = self.verifier.verify(task, context, action_result, history)
            self._record_event(
                run.run_id,
                event_type="verification_state_changed",
                payload={
                    "verification_status": verification.status,
                    "action_id": action.action_id,
                    "summary": verification.summary,
                    "details": verification.details,
                },
                phase="verify",
                summary=verification.summary or verification.status,
            )

            if verification.status == "passed":
                decision = self._finish(
                    run.run_id,
                    success=True,
                    reason=verification.summary or "completed",
                    profile=self._completion_profile(history),
                )
                return self._result(
                    run.run_id,
                    task.task_id,
                    history,
                    decision.status.value,
                    decision.status.value == "success",
                    verification.status,
                    decision.reason,
                    turn,
                )

            if verification.status == "failed":
                self._finish(
                    run.run_id,
                    success=False,
                    reason=verification.summary or "failed",
                    profile=self._completion_profile(history),
                    final_status="failed",
                )
                return self._result(run.run_id, task.task_id, history, "failed", False, verification.status, verification.summary, turn)

            if action.kind == CodingActionKind.STOP:
                self._finish(
                    run.run_id,
                    success=False,
                    reason=verification.summary or "blocked",
                    profile=self._completion_profile(history),
                    final_status="blocked",
                )
                return self._result(run.run_id, task.task_id, history, "blocked", False, verification.status, verification.summary, turn)

        self._finish(
            run.run_id,
            success=False,
            reason="turn limit reached",
            profile=self._completion_profile(history),
            final_status="blocked",
        )
        return self._result(run.run_id, task.task_id, history, "blocked", False, "blocked", "turn limit reached", task.max_turns)

    def _record_event(
        self,
        run_id: str,
        *,
        event_type: str,
        payload: Any = None,
        call_id: str = "",
        **fields: Any,
    ):
        normalized = payload if isinstance(payload, dict) else {}
        action = normalized.get("action") if isinstance(normalized, dict) else None
        resolved_call_id = str(
            call_id
            or normalized.get("action_id")
            or (action.get("action_id") if isinstance(action, dict) else "")
            or ""
        )
        authority = EvidenceAuthority.DERIVED
        if event_type == "mutation_receipt":
            authority = EvidenceAuthority.RECEIPT
        elif event_type == "verification_state_changed" and normalized.get("verification_status") == "passed":
            authority = EvidenceAuthority.VERIFIED
        return self.coordinator.record_canonical(
            run_id,
            event_type=event_type,
            payload=payload,
            producer="coding_agent_fixture",
            authority=authority,
            call_id=resolved_call_id,
            idempotency_key=(f"{event_type}:{resolved_call_id}" if resolved_call_id else ""),
            **fields,
        )

    def _finish(
        self,
        run_id: str,
        *,
        success: bool,
        reason: str,
        profile: CompletionProfile,
        final_status: str = "success",
    ):
        observed = self.coordinator.finish(
            run_id,
            success=success,
            reason=reason,
            final_status=final_status,
        )
        decision = evaluate_completion(
            self.store.load_trajectory_events(run_id),
            profile=profile,
        )
        self.coordinator.finalize(
            run_id,
            source_observation_id=observed.event_id,
            source_observation=observed,
            status=decision.status,
            reason=reason if decision.status.value == "success" else decision.reason,
        )
        return decision

    @staticmethod
    def _completion_profile(history: Sequence[CodingActionResult]) -> CompletionProfile:
        return (
            CompletionProfile.MUTATION
            if any(item.action.kind in {CodingActionKind.WRITE, CodingActionKind.PATCH} for item in history)
            else CompletionProfile.READ_ONLY
        )

    def _refresh_context(
        self,
        task: CodingTask,
        adapter: WorkspaceAdapter,
        history: Sequence[CodingActionResult],
        run_id: str,
    ) -> CodingContext:
        target_exists = bool(task.target_path and adapter.exists(task.target_path))
        current_text = adapter.read_text(task.target_path) if target_exists and task.target_path else ""
        summary = self.store.load_run_summary(run_id)
        event_types = [item.action.kind.value for item in history]
        return build_coding_context(
            task,
            current_text=current_text,
            target_exists=target_exists,
            recent_event_types=event_types,
            evidence=summary.model_dump(mode="python") if summary is not None else {},
            metadata={"turns_used": len(history)},
        )

    def _record_action_result(self, run_id: str, action_result: CodingActionResult, task: CodingTask) -> None:
        artifact_text = action_result.text or action_result.stdout
        if len(artifact_text) > 1600:
            self.store.record_artifact(
                run_id,
                kind="coding_agent_output",
                content=artifact_text,
                filename=f"{action_result.action.kind.value}_{action_result.action.action_id}.txt",
                source_event_id="",
            )

    def _result(
        self,
        run_id: str,
        task_id: str,
        history: Sequence[CodingActionResult],
        status: str,
        success: bool,
        verification_status: str,
        reason: str,
        turns_used: int,
    ) -> CodingRunResult:
        return CodingRunResult(
            run_id=run_id,
            task_id=task_id,
            status=status,  # type: ignore[arg-type]
            success=success,
            reason=reason,
            turns_used=turns_used,
            verification_status=verification_status,
            trajectory_dir=str(self.store.run_dir(run_id)),
            actions=list(history),
        )
