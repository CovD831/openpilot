"""Same-Run Pi mutation recovery through exact validation only.

This is deliberately not a second execution loop. Once a Pi mutation has a
durable receipt but lacks validation evidence, recovery binds a new approval to
the original Run and invokes Action Gateway's already-admitted exact validation
surface. It never starts Pi, rebuilds a prompt, or replays a patch.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from autonomous_iteration.action_gateway import ActionGateway, ValidationRequest
from autonomous_iteration.application import HarnessApplication
from autonomous_iteration.checkpoint_store import RuntimeCheckpointStore
from autonomous_iteration.supervisor import RuntimeSupervisor, SupervisorSession
from autonomous_iteration.task_consent import TaskConsentRegistry
from autonomous_iteration.verification import (
    CompletionDecision,
    CompletionProfile,
    evaluate_completion,
)
from evidence_core import EvidenceLayer, EvidenceStore, EventRecord, TerminalStatus
from memory.agents.project_environment_tool import inspect_project_environment
from metadata import TaskAdmissionGrant, TaskApprovalGrant
from tools.builtin_tools import register_builtin_tools
from tools.tool_executor import ToolExecutor
from tools.tool_registry import ToolRegistry


@dataclass(frozen=True)
class PiMutationRecoveryContext:
    """Read-only facts needed to present one exact-validation recovery proposal."""

    run_id: str
    admission: TaskAdmissionGrant
    conversation_id: str
    proposal_id: str


class PiMutationRecoveryRunner:
    """Reconcile one indeterminate Pi mutation without replaying its side effect."""

    def __init__(
        self,
        *,
        application_factory: Callable[[TaskAdmissionGrant], HarnessApplication] | None = None,
        executor_factory: Callable[[], ToolExecutor] | None = None,
        environment_preflight: Callable[..., Any] | None = None,
        consent_registry_factory: Callable[[Path], TaskConsentRegistry] | None = None,
        supervisor_factory: Callable[[Path], RuntimeSupervisor] | None = None,
    ) -> None:
        self._application_factory = application_factory or self._default_application
        self._executor_factory = executor_factory or self._default_executor
        self._environment_preflight = environment_preflight or inspect_project_environment
        self._consent_registry_factory = consent_registry_factory or self._default_consent_registry
        self._supervisor_factory = supervisor_factory or self._default_supervisor

    def prepare(
        self,
        run_id: str,
        *,
        project_root: str | Path,
    ) -> PiMutationRecoveryContext:
        """Load and verify a recoverable Pi Run without granting any capability."""

        root = Path(project_root).expanduser().resolve(strict=False)
        if not root.is_dir():
            raise ValueError("project root is not a directory")
        normalized_run_id = str(run_id).strip()
        if not normalized_run_id:
            raise ValueError("run_id is required")
        evidence = EvidenceStore(
            root / ".openpilot" / "evidence_core",
            create=False,
        )
        record = evidence.load_run(normalized_run_id)
        if record is None:
            raise KeyError("Pi recovery Run was not found")
        events = evidence.load_trajectory_events(normalized_run_id)
        admission = _persisted_admission(events)
        if Path(admission.project_root).expanduser().resolve(strict=False) != root:
            raise PermissionError("persisted admission belongs to another project")
        _require_recovery_record(record, admission, record.session_id)
        _require_recoverable_mutation_receipt(events)
        original_consent = _original_mutation_consent(events, run_id=normalized_run_id)
        _require_original_consent_identity(
            original_consent,
            admission=admission,
            run_id=normalized_run_id,
            conversation_id=record.session_id,
        )
        proposal_id = str(original_consent.get("proposal_id") or "").strip()
        if not proposal_id:
            raise PermissionError("original proposal consent is missing its proposal identity")
        return PiMutationRecoveryContext(
            run_id=normalized_run_id,
            admission=admission,
            conversation_id=record.session_id,
            proposal_id=proposal_id,
        )

    def recover(
        self,
        run_id: str,
        admission: TaskAdmissionGrant,
        *,
        approval: TaskApprovalGrant,
        conversation_id: str,
    ) -> dict[str, object]:
        """Run the sole exact validation eligible for a durable Pi mutation receipt."""

        if not admission.is_mutation or admission.validation is None:
            raise PermissionError("Pi mutation recovery requires an admitted mutation task")
        _require_matching_mutation_approval(
            admission,
            approval,
            conversation_id=conversation_id,
        )
        normalized_run_id = str(run_id).strip()
        if not normalized_run_id:
            raise ValueError("run_id is required")

        application = self._application_factory(admission)
        record = application.coordinator.evidence.load_run(normalized_run_id)
        if record is None:
            raise KeyError("Pi recovery Run was not found")
        _require_recovery_record(record, admission, conversation_id)

        events = application.coordinator.evidence.load_trajectory_events(normalized_run_id)
        persisted_admission = _persisted_admission(events)
        if persisted_admission.model_dump(mode="json") != admission.model_dump(mode="json"):
            raise PermissionError("persisted admission does not match recovery authority")
        _require_recoverable_mutation_receipt(events)
        original_consent = _original_mutation_consent(events, run_id=normalized_run_id)
        _require_fresh_recovery_approval(
            approval,
            original_consent=original_consent,
            admission=admission,
            run_id=normalized_run_id,
            conversation_id=conversation_id,
        )

        original_run = application.coordinator.attach_run(
            normalized_run_id,
            expected_task_id=admission.task_id,
            expected_session_id=str(conversation_id).strip(),
        )
        supervisor = self._supervisor_factory(Path(admission.project_root))
        session = SupervisorSession(supervisor, original_run)
        if not session.acquire():
            raise RuntimeError("Pi recovery Run lease is already active")

        consent_registry = self._consent_registry_factory(Path(admission.project_root))
        consent = approval.bind_run(normalized_run_id)
        consent_active = False
        try:
            consent_registry.activate(consent)
            consent_active = True
            resume_attempt_id = supervisor.new_resume_attempt_id()
            resumed = application.coordinator.attach_run(
                normalized_run_id,
                expected_task_id=admission.task_id,
                expected_session_id=str(conversation_id).strip(),
                resume_attempt_id=resume_attempt_id,
            )
            application.canonical(
                resumed,
                event_type="mutation_recovery_consent_bound",
                payload={
                    "consent_id": consent.consent_id,
                    "approval_id": consent.approval_id,
                    "proposal_id": consent.proposal_id,
                    "admission_id": consent.admission_id,
                    "task_id": consent.task_id,
                    "project_root": consent.project_root,
                    "conversation_id": consent.conversation_id,
                    "run_id": consent.run_id,
                    "resume_attempt_id": resume_attempt_id,
                    "protocol_version": consent.protocol_version,
                },
                producer="pi_mutation_recovery",
                idempotency_key=f"mutation-recovery-consent:{consent.consent_id}",
            )
            gateway = ActionGateway(
                application.coordinator,
                self._executor_factory(),
                environment_preflight=self._environment_preflight,
                consent_resolver=consent_registry,
            )
            validation = ValidationRequest(
                call_id=f"recovery-validation-{resume_attempt_id}",
                command=admission.validation.command,
                cwd=admission.validation.cwd,
                timeout_seconds=admission.validation.timeout_seconds,
                admission=admission,
                consent=consent,
            )
            result = gateway.execute_validation(
                resumed,
                validation,
                requested_command=admission.validation.command,
            )
            observed = application.coordinator.finish(
                resumed,
                success=result.verified is True,
                reason="Pi mutation recovery validation completed",
            )
            decision = _recovery_completion_decision(
                application.coordinator.evidence.load_trajectory_events(normalized_run_id)
            )
            terminal = application.coordinator.finalize(
                resumed,
                source_observation_id=observed.event_id,
                source_observation=observed,
                status=decision.status,
                reason=decision.reason,
            )
            return {
                "run_id": normalized_run_id,
                "resume_attempt_id": resume_attempt_id,
                "status": decision.status.value,
                "success": decision.status is TerminalStatus.SUCCESS,
                "reason": decision.reason,
                "terminal_event_id": terminal.event_id,
            }
        finally:
            if consent_active:
                consent_registry.close(consent.consent_id, run_id=normalized_run_id)
            session.release()

    @staticmethod
    def _default_application(admission: TaskAdmissionGrant) -> HarnessApplication:
        evidence = EvidenceStore(
            Path(admission.project_root) / ".openpilot" / "evidence_core"
        )
        return HarnessApplication(evidence, engine="pi")

    @staticmethod
    def _default_executor() -> ToolExecutor:
        registry = ToolRegistry()
        register_builtin_tools(registry)
        return ToolExecutor(registry)

    @staticmethod
    def _default_consent_registry(project_root: Path) -> TaskConsentRegistry:
        return TaskConsentRegistry(state_directory=project_root / ".openpilot" / "consents")

    @staticmethod
    def _default_supervisor(project_root: Path) -> RuntimeSupervisor:
        return RuntimeSupervisor(
            RuntimeCheckpointStore(project_root / ".openpilot" / "checkpoints")
        )


def _require_matching_mutation_approval(
    admission: TaskAdmissionGrant,
    approval: TaskApprovalGrant | None,
    *,
    conversation_id: str,
) -> None:
    if approval is None:
        raise PermissionError("mutation Pi task requires an explicit matching approval")
    if not str(conversation_id).strip():
        raise PermissionError("mutation Pi task requires a conversation identity")
    if (
        approval.admission_id != admission.admission_id
        or approval.task_id != admission.task_id
        or approval.project_root != admission.project_root
        or approval.conversation_id != conversation_id
        or approval.protocol_version != admission.protocol_version
    ):
        raise PermissionError("mutation Pi task approval does not match the admitted task")


def _semantic_events(
    events: list[EventRecord],
    event_type: str,
    *,
    raw_producer: str = "",
) -> list[EventRecord]:
    raw_by_id = {
        event.event_id: event
        for event in events
        if event.layer is EvidenceLayer.RAW
    }
    selected: list[EventRecord] = []
    for event in events:
        if event.layer is not EvidenceLayer.SEMANTIC or event.event_type != event_type:
            continue
        raw = raw_by_id.get(event.source_observation_id)
        if raw is None or raw.event_type != event_type:
            continue
        if raw_producer and raw.producer != raw_producer:
            continue
        selected.append(event)
    return selected


def _require_recovery_record(
    record: Any,
    admission: TaskAdmissionGrant,
    conversation_id: str,
) -> None:
    if record.task_id != admission.task_id:
        raise PermissionError("existing Run task identity does not match admission")
    if record.session_id != str(conversation_id).strip():
        raise PermissionError("existing Run session identity does not match recovery conversation")
    if record.route != "cli_v2_pi":
        raise PermissionError("existing Run route is not eligible for Pi recovery")
    if record.final_status != TerminalStatus.INDETERMINATE:
        raise PermissionError("Pi recovery requires an indeterminate Run")


def _persisted_admission(events: list[EventRecord]) -> TaskAdmissionGrant:
    received = [
        event
        for event in _semantic_events(
            events,
            "task_received",
            raw_producer="cli_interaction",
        )
    ]
    if len(received) != 1:
        raise PermissionError("Pi recovery requires one canonical persisted admission")
    try:
        return TaskAdmissionGrant.model_validate((received[0].payload or {}).get("admission"))
    except (TypeError, ValueError) as exc:
        raise PermissionError("Pi recovery persisted admission is malformed") from exc


def _require_recoverable_mutation_receipt(events: list[EventRecord]) -> None:
    receipts = _semantic_events(events, "mutation_receipt")
    if not any((event.payload or {}).get("durable") is True for event in receipts):
        raise PermissionError("Pi recovery requires a durable mutation receipt")
    validation_events = [
        event
        for event in events
        if event.layer is EvidenceLayer.SEMANTIC
        and event.event_type in {
            "validation_started",
            "validation_completed",
            "verification_state_changed",
        }
    ]
    if validation_events:
        raise PermissionError("Pi recovery rejects a Run with existing validation evidence")


def _original_mutation_consent(
    events: list[EventRecord],
    *,
    run_id: str,
) -> dict[str, Any]:
    consents = [
        event
        for event in _semantic_events(
            events,
            "mutation_consent_bound",
            raw_producer="pi_task_runner",
        )
    ]
    if len(consents) != 1:
        raise PermissionError("Pi recovery requires one canonical original proposal consent")
    payload = dict(consents[0].payload or {})
    if str(payload.get("run_id") or "") != run_id:
        raise PermissionError("original proposal consent belongs to another Run")
    return payload


def _require_fresh_recovery_approval(
    approval: TaskApprovalGrant,
    *,
    original_consent: dict[str, Any],
    admission: TaskAdmissionGrant,
    run_id: str,
    conversation_id: str,
) -> None:
    _require_original_consent_identity(
        original_consent,
        admission=admission,
        run_id=run_id,
        conversation_id=conversation_id,
    )
    if approval.proposal_id != str(original_consent.get("proposal_id") or ""):
        raise PermissionError("recovery approval does not match the original proposal consent")
    if approval.approval_id == str(original_consent.get("approval_id") or ""):
        raise PermissionError("Pi recovery requires a fresh approval")


def _require_original_consent_identity(
    original_consent: dict[str, Any],
    *,
    admission: TaskAdmissionGrant,
    run_id: str,
    conversation_id: str,
) -> None:
    expected = {
        "admission_id": admission.admission_id,
        "task_id": admission.task_id,
        "project_root": admission.project_root,
        "conversation_id": str(conversation_id).strip(),
        "run_id": run_id,
        "protocol_version": admission.protocol_version,
    }
    for field, value in expected.items():
        if str(original_consent.get(field) or "") != str(value):
            raise PermissionError("recovery approval does not match the original proposal consent")


def _recovery_completion_decision(events: list[EventRecord]) -> CompletionDecision:
    decision = evaluate_completion(events, profile=CompletionProfile.MUTATION)
    if decision.status in {TerminalStatus.SUCCESS, TerminalStatus.BLOCKED, TerminalStatus.FAILED}:
        return decision
    return CompletionDecision(
        TerminalStatus.BLOCKED,
        f"Pi recovery completion evidence requires manual inspection: {decision.reason}",
    )


__all__ = ["PiMutationRecoveryContext", "PiMutationRecoveryRunner"]
