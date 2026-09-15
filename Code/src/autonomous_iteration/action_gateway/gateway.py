"""Phase 4 action gateway adapter around the existing ToolRegistry/Executor."""

from __future__ import annotations

from contextlib import nullcontext
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from autonomous_iteration.run_coordinator import RunCoordinator, RunHandle
from autonomous_iteration.task_consent import TaskConsentRegistry
from autonomous_iteration.validation_environment import (
    effective_validation_command,
    require_ready_validation_environment,
)
from memory.agents.project_environment_tool import inspect_project_environment
from tools.executor_models import ExecutionContext, ExecutionResult
from tools.tool_selection import ToolSelection
from tools.tool_selection import SelectionReason
from tools.tool_executor import ToolExecutor
from metadata import (
    EnvironmentSyncMetadata,
    TaskAdmissionGrant,
    TaskConsentReference,
    ToolInputMetadata,
)
from utils.file_mutation_preconditions import (
    FileMutationPreconditionError,
    assert_file_mutation_precondition,
)


@dataclass(frozen=True)
class ActionRequest:
    call_id: str
    selection: ToolSelection
    mutation: bool = False
    declared_read_files: tuple[str, ...] = ()
    write_scope: tuple[str, ...] = ()
    user_confirmed: bool = False
    mutation_opt_in: bool = False
    admission: TaskAdmissionGrant | None = None
    consent: TaskConsentReference | None = None


@dataclass(frozen=True)
class ValidationRequest:
    call_id: str
    command: str
    cwd: str
    timeout_seconds: int = 120
    admission: TaskAdmissionGrant | None = None
    consent: TaskConsentReference | None = None


@dataclass
class ActionResult:
    call_id: str
    execution: ExecutionResult
    receipt: dict[str, Any] | None = None
    observation_event_id: str = ""
    errors: list[str] = field(default_factory=list)
    verified: bool | None = None


class ActionGateway:
    """Single route from an admitted tool request to execution observations."""

    def __init__(
        self,
        coordinator: RunCoordinator,
        executor: ToolExecutor,
        *,
        environment_preflight: Any | None = None,
        consent_resolver: TaskConsentRegistry | None = None,
    ):
        self.coordinator = coordinator
        self.executor = executor
        self._environment_preflight = environment_preflight or inspect_project_environment
        self._consent_resolver = consent_resolver

    def execute(self, run: RunHandle, request: ActionRequest, *, context: ExecutionContext | None = None) -> ActionResult:
        self._admit(request, run=run)
        selection = request.selection
        if request.mutation:
            self._require_declared_reads_completed(run, request)
            if request.admission is not None:
                selection = self._bind_file_mutation_precondition(request)
                self._require_current_mutation_precondition(selection)
            self.coordinator.record_canonical(
                run,
                event_type="mutation_requested",
                payload={
                    "action": {"kind": "patch"},
                    "tool_name": request.selection.tool_name,
                    "write_scope": list(request.write_scope),
                },
                producer="action_gateway",
                call_id=request.call_id,
                idempotency_key=f"mutation-requested:{request.call_id}",
            )
        consent_lease = (
            self._authorize_live_consent(request.consent, run)
            if request.mutation and request.admission is not None
            else nullcontext()
        )
        with consent_lease:
            self.coordinator.record_canonical(
                run,
                event_type="tool_called",
                payload={
                    "action": {"kind": "patch" if request.mutation else "read"},
                    "tool_name": request.selection.tool_name,
                    "mutation": request.mutation,
                    "declared_read_files": list(request.declared_read_files),
                    "write_scope": list(request.write_scope),
                },
                producer="action_gateway",
                call_id=request.call_id,
                idempotency_key=f"tool-called:{request.call_id}",
            )
            execution = self.executor.execute_single(selection, context)
        event_type = "tool_succeeded" if execution.success else "tool_failed"
        observed = self.coordinator.record_canonical(
            run,
            event_type=event_type,
            payload={
                "tool_name": request.selection.tool_name,
                "success": bool(execution.success),
                "execution_id": execution.execution_id,
                "declared_read_files": list(request.declared_read_files),
            },
            producer="tool_executor",
            call_id=request.call_id,
            idempotency_key=f"tool-result:{request.call_id}",
        )
        receipt = None
        if request.mutation and execution.success:
            receipt = {"call_id": request.call_id, "execution_id": execution.execution_id, "durable": True}
            self.coordinator.record_canonical(
                run,
                event_type="mutation_receipt",
                payload=receipt,
                producer="action_gateway",
                call_id=request.call_id,
                idempotency_key=f"mutation-receipt:{request.call_id}",
            )
        return ActionResult(call_id=request.call_id, execution=execution, receipt=receipt, observation_event_id=observed.event_id)

    @staticmethod
    def _admit(request: ActionRequest, *, run: RunHandle | None = None) -> None:
        if not request.call_id.strip():
            raise ValueError("action call_id is required")
        if request.admission is not None:
            admission = request.admission
            if request.mutation:
                if not admission.is_mutation:
                    raise PermissionError("mutation is outside the task admission")
                if tuple(request.declared_read_files) != tuple(admission.read_files):
                    raise PermissionError("mutation read scope does not match task admission")
                if tuple(request.write_scope) != tuple(admission.write_files):
                    raise PermissionError("mutation write scope does not match task admission")
                ActionGateway._require_matching_consent(admission, request.consent, run=run)
            else:
                if request.write_scope:
                    raise PermissionError("read action cannot carry a write scope")
                if not set(request.declared_read_files).issubset(set(admission.read_files)):
                    raise PermissionError("read scope is outside the task admission")
            return
        if request.mutation:
            if not request.mutation_opt_in or not request.user_confirmed:
                raise PermissionError("mutation requires explicit opt-in and user confirmation")
            if not request.write_scope:
                raise ValueError("mutation requires non-empty write scope")
            if not request.declared_read_files:
                raise ValueError("mutation requires non-empty declared read scope")

    @staticmethod
    def _require_matching_consent(
        admission: TaskAdmissionGrant,
        consent: TaskConsentReference | None,
        *,
        run: RunHandle | None,
    ) -> None:
        if consent is None:
            raise PermissionError("mutation requires a run-bound task consent")
        if (
            consent.admission_id != admission.admission_id
            or consent.task_id != admission.task_id
            or consent.project_root != admission.project_root
            or consent.protocol_version != admission.protocol_version
        ):
            raise PermissionError("mutation consent does not match task admission")
        if run is not None and consent.run_id != run.run_id:
            raise PermissionError("mutation consent belongs to another run")

    def _require_declared_reads_completed(
        self,
        run: RunHandle,
        request: ActionRequest,
    ) -> None:
        completed: set[str] = set()
        for event in self.coordinator.evidence.load_trajectory_events(run.run_id):
            if event.layer.value != "semantic" or event.event_type != "tool_succeeded":
                continue
            payload = event.payload or {}
            if payload.get("tool_name") != "file_reader":
                continue
            completed.update(str(path) for path in payload.get("declared_read_files") or [])
        missing = set(request.declared_read_files) - completed
        if missing:
            raise PermissionError(
                "mutation declared reads are not durably completed: "
                + ", ".join(sorted(missing))
            )

    @staticmethod
    def _require_current_mutation_precondition(selection: ToolSelection) -> None:
        precondition = selection.input_metadata.runtime_handles.get(
            "_file_mutation_precondition"
        )
        if precondition is None:
            raise PermissionError("mutation file precondition is missing for the admitted write target")
        try:
            assert_file_mutation_precondition(precondition.path, precondition)
        except (AttributeError, FileMutationPreconditionError) as exc:
            raise PermissionError(str(exc) or "mutation file precondition is invalid") from exc

    @staticmethod
    def _bind_file_mutation_precondition(request: ActionRequest) -> ToolSelection:
        admission = request.admission
        if admission is None:
            return request.selection
        if request.selection.tool_name != "file_patch_writer":
            raise PermissionError("admitted mutation requires the file_patch_writer")
        raw_path = str(request.selection.input_metadata.file_path or "").strip()
        root = Path(admission.project_root).expanduser().resolve(strict=False)
        candidate = Path(raw_path).expanduser()
        if not candidate.is_absolute():
            candidate = root / candidate
        admitted_paths = {
            Path(path).expanduser().resolve(strict=False): path
            for path in admission.write_files
        }
        path = admitted_paths.get(candidate.resolve(strict=False))
        if path is None:
            raise PermissionError("mutation patch target is outside the admitted write scope")
        preconditions = {item.path: item for item in admission.write_preconditions}
        precondition = preconditions.get(path)
        if precondition is None:
            raise PermissionError("mutation file precondition is missing for the admitted write target")
        payload = request.selection.input_metadata.to_params()
        payload["file_path"] = path
        payload["_file_mutation_precondition"] = precondition
        return request.selection.model_copy(
            update={
                "input_metadata": ToolInputMetadata.from_mapping(
                    "file_patch_writer",
                    payload,
                )
            }
        )

    def execute_validation(
        self,
        run: RunHandle,
        request: ValidationRequest,
        *,
        requested_command: str,
        context: ExecutionContext | None = None,
    ) -> ActionResult:
        if requested_command != request.command:
            raise PermissionError("validation must use the exact declared command")
        validation_environment: EnvironmentSyncMetadata | None = None
        effective_command = request.command
        effective_cwd = request.cwd
        effective_env: dict[str, str] = {}
        if request.admission is not None:
            admitted_validation = request.admission.validation
            if (
                admitted_validation is None
                or request.command != admitted_validation.command
                or request.cwd != admitted_validation.cwd
                or request.timeout_seconds != admitted_validation.timeout_seconds
            ):
                raise PermissionError("validation request does not match task admission")
            if request.admission.is_mutation:
                self._require_matching_consent(
                    request.admission,
                    request.consent,
                    run=run,
                )
                self._require_mutation_receipt(run)
                validation_environment = self._require_ready_validation_environment(request)
                effective_command = self._effective_validation_command(
                    request.command,
                    validation_environment,
                )
                effective_cwd = validation_environment.command_cwd
                effective_env = dict(validation_environment.command_env)
        validation_consent_lease = (
            self._authorize_live_consent(request.consent, run)
            if request.admission is not None and request.admission.is_mutation
            else nullcontext()
        )
        with validation_consent_lease:
            self.coordinator.record_canonical(
                run,
                event_type="validation_started",
                payload={
                    "command": request.command,
                    "effective_command": effective_command,
                    "cwd": effective_cwd,
                    "environment_id": validation_environment.environment_id if validation_environment else "",
                    "python_executable": validation_environment.python_executable if validation_environment else "",
                },
                producer="action_gateway",
                call_id=request.call_id,
                idempotency_key=f"validation-started:{request.call_id}",
            )
            selection = ToolSelection(
                step_id=request.call_id,
                tool_name="command_executor",
                reason=SelectionReason.ONLY_OPTION,
                input_metadata=ToolInputMetadata.from_mapping(
                    "command_executor",
                    {
                        "command": effective_command,
                        "requested_command": request.command,
                        "effective_command": effective_command,
                        "cwd": effective_cwd,
                        "env": effective_env,
                        "project_path": request.admission.project_root if request.admission is not None else request.cwd,
                        "mode": "automatic",
                        "timeout": request.timeout_seconds,
                    },
                ),
            )
            result = self.execute(
                run,
                ActionRequest(call_id=request.call_id, selection=selection),
                context=context,
            )
        output = getattr(result.execution, "output_metadata", None)
        artifact = getattr(output, "result", None)
        exit_code = getattr(artifact, "exit_code", None)
        artifact_success = getattr(artifact, "success", None)
        passed = (
            bool(result.execution.success)
            and (exit_code is None or int(exit_code) == 0)
            and artifact_success is not False
        )
        result.verified = passed
        completed = self.coordinator.record_canonical(
            run,
            event_type="validation_completed",
            payload={
                "command": request.command,
                "effective_command": effective_command,
                "cwd": effective_cwd,
                "environment_id": validation_environment.environment_id if validation_environment else "",
                "python_executable": validation_environment.python_executable if validation_environment else "",
                "success": passed,
                "execution_id": result.execution.execution_id,
                "exit_code": exit_code,
            },
            producer="action_gateway",
            call_id=request.call_id,
            idempotency_key=f"validation-completed:{request.call_id}",
        )
        self.coordinator.record_canonical(
            run,
            event_type="verification_state_changed",
            payload={
                "verification_status": "passed" if passed else "failed",
                "validation_event_id": completed.event_id,
            },
            producer="verification",
            call_id=request.call_id,
            idempotency_key=f"verification:{request.call_id}",
        )
        return result

    def _require_mutation_receipt(self, run: RunHandle) -> None:
        for event in self.coordinator.evidence.load_trajectory_events(run.run_id):
            if event.event_type != "mutation_receipt":
                continue
            payload = event.payload or {}
            if payload.get("durable") is True:
                return
        raise PermissionError("mutation validation requires a durable mutation receipt")

    def _authorize_live_consent(
        self,
        consent: TaskConsentReference | None,
        run: RunHandle,
    ):
        if self._consent_resolver is None:
            raise PermissionError("mutation requires an action-time consent resolver")
        return self._consent_resolver.authorize(consent, run_id=run.run_id)

    def _require_ready_validation_environment(
        self,
        request: ValidationRequest,
    ) -> EnvironmentSyncMetadata:
        admission = request.admission
        assert admission is not None
        return require_ready_validation_environment(
            admission,
            command=request.command,
            cwd=request.cwd,
            environment_preflight=self._environment_preflight,
        )

    @staticmethod
    def _effective_validation_command(
        requested_command: str,
        environment: EnvironmentSyncMetadata,
    ) -> str:
        return effective_validation_command(requested_command, environment)

    def pi_read_handler(
        self,
        run: RunHandle,
        *,
        allowed_read_files: tuple[str, ...] = (),
        admission: TaskAdmissionGrant | None = None,
        context: ExecutionContext | None = None,
    ):
        """Build the only Pi read-tool callback admitted by OpenPilot."""

        if admission is not None:
            if allowed_read_files:
                raise ValueError("admitted Pi read handler cannot accept a loose read scope")
            allowed_read_files = tuple(admission.read_files)
        allowed = {str(path) for path in allowed_read_files}
        admitted_paths: dict[Path, str] = {}
        project_root: Path | None = None
        if admission is not None:
            project_root = Path(admission.project_root).expanduser().resolve(strict=False)
            admitted_paths = {
                Path(path).expanduser().resolve(strict=False): str(path)
                for path in allowed_read_files
            }

        def handle(request: dict[str, Any]) -> str:
            if request.get("toolName") != "openpilot_read":
                raise ValueError("unsupported Pi tool")
            call_id = str(request.get("toolCallId") or "").strip()
            args = request.get("args") if isinstance(request.get("args"), dict) else {}
            path = str(args.get("path") or "").strip()
            if not call_id or not path:
                raise ValueError("Pi read request requires call id and path")
            if project_root is not None:
                candidate = Path(path).expanduser()
                if not candidate.is_absolute():
                    candidate = project_root / candidate
                canonical_path = admitted_paths.get(candidate.resolve(strict=False))
                if canonical_path is None:
                    raise PermissionError(f"Pi read path is outside declared scope: {path}")
                path = canonical_path
            elif path not in allowed:
                raise PermissionError(f"Pi read path is outside declared scope: {path}")
            selection = ToolSelection(
                step_id=call_id,
                tool_name="file_reader",
                reason=SelectionReason.ONLY_OPTION,
                input_metadata=ToolInputMetadata.from_mapping(
                    "file_reader", {"file_path": path}
                ),
            )
            result = self.execute(
                run,
                ActionRequest(
                    call_id=call_id,
                    selection=selection,
                    declared_read_files=(path,),
                    admission=admission,
                ),
                context=context,
            )
            if not result.execution.success:
                error = result.execution.error
                raise RuntimeError(
                    str(getattr(error, "error_message", "") or "file_reader failed")
                )
            payload = getattr(result.execution.output_metadata, "result", None)
            content = getattr(payload, "content", None)
            if content is not None:
                return str(content)
            if hasattr(payload, "model_dump"):
                return str(payload.model_dump(mode="json"))
            return str(payload or "")

        return handle

    def pi_action_handler(
        self,
        run: RunHandle,
        *,
        allowed_read_files: tuple[str, ...] = (),
        allowed_write_files: tuple[str, ...] = (),
        validation: ValidationRequest | None = None,
        mutation_opt_in: bool = False,
        user_confirmed: bool = False,
        admission: TaskAdmissionGrant | None = None,
        consent: TaskConsentReference | None = None,
        context: ExecutionContext | None = None,
    ):
        """Build the complete fixed Pi tool surface owned by Action Gateway."""

        if admission is not None:
            if (
                allowed_read_files
                or allowed_write_files
                or validation is not None
                or mutation_opt_in
                or user_confirmed
            ):
                raise ValueError("admitted Pi mutation handler cannot accept loose authority fields")
            if not admission.is_mutation or admission.validation is None:
                raise ValueError("Pi mutation handler requires an admitted mutation task")
            allowed_read_files = tuple(admission.read_files)
            allowed_write_files = tuple(admission.write_files)
            validation = ValidationRequest(
                call_id="validation",
                command=admission.validation.command,
                cwd=admission.validation.cwd,
                timeout_seconds=admission.validation.timeout_seconds,
                admission=admission,
                consent=consent,
            )
        if validation is None:
            raise ValueError("Pi mutation handler requires an exact validation request")

        read = (
            self.pi_read_handler(run, admission=admission, context=context)
            if admission is not None
            else self.pi_read_handler(
                run,
                allowed_read_files=allowed_read_files,
                context=context,
            )
        )
        read_scope = tuple(str(path) for path in allowed_read_files)
        write_scope = tuple(str(path) for path in allowed_write_files)
        project_root = Path(validation.cwd).expanduser().resolve(strict=False)

        def normalize_declared(raw_path: str) -> Path:
            candidate = Path(raw_path).expanduser()
            if not candidate.is_absolute():
                candidate = project_root / candidate
            return candidate.resolve(strict=False)

        normalized_reads = {
            normalize_declared(path): path for path in read_scope
        }
        normalized_writes = {
            normalize_declared(path): path for path in write_scope
        }

        def admitted_path(raw_path: Any, scope: dict[Path, str]) -> str | None:
            candidate = Path(str(raw_path or "")).expanduser()
            if not candidate.is_absolute():
                candidate = project_root / candidate
            return scope.get(candidate.resolve(strict=False))

        def handle(request: dict[str, Any]) -> Any:
            tool_name = str(request.get("toolName") or "")
            call_id = str(request.get("toolCallId") or "").strip()
            args = request.get("args") if isinstance(request.get("args"), dict) else {}
            if tool_name == "openpilot_read":
                path = admitted_path(args.get("path"), normalized_reads)
                if path is None:
                    raise PermissionError("Pi read path is outside declared scope")
                normalized_request = dict(request)
                normalized_request["args"] = {**args, "path": path}
                return read(normalized_request)
            if tool_name == "openpilot_patch":
                path = admitted_path(args.get("path"), normalized_writes)
                if not call_id or path is None:
                    raise PermissionError("Pi patch path is outside declared write scope")
                selection = ToolSelection(
                    step_id=call_id,
                    tool_name="file_patch_writer",
                    reason=SelectionReason.ONLY_OPTION,
                    input_metadata=ToolInputMetadata.from_mapping(
                        "file_patch_writer",
                        {
                            "file_path": path,
                            "line_start": args.get("lineStart"),
                            "line_end": args.get("lineEnd"),
                            "replacement_text": args.get("replacementText"),
                            "operation_kind": "modify_symbol",
                            "_post_processing_write_scope": list(write_scope),
                        },
                    ),
                )
                result = self.execute(
                    run,
                    ActionRequest(
                        call_id=call_id,
                        selection=selection,
                        mutation=True,
                        declared_read_files=read_scope,
                        write_scope=write_scope,
                        user_confirmed=user_confirmed,
                        mutation_opt_in=mutation_opt_in,
                        admission=admission,
                        consent=consent,
                    ),
                    context=context,
                )
                return {"success": bool(result.execution.success), "receipt": result.receipt}
            if tool_name == "openpilot_validate":
                if not call_id:
                    raise ValueError("Pi validation request requires call id")
                exact = ValidationRequest(
                    call_id=call_id,
                    command=validation.command,
                    cwd=validation.cwd,
                    timeout_seconds=validation.timeout_seconds,
                    admission=validation.admission,
                    consent=validation.consent,
                )
                result = self.execute_validation(
                    run,
                    exact,
                    requested_command=str(args.get("command") or ""),
                    context=context,
                )
                if result.verified is not True:
                    raise RuntimeError("exact validation failed")
                return {"success": True}
            raise ValueError("unsupported Pi tool")

        return handle
