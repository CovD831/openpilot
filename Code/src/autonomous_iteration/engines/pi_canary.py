"""Credential-safe real-provider Pi rollout canary.

The credential is read by Pi from the process environment. This module never
accepts a credential argument and never includes credential values in output.
"""

from __future__ import annotations

import argparse
import json
from enum import StrEnum
from pathlib import Path
from tempfile import TemporaryDirectory

from pydantic import BaseModel, ConfigDict, Field

from autonomous_iteration.action_gateway import ActionGateway, ValidationRequest
from autonomous_iteration.application import HarnessApplication
from autonomous_iteration.checkpoint_store import RuntimeCheckpointStore
from autonomous_iteration.engines.pi_sidecar import PiRpcEngine, PiSidecarConfig
from autonomous_iteration.supervisor import RuntimeSupervisor, SupervisorSession
from autonomous_iteration.verification import CompletionProfile, evaluate_completion
from evidence_core import EvidenceStore, TerminalStatus
from tools.builtin_tools import register_builtin_tools
from tools.tool_executor import ToolExecutor
from tools.tool_registry import ToolRegistry


class PiCanaryMode(StrEnum):
    READ_ONLY = "readonly"
    MUTATION = "mutation"
    RECOVERY = "recovery"


class PiCanaryResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str
    model: str
    mode: PiCanaryMode
    passed: bool
    engine_state: str
    run_status: str
    marker_present: bool
    target_updated: bool | None = None
    mutation_receipt: bool = False
    validation_completed: bool = False
    verification_recorded: bool = False
    credential_marker_persisted: bool = False
    event_count: int = 0
    tool_sequence: list[str] = Field(default_factory=list)
    mutation_requested: bool = False
    validation_passed: bool = False
    verification_status: str = ""
    resume_attempt_recorded: bool = False
    reconciliation_completed: bool = False


def run_pi_canary(
    *,
    provider: str,
    model: str,
    mode: PiCanaryMode | str,
    timeout_seconds: float = 120.0,
) -> PiCanaryResult:
    selected_mode = PiCanaryMode(mode)
    with TemporaryDirectory(prefix="openpilot-pi-canary-") as temporary:
        root = Path(temporary)
        store = EvidenceStore(root / "evidence")
        app = HarnessApplication(store, engine="pi")
        run = app.start(
            f"{provider}-{model}-{selected_mode.value}-canary",
            source="credentialed_canary",
            goal="Validate the real Pi provider boundary",
        )
        app.canonical(
            run,
            event_type="task_received",
            payload={"canary_mode": selected_mode.value},
            producer="application_entry",
        )

        action_handler = None
        profile = CompletionProfile.READ_ONLY
        marker = "READ_ONLY_CANARY_OK"
        target: Path | None = None
        gateway: ActionGateway | None = None
        validation_request: ValidationRequest | None = None
        enable_mutation = selected_mode is not PiCanaryMode.READ_ONLY
        if enable_mutation:
            marker = (
                "RECOVERY_PATCH_APPLIED"
                if selected_mode is PiCanaryMode.RECOVERY
                else "MUTATION_CANARY_OK"
            )
            target = root / "target.py"
            target.write_text('VALUE = "old"\n', encoding="utf-8")
            (root / "check.py").write_text(
                "from pathlib import Path\n"
                "assert Path('target.py').read_text(encoding='utf-8') "
                "== 'VALUE = \"new\"\\n'\n",
                encoding="utf-8",
            )
            registry = ToolRegistry()
            register_builtin_tools(registry)
            gateway = ActionGateway(app.coordinator, ToolExecutor(registry))
            validation_request = ValidationRequest(
                call_id="validation",
                command="python check.py",
                cwd=str(root),
            )
            action_handler = gateway.pi_action_handler(
                run,
                allowed_read_files=(str(target),),
                allowed_write_files=(str(target),),
                validation=validation_request,
                mutation_opt_in=True,
                user_confirmed=True,
            )
            if selected_mode is PiCanaryMode.RECOVERY:
                prompt = (
                    f"Use openpilot_read on {target}. Then use openpilot_patch on the same "
                    "path with lineStart 1, lineEnd 1, and replacementText exactly "
                    f"VALUE = \"new\". Do not call openpilot_validate. Answer {marker} "
                    "after the patch tool returns."
                )
            else:
                prompt = (
                    f"Use openpilot_read on {target}. Then use openpilot_patch on the same "
                    "path with lineStart 1, lineEnd 1, and replacementText exactly "
                    'VALUE = "new". Then call openpilot_validate with the exact command '
                    f"python check.py. Do not use any other tool. Answer {marker} only after "
                    "validation succeeds."
                )
            profile = CompletionProfile.MUTATION
        else:
            prompt = f"Return exactly {marker}. Do not call tools."

        engine = PiRpcEngine(
            app.coordinator,
            PiSidecarConfig(
                provider=provider,
                model=model,
                timeout_seconds=timeout_seconds,
                cwd=str(root),
                enable_read_tool=enable_mutation,
                enable_mutation_tools=enable_mutation,
            ),
        )
        resume_attempt_recorded = False
        reconciliation_completed = False
        if selected_mode is PiCanaryMode.RECOVERY:
            engine.run_once(run, prompt=prompt, action_handler=action_handler)
            staged_events = store.load_trajectory_events(run.run_id)
            staged_semantic = {
                event.event_type
                for event in staged_events
                if event.layer.value == "semantic"
            }
            staged_target_updated = (
                target is not None
                and target.read_text(encoding="utf-8") == 'VALUE = "new"\n'
            )
            if (
                str(engine.state.value) == "stopped"
                and staged_target_updated
                and "mutation_receipt" in staged_semantic
                and gateway is not None
                and validation_request is not None
            ):
                app.coordinator.mark_recovery_state(
                    run,
                    status=TerminalStatus.INDETERMINATE,
                    reason="mutation persisted before reconciliation validation",
                )
                supervisor = RuntimeSupervisor(
                    RuntimeCheckpointStore(root / "checkpoints")
                )
                session = SupervisorSession(supervisor, run)
                if session.acquire():
                    try:
                        resume_attempt_id = supervisor.new_resume_attempt_id()
                        resumed = app.coordinator.attach_run(
                            run.run_id,
                            resume_attempt_id=resume_attempt_id,
                        )
                        resume_attempt_recorded = (
                            resumed.run.resume_attempt_id == resume_attempt_id
                        )
                        validation_result = gateway.execute_validation(
                            resumed,
                            validation_request,
                            requested_command=validation_request.command,
                        )
                        observed = app.coordinator.finish(
                            resumed,
                            success=validation_result.verified is True,
                            reason="mutation reconciliation validation completed",
                        )
                        decision = evaluate_completion(
                            store.load_trajectory_events(run.run_id),
                            profile=CompletionProfile.MUTATION,
                        )
                        app.coordinator.finalize(
                            resumed,
                            source_observation_id=observed.event_id,
                            source_observation=observed,
                            status=decision.status,
                            reason=decision.reason,
                        )
                        reconciliation_completed = (
                            decision.status is TerminalStatus.SUCCESS
                        )
                    finally:
                        session.release()
            loaded_run = store.load_run(run.run_id)
            runtime_result = {
                "status": str(
                    loaded_run.final_status.value if loaded_run else "failed"
                ),
                "success": bool(loaded_run and loaded_run.success),
            }
        else:
            runtime_result = app.run_pi(
                run.run_id,
                engine=engine,
                prompt=prompt,
                action_handler=action_handler,
                profile=profile,
            )
        events = store.load_trajectory_events(run.run_id)
        semantic_types = {
            event.event_type for event in events if event.layer.value == "semantic"
        }
        tool_sequence = [
            str((event.payload or {}).get("toolName") or (event.payload or {}).get("tool_name") or "")
            for event in events
            if event.layer.value == "raw"
            and event.event_type == "tool_call"
            and ((event.payload or {}).get("toolName") or (event.payload or {}).get("tool_name"))
        ]
        validation_events = [
            event for event in events if event.event_type == "validation_completed"
        ]
        verification_events = [
            event for event in events if event.event_type == "verification_state_changed"
        ]
        response_text = " ".join(
            json.dumps(event.payload, ensure_ascii=False)
            for event in events
            if event.event_type == "model_response"
        )
        persisted = store.events_file(run.run_id).read_text(encoding="utf-8")
        target_updated = (
            target.read_text(encoding="utf-8") == 'VALUE = "new"\n'
            if target is not None
            else None
        )
        marker_present = marker in response_text
        passed = (
            str(engine.state.value) == "stopped"
            and marker_present
            and (
                selected_mode is PiCanaryMode.READ_ONLY
                or (
                    bool(runtime_result["success"])
                    and target_updated is True
                    and "mutation_receipt" in semantic_types
                    and "validation_completed" in semantic_types
                    and "verification_state_changed" in semantic_types
                    and (
                        selected_mode is not PiCanaryMode.RECOVERY
                        or (resume_attempt_recorded and reconciliation_completed)
                    )
                )
            )
        )
        return PiCanaryResult(
            provider=provider,
            model=model,
            mode=selected_mode,
            passed=passed,
            engine_state=str(engine.state.value),
            run_status=str(runtime_result["status"]),
            marker_present=marker_present,
            target_updated=target_updated,
            mutation_receipt="mutation_receipt" in semantic_types,
            validation_completed="validation_completed" in semantic_types,
            verification_recorded="verification_state_changed" in semantic_types,
            credential_marker_persisted="sk-" in persisted,
            event_count=len(events),
            tool_sequence=tool_sequence,
            mutation_requested="mutation_requested" in semantic_types,
            validation_passed=bool(
                validation_events
                and (validation_events[-1].payload or {}).get("success") is True
            ),
            verification_status=(
                str((verification_events[-1].payload or {}).get("verification_status") or "")
                if verification_events
                else ""
            ),
            resume_attempt_recorded=resume_attempt_recorded,
            reconciliation_completed=reconciliation_completed,
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--mode", choices=[item.value for item in PiCanaryMode], required=True)
    parser.add_argument("--timeout", type=float, default=120.0)
    args = parser.parse_args()
    result = run_pi_canary(
        provider=args.provider,
        model=args.model,
        mode=args.mode,
        timeout_seconds=args.timeout,
    )
    print(result.model_dump_json())
    return 0 if result.passed and not result.credential_marker_persisted else 1


if __name__ == "__main__":
    raise SystemExit(main())
