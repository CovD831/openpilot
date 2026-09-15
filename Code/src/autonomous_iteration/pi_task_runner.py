"""Pi-only runner for the public CLI's admitted task surface.

This module deliberately has no dependency on ``IntelligentAutopilot`` or the
legacy runtime controller. Mutation is admitted only through the same strict
grant, ready-environment, run-bound consent, Action Gateway, and completion
chain used by the Pi tool bridge.
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from autonomous_iteration.action_gateway import ActionGateway
from autonomous_iteration.application import HarnessApplication
from autonomous_iteration.engines import PiRpcEngine, PiSidecarConfig
from autonomous_iteration.task_consent import TaskConsentRegistry
from autonomous_iteration.validation_environment import require_ready_validation_environment
from autonomous_iteration.verification import CompletionProfile
from evidence_core import EvidenceStore
from memory.agents.project_environment_tool import inspect_project_environment
from metadata import TaskAdmissionGrant, TaskApprovalGrant
from tools.builtin_tools import register_builtin_tools
from tools.tool_executor import ToolExecutor
from tools.tool_registry import ToolRegistry


_ANSI_ESCAPE = re.compile(r"\x1b(?:\][^\x07\x1b]*(?:\x07|\x1b\\)|\[[0-?]*[ -/]*[@-~])")
_BIDI_OR_INVISIBLE = frozenset(
    {
        "\u061c",
        "\u200b",
        "\u200c",
        "\u200d",
        "\u200e",
        "\u200f",
        "\u202a",
        "\u202b",
        "\u202c",
        "\u202d",
        "\u202e",
        "\u2066",
        "\u2067",
        "\u2068",
        "\u2069",
        "\ufeff",
    }
)
_MAX_RESPONSE_CHARS = 6000


class PiTaskRunner:
    """Run one admitted task through Harness -> Pi -> Action Gateway."""

    def __init__(
        self,
        *,
        application_factory: Callable[[TaskAdmissionGrant], HarnessApplication] | None = None,
        engine_factory: Callable[[Any, PiSidecarConfig], Any] | None = None,
        executor_factory: Callable[[], ToolExecutor] | None = None,
        environment_preflight: Callable[..., Any] | None = None,
        consent_registry_factory: Callable[[Path], TaskConsentRegistry] | None = None,
        mutation_started_callback: Callable[[dict[str, str]], None] | None = None,
    ) -> None:
        self._application_factory = application_factory or self._default_application
        self._engine_factory = engine_factory or self._default_engine
        self._executor_factory = executor_factory or self._default_executor
        self._environment_preflight = environment_preflight or inspect_project_environment
        self._consent_registry_factory = consent_registry_factory or self._default_consent_registry
        self._mutation_started_callback = mutation_started_callback

    def run(
        self,
        goal: str,
        admission: TaskAdmissionGrant,
        *,
        approval: TaskApprovalGrant | None,
        source: str = "cli",
        conversation_id: str = "",
    ) -> dict[str, object]:
        if not admission.is_mutation and approval is not None:
            raise PermissionError("read-only Pi tasks cannot carry mutation approval")
        normalized_goal = str(goal).strip()
        if not normalized_goal:
            raise ValueError("goal is required")

        mutation_environment = None
        if admission.is_mutation:
            self._require_matching_mutation_approval(
                admission,
                approval,
                conversation_id=conversation_id,
            )
            assert admission.validation is not None
            mutation_environment = require_ready_validation_environment(
                admission,
                command=admission.validation.command,
                cwd=admission.validation.cwd,
                environment_preflight=self._environment_preflight,
            )

        application = self._application_factory(admission)
        consent_registry = (
            self._consent_registry_factory(Path(admission.project_root))
            if admission.is_mutation
            else None
        )
        gateway = ActionGateway(
            application.coordinator,
            self._executor_factory(),
            environment_preflight=self._environment_preflight,
            consent_resolver=consent_registry,
        )
        run = application.start(
            admission.task_id,
            source=source,
            raw_input=normalized_goal,
            goal=normalized_goal,
            session_id=conversation_id,
            route="cli_v2_pi",
        )
        consent = None
        try:
            if admission.is_mutation:
                assert approval is not None
                assert consent_registry is not None
                consent = approval.bind_run(run.run_id)
                consent_registry.activate(consent)
                application.canonical(
                    run,
                    event_type="mutation_consent_bound",
                        payload={
                            "consent_id": consent.consent_id,
                            "approval_id": consent.approval_id,
                            "proposal_id": consent.proposal_id,
                            "admission_id": consent.admission_id,
                            "task_id": consent.task_id,
                        "project_root": consent.project_root,
                        "conversation_id": consent.conversation_id,
                        "run_id": consent.run_id,
                        "protocol_version": consent.protocol_version,
                    },
                    producer="pi_task_runner",
                    idempotency_key=f"mutation-consent:{consent.consent_id}",
                )
                if self._mutation_started_callback is not None:
                    try:
                        self._mutation_started_callback(
                            {
                                "run_id": run.run_id,
                                "consent_id": consent.consent_id,
                                "project_root": admission.project_root,
                            }
                        )
                    except Exception:
                        # Terminal presentation is a derived projection and must
                        # never alter an already recorded permission decision.
                        pass
            application.canonical(
                run,
                event_type="task_received",
                payload={
                    "admission_id": admission.admission_id,
                    "task_id": admission.task_id,
                    "project_root": admission.project_root,
                    "read_files": list(admission.read_files),
                        "write_files": list(admission.write_files),
                        "validation_command": admission.validation.command if admission.validation else "",
                        "admission": admission.model_dump(mode="json"),
                        "environment_id": mutation_environment.environment_id if mutation_environment else "",
                    "protocol_version": admission.protocol_version,
                },
                producer="cli_interaction",
                idempotency_key=f"task-received:{run.run_id}",
            )
            handler = (
                gateway.pi_action_handler(run, admission=admission, consent=consent)
                if admission.is_mutation
                else gateway.pi_read_handler(run, admission=admission)
            )
            engine = self._engine_factory(
                application.coordinator,
                PiSidecarConfig(
                    provider=str(os.getenv("OPENPILOT_PI_PROVIDER") or ""),
                    model=str(os.getenv("OPENPILOT_PI_MODEL") or ""),
                    cwd=admission.project_root,
                    enable_read_tool=True,
                    enable_mutation_tools=admission.is_mutation,
                ),
            )
            result = application.run_pi(
                run.run_id,
                engine=engine,
                prompt=self._pi_prompt(normalized_goal, admission),
                action_handler=handler,
                profile=CompletionProfile.MUTATION if admission.is_mutation else CompletionProfile.READ_ONLY,
                read_only_verifier=(
                    None
                    if admission.is_mutation
                    else lambda _run, _messages: bool(self._response_from_events(application, run.run_id))
                ),
            )
        finally:
            if consent_registry is not None and consent is not None:
                consent_registry.close(consent.consent_id, run_id=run.run_id)
        response = self._response_from_events(application, run.run_id)
        return {**result, "response": response}

    @staticmethod
    def _default_application(admission: TaskAdmissionGrant) -> HarnessApplication:
        evidence = EvidenceStore(
            Path(admission.project_root) / ".openpilot" / "evidence_core"
        )
        return HarnessApplication(evidence, engine="pi")

    @staticmethod
    def _default_engine(coordinator: Any, config: PiSidecarConfig) -> PiRpcEngine:
        return PiRpcEngine(coordinator, config)

    @staticmethod
    def _default_executor() -> ToolExecutor:
        registry = ToolRegistry()
        register_builtin_tools(registry)
        return ToolExecutor(registry)

    @staticmethod
    def _default_consent_registry(project_root: Path) -> TaskConsentRegistry:
        return TaskConsentRegistry(state_directory=project_root / ".openpilot" / "consents")

    @staticmethod
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

    @staticmethod
    def _pi_prompt(goal: str, admission: TaskAdmissionGrant) -> str:
        paths = "\n".join(f"- {path}" for path in admission.read_files)
        if admission.is_mutation:
            write_paths = "\n".join(f"- {path}" for path in admission.write_files)
            assert admission.validation is not None
            return (
                "Complete the user's task only through OpenPilot's admitted mutation surface. "
                "First use openpilot_read for the admitted read paths. Then use openpilot_patch only "
                "for an admitted write path and only after the declared reads have completed. "
                "After a successful patch, use openpilot_validate exactly once with the declared command. "
                "Do not request shell commands, network access, additional paths, or any tool outside "
                "openpilot_read, openpilot_patch, and openpilot_validate.\n\n"
                f"Admitted read paths:\n{paths}\n\n"
                f"Admitted write paths:\n{write_paths}\n\n"
                f"Exact validation command:\n{admission.validation.command}\n\n"
                f"User task:\n{goal}"
            )
        return (
            "Answer the user's task through OpenPilot's admitted read-only surface. "
            "Use openpilot_read only for the listed paths when inspection is needed. "
            "Do not request patches, validation commands, shell commands, network access, "
            "or any path outside that list.\n\n"
            f"Admitted read paths:\n{paths}\n\nUser task:\n{goal}"
        )

    @staticmethod
    def _response_from_events(application: HarnessApplication, run_id: str) -> str:
        for event in reversed(application.coordinator.evidence.load_trajectory_events(run_id)):
            if event.event_type != "model_response":
                continue
            response = PiTaskRunner._response_text(event.payload or {})
            if response:
                return PiTaskRunner._sanitize_terminal_text(response)
        return ""

    @staticmethod
    def _response_text(value: Any, *, depth: int = 0) -> str:
        """Extract the first bounded textual leaf from a Pi model-response record."""

        if depth > 5:
            return ""
        if isinstance(value, str):
            return value.strip()
        if isinstance(value, dict):
            for key in ("text", "content", "message"):
                if key in value:
                    text = PiTaskRunner._response_text(value[key], depth=depth + 1)
                    if text:
                        return text
            for item in value.values():
                text = PiTaskRunner._response_text(item, depth=depth + 1)
                if text:
                    return text
        if isinstance(value, list):
            for item in value:
                text = PiTaskRunner._response_text(item, depth=depth + 1)
                if text:
                    return text
        return ""

    @staticmethod
    def _sanitize_terminal_text(value: str) -> str:
        without_ansi = _ANSI_ESCAPE.sub("", str(value))
        cleaned = "".join(
            character
            for character in without_ansi
            if character not in _BIDI_OR_INVISIBLE
            and (character in {"\n", "\t"} or ord(character) >= 32)
        )
        return cleaned[:_MAX_RESPONSE_CHARS]


__all__ = ["PiTaskRunner"]
