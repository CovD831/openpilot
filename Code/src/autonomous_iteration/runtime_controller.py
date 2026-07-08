"""Phase-driven agent runtime controller and deterministic safeguards."""

from __future__ import annotations

import time
import uuid
import shlex
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from autonomous_iteration.task_models import TaskStatus
from core.semantic_types import TaskCard
from core.exceptions import InvalidLLMResponseError, LLMProviderError, LLMTimeoutError
from memory.project_path_resolver import ProjectPathResolver, ground_command_paths_within_project
from metadata import (
    AgentPhase,
    DecisionNeedMetadata,
    EditPlanMetadata,
    FailureMetadata,
    GuardDecisionMetadata,
    PathIntentMetadata,
    RuntimeReportMetadata,
    RuntimeStateMetadata,
    ToolDecisionMetadata,
    ToolInputMetadata,
    VerificationPlanMetadata,
)
from tools.tool_selection import SelectionReason, ToolSelection
from utils.path_boundary import resolve_project_path


WRITE_TOOLS = {"file_writer", "file_patch_writer", "file_delete_tool"}
READ_TOOLS = {"file_reader", "multi_file_reader"}
EXECUTION_TOOLS = {"command_executor", "code_executor"}
FILE_CREATE_OPERATIONS = {"create_file", "file_create", "directory_generate"}
NON_EXECUTABLE_FILE_SUFFIXES = {
    ".cfg",
    ".conf",
    ".ini",
    ".json",
    ".md",
    ".rst",
    ".toml",
    ".txt",
    ".yaml",
    ".yml",
}
READ_ONLY_TASK_TAGS = {"analysis", "inspect", "inspection", "investigate", "readonly", "read_only", "understanding"}
READ_ONLY_TASK_TYPES = {"analysis", "inspection", "investigation", "document_summary", "codebase_understanding"}
READ_ONLY_TASK_TERMS = (
    "analy",
    "architecture",
    "explain",
    "inspect",
    "investigate",
    "review",
    "trace",
    "分析",
    "排查",
    "梳理",
    "理解",
    "解释",
    "取证",
)
READ_ONLY_BLOCKED_TOOLS = WRITE_TOOLS | {"bug_fix_tool", "code_generator", "code_unit_generator", "code_editor", "code_executor", "readme_tool"}
RISK_ORDER = {"low": 0, "medium": 1, "high": 2, "forbidden": 3}
PHASE_SEQUENCE = [
    AgentPhase.UNDERSTAND_TASK,
    AgentPhase.UNDERSTAND_PROJECT,
    AgentPhase.DIAGNOSE,
    AgentPhase.PLAN,
    AgentPhase.EXECUTE,
    AgentPhase.VERIFY,
    AgentPhase.REPLAN,
    AgentPhase.SUMMARIZE,
]


def is_read_only_analysis_goal(
    goal: str,
    *,
    tags: list[str] | None = None,
    task_type: str = "",
) -> bool:
    normalized_tags = {str(tag or "").strip().lower() for tag in tags or [] if str(tag or "").strip()}
    if normalized_tags.intersection(READ_ONLY_TASK_TAGS):
        return True
    normalized_task_type = str(task_type or "").strip().lower()
    if normalized_task_type in READ_ONLY_TASK_TYPES:
        return True
    lowered_goal = str(goal or "").strip().lower()
    if not lowered_goal:
        return False
    return any(term in lowered_goal for term in READ_ONLY_TASK_TERMS)


def apply_read_only_runtime_mode(
    state: RuntimeStateMetadata,
    goal: str,
    *,
    tags: list[str] | None = None,
    task_type: str = "",
) -> bool:
    if not is_read_only_analysis_goal(goal, tags=tags, task_type=task_type):
        return False
    marker = "runtime_mode:read_only_analysis"
    if marker not in state.assumptions:
        state.add_assumption(marker)
    state.add_fact("Task classified as read-only analysis; gather evidence before any mutation.")
    return True


def _state_is_read_only_analysis(state: RuntimeStateMetadata) -> bool:
    return "runtime_mode:read_only_analysis" in state.assumptions


def _command_looks_mutating(command: str) -> bool:
    lowered = f" {str(command or '').lower()} "
    patterns = (
        " rm ",
        " mv ",
        " cp ",
        " mkdir ",
        " touch ",
        " chmod ",
        " chown ",
        " tee ",
        " pip install ",
        " pip3 install ",
        " npm install ",
        " npm add ",
        " pnpm add ",
        " yarn add ",
        " git checkout ",
        " git switch ",
        " git commit ",
        " git reset ",
        " git clean ",
        " git apply ",
        " git am ",
    )
    return any(pattern in lowered for pattern in patterns) or " >" in lowered or ">>" in lowered or "sed -i" in lowered


def _phase_value(phase: AgentPhase | str) -> str:
    return phase.value if isinstance(phase, AgentPhase) else str(phase)


def _phase_is(phase: AgentPhase | str, expected: AgentPhase) -> bool:
    return _phase_value(phase) == expected.value


def _is_new_file_create(tool_name: str, file_path: Any, operation_kind: Any) -> bool:
    if tool_name != "file_writer":
        return False
    operation = str(operation_kind or "").lower()
    if operation and operation not in FILE_CREATE_OPERATIONS:
        return False
    if not file_path:
        return False
    try:
        return not Path(str(file_path)).expanduser().exists()
    except OSError:
        return False


class RuntimeGuard:
    """Centralized runtime policy for budgets, risk, and confirmation gates."""

    def approve_need(self, state: RuntimeStateMetadata, need: DecisionNeedMetadata, tool_name: str) -> GuardDecisionMetadata:
        if _phase_is(state.phase, AgentPhase.BLOCKED):
            return GuardDecisionMetadata(
                approved=False,
                reason=state.completion_reason or "runtime is blocked",
                risk_level=need.risk_level,
            )

        if self._risk_value(need.risk_level) >= self._risk_value("forbidden"):
            return GuardDecisionMetadata(
                approved=False,
                reason=f"Need '{need.question}' is forbidden risk.",
                risk_level=need.risk_level,
            )

        if self._risk_value(need.risk_level) >= self._risk_value("high"):
            return GuardDecisionMetadata(
                approved=False,
                reason=f"Need '{need.question}' requires user confirmation.",
                risk_level=need.risk_level,
                attributes={"requires_user_confirmation": True, "tool_name": tool_name},
            )

        if _state_is_read_only_analysis(state):
            read_only_block = self._read_only_restriction(state, need, tool_name)
            if read_only_block is not None:
                return read_only_block

        read_count = 1 if tool_name in READ_TOOLS else 0
        file_path = need.target_path or need.attributes.get("file_path")
        operation_kind = need.operation_kind or need.attributes.get("operation_kind")
        create_count = 1 if _is_new_file_create(tool_name, file_path, operation_kind) else 0
        edit_count = 1 if tool_name in WRITE_TOOLS and not create_count else 0
        if not state.budget.has_tool_budget(reads=read_count, edits=edit_count, creates=create_count):
            return GuardDecisionMetadata(
                approved=False,
                reason="; ".join(state.budget.exhausted_reasons()) or "runtime budget exhausted",
                risk_level=need.risk_level,
            )

        return GuardDecisionMetadata(
            approved=True,
            reason="Need is within runtime risk and budget policy.",
            risk_level=need.risk_level,
            attributes={"requires_confirmation": self.requires_confirmation(tool_name, need)},
        )

    def _read_only_restriction(
        self,
        state: RuntimeStateMetadata,
        need: DecisionNeedMetadata,
        tool_name: str,
    ) -> GuardDecisionMetadata | None:
        if tool_name in READ_ONLY_BLOCKED_TOOLS:
            return GuardDecisionMetadata(
                approved=False,
                reason=f"Read-only analysis task cannot use mutation tool '{tool_name}'. Gather evidence first and wait for explicit write mode.",
                risk_level=need.risk_level,
                attributes={"guard_kind": "read_only_analysis", "tool_name": tool_name},
            )
        if tool_name == "command_executor" and _command_looks_mutating(need.command or ""):
            return GuardDecisionMetadata(
                approved=False,
                reason="Read-only analysis task cannot run mutating shell commands.",
                risk_level=need.risk_level,
                attributes={"guard_kind": "read_only_analysis", "command": need.command or ""},
            )
        if self._read_only_file_read_lacks_project_context(state, need, tool_name):
            return GuardDecisionMetadata(
                approved=False,
                reason=(
                    "Read-only analysis file reads require project_path/cwd or prior path evidence before "
                    "reading a model-proposed path."
                ),
                risk_level=need.risk_level,
                attributes={"guard_kind": "read_only_path_grounding", "tool_name": tool_name},
            )
        return None

    def _read_only_file_read_lacks_project_context(
        self,
        state: RuntimeStateMetadata,
        need: DecisionNeedMetadata,
        tool_name: str,
    ) -> bool:
        if tool_name != "file_reader":
            return False
        attrs = need.attributes or {}
        if attrs.get("project_path") or attrs.get("cwd"):
            return False
        raw_path = str(need.target_path or attrs.get("file_path") or "").strip()
        if not raw_path:
            return False
        if raw_path in state.candidate_files or raw_path in state.selected_files:
            return False
        path = Path(raw_path).expanduser()
        if path.is_absolute():
            hallucinated_roots = ("/workspace/openpilot", "/workspace/project", "/openpilot")
            return raw_path.rstrip("/") in hallucinated_roots or raw_path.startswith(tuple(f"{root}/" for root in hallucinated_roots))
        return raw_path not in {".", "./"}

    def requires_confirmation(self, tool_name: str, need: DecisionNeedMetadata, registry: Any | None = None) -> bool:
        if self._risk_value(need.risk_level) >= self._risk_value("high"):
            return True
        if tool_name in WRITE_TOOLS:
            return True
        if registry and hasattr(registry, "get"):
            definition = registry.get(tool_name)
            permission_level = str(getattr(definition, "permission_level", "") or "").lower()
            return permission_level in {"high", "forbidden"}
        return False

    def should_replan(self, state: RuntimeStateMetadata) -> str | None:
        if state.verification_status == "failed":
            return "verification failed"
        if state.budget.exhausted_reasons():
            return "; ".join(state.budget.exhausted_reasons())
        if state.risk_level == "high" and not state.planned_edits:
            return "risk increased before an executable plan exists"
        return None

    def _risk_value(self, risk_level: str | None) -> int:
        return RISK_ORDER.get(str(risk_level or "medium").lower(), 1)


class ToolRouter:
    """Map explicit decision needs to tool selections under budget/risk limits."""

    def __init__(self, registry: Any | None = None, guard: RuntimeGuard | None = None) -> None:
        self.registry = registry
        self.guard = guard or RuntimeGuard()

    def route(self, state: RuntimeStateMetadata, need: DecisionNeedMetadata) -> list[ToolSelection]:
        """Return tool selections for a need, or block the state if routing is unsafe."""
        tool_name = self._tool_for_need(need)
        if not tool_name:
            state.add_unknown(need.question)
            return []

        guard_decision = self.guard.approve_need(state, need, tool_name)
        if not guard_decision.approved:
            if guard_decision.attributes.get("requires_user_confirmation"):
                state.phase = AgentPhase.ASK_USER
                state.completion_reason = guard_decision.reason
            else:
                state.block(guard_decision.reason)
            state.record_tool_event(
                {
                    "event_type": "runtime_guard",
                    "tool_name": tool_name,
                    "approved": False,
                    "reason": guard_decision.reason,
                    "guard_kind": guard_decision.attributes.get("guard_kind", ""),
                }
            )
            return []

        input_metadata = self._input_for_need(state, tool_name, need)
        if input_metadata is None:
            state.add_unknown(need.question)
            return []

        if tool_name in WRITE_TOOLS:
            target_path = need.target_path or need.attributes.get("file_path")
            if target_path:
                evidence = need.decision_to_unlock or need.question
                state.add_candidate_file(str(target_path), f"Decision need target: {evidence}")

        requires_confirmation = bool(guard_decision.attributes.get("requires_confirmation"))
        decision = ToolDecisionMetadata(
            need_type=need.need_type,
            question=need.question,
            selected_tool=tool_name,
            phase=need.phase,
            reason=self._decision_reason(tool_name, need),
            alternatives_considered=self._alternatives_for_need(need),
            expected_state_change=need.expected_state_change,
            risk_level=need.risk_level,
            cost_hint=need.cost_hint,
            requires_confirmation=requires_confirmation,
        )
        state.record_tool_decision(decision)
        return [
            ToolSelection(
                step_id=need.attributes.get("step_id") or f"{need.phase.value}_{uuid.uuid4().hex[:8]}",
                tool_name=tool_name,
                reason=SelectionReason.CAPABILITY_MATCH,
                confidence=0.85,
                input_metadata=input_metadata,
                requires_confirmation=requires_confirmation,
                fallback_tools=[],
                depends_on=[],
                timeout_override=need.attributes.get("timeout"),
            )
        ]

    def _tool_for_need(self, need: DecisionNeedMetadata) -> str | None:
        need_type = need.need_type.lower().replace("-", "_")
        if need_type in {"file_read", "read_file", "inspect_file"}:
            if self._looks_like_directory_need(need):
                return "multi_file_reader"
            return "file_reader"
        if need_type in {"project_structure", "directory_read", "read_directory", "multi_file_read"}:
            return "multi_file_reader"
        if need_type in {"web_search", "reference_search", "research"}:
            return "web_searcher"
        if need_type in {"command_check", "smoke_test", "test", "verify_command"}:
            return "command_executor"
        if need_type in {"bug_fix", "bug_fix_tool", "fix_bug", "repair"}:
            return "bug_fix_tool"
        operation_kind = str(need.operation_kind or need.attributes.get("operation_kind") or "").lower()
        if need_type in {"file_delete", "delete_file", "remove_file"}:
            return "file_delete_tool"
        if need_type in {"file_write", "write_file"}:
            if operation_kind in {"add_symbol", "modify_symbol", "code_patch", "code_unit_generate", "code_symbol_modify"}:
                return "file_patch_writer"
            if operation_kind in {"delete_file", "file_delete", "remove_file"}:
                return "file_delete_tool"
            return "file_writer"
        if need_type == "code_file_create" and self._looks_like_non_executable_file_need(need):
            target_path = need.target_path or need.attributes.get("file_path")
            if target_path and Path(str(target_path)).name.lower().startswith("readme"):
                return "readme_tool"
            return "file_writer"
        if need_type in {"code_file_create", "directory_generate"}:
            return "code_generator"
        if need_type in {"code_unit_generate", "generate_code_unit", "add_symbol"}:
            return "code_unit_generator"
        if need_type in {"code_symbol_modify", "code_patch", "modify_symbol"}:
            return "code_editor"
        if need_type in {"code_generation", "generate_code", "code_generator"}:
            if operation_kind in {"add_symbol", "code_unit_generate"}:
                return "code_unit_generator"
            if operation_kind in {"modify_symbol", "code_patch", "code_symbol_modify"}:
                return "code_editor"
            return "code_generator"
        if need_type in {"code_execution", "execute_code", "run_code"}:
            if need.command or need.attributes.get("command"):
                return "command_executor"
            return "code_executor"
        if need_type in {"readme_generation", "readme", "documentation"}:
            return "readme_tool"
        return None

    def _input_for_need(self, state: RuntimeStateMetadata, tool_name: str, need: DecisionNeedMetadata) -> ToolInputMetadata | None:
        attrs = dict(need.attributes)
        project_path = self._project_root_from_attrs(attrs)
        if tool_name == "file_reader":
            file_path = need.target_path or attrs.get("file_path")
            if not file_path:
                return None
            resolved_file_path = self._resolve_single_path(
                state,
                raw_path=file_path,
                project_path=project_path,
                operation="read",
                intent_kind="existing_file",
                source=f"{tool_name}:file_path",
                evidence=[need.question],
            )
            if not resolved_file_path or self._path_is_existing_directory(resolved_file_path):
                return None
            payload = dict(attrs)
            payload["file_path"] = resolved_file_path
            if project_path:
                payload["project_path"] = project_path
            return ToolInputMetadata.from_mapping(tool_name, payload)
        if tool_name == "multi_file_reader":
            payload: dict[str, Any] = dict(attrs)
            if need.candidate_paths:
                payload["file_paths"] = self._resolve_many_paths(
                    state,
                    raw_paths=need.candidate_paths,
                    project_path=project_path,
                    operation="read",
                    intent_kind="existing_file",
                    source=f"{tool_name}:file_paths",
                    evidence=[need.question],
                )
                if not payload["file_paths"]:
                    return None
            elif need.target_path:
                resolved_directory = self._resolve_single_path(
                    state,
                    raw_path=need.target_path,
                    project_path=project_path,
                    operation="read",
                    intent_kind="existing_directory",
                    source=f"{tool_name}:directory_path",
                    evidence=[need.question],
                )
                if not resolved_directory:
                    return None
                payload["directory_path"] = resolved_directory
            elif project_path and self._looks_like_project_root_read_need(need):
                payload["directory_path"] = project_path
            if payload.get("directory_path") and not payload.get("pattern"):
                if self._should_use_directory_sketch(need, payload):
                    payload["pattern"] = "sketch.json"
                    payload.setdefault("max_files", 1)
                else:
                    payload["pattern"] = "*"
            if project_path:
                payload["project_path"] = project_path
            if not payload.get("file_paths") and not payload.get("directory_path"):
                return None
            return ToolInputMetadata.from_mapping(tool_name, payload)
        if tool_name == "web_searcher":
            query = need.query or attrs.get("query") or need.question
            return ToolInputMetadata.from_mapping(tool_name, {"query": query, **attrs})
        if tool_name == "command_executor":
            command = need.command or attrs.get("command")
            if not command:
                return None
            payload = {"command": command, "mode": attrs.get("mode", "automatic"), **attrs}
            cwd = attrs.get("cwd") or project_path
            if cwd and project_path:
                resolved_cwd = self._resolve_single_path(
                    state,
                    raw_path=cwd,
                    project_path=project_path,
                    operation="execute",
                    intent_kind="command_cwd",
                    source=f"{tool_name}:cwd",
                    evidence=[need.question, command],
                )
                if not resolved_cwd:
                    return None
                payload["cwd"] = resolved_cwd
            if project_path:
                resolved_command = self._resolve_command_text(
                    state,
                    command=command,
                    project_path=project_path,
                    source=f"{tool_name}:command",
                    evidence=[need.question, command],
                )
                if not resolved_command:
                    return None
                payload["command"] = resolved_command
                payload["project_path"] = project_path
            return ToolInputMetadata.from_mapping(tool_name, payload)
        if tool_name == "bug_fix_tool":
            command = need.command or attrs.get("command")
            file_paths = attrs.get("file_paths") or need.candidate_paths
            if not command or not file_paths:
                return None
            payload = dict(attrs)
            payload["command"] = command
            if project_path:
                payload["file_paths"] = self._resolve_many_paths(
                    state,
                    raw_paths=file_paths,
                    project_path=project_path,
                    operation="read",
                    intent_kind="existing_file",
                    source=f"{tool_name}:file_paths",
                    evidence=[need.question, command],
                )
                if not payload["file_paths"]:
                    return None
            else:
                payload["file_paths"] = file_paths
            return ToolInputMetadata.from_mapping(tool_name, payload)
        if tool_name == "file_writer":
            file_path = need.target_path or attrs.get("file_path")
            content = attrs.get("content")
            if not file_path:
                return None
            payload = dict(attrs)
            if project_path:
                requested_operation_kind = need.operation_kind or attrs.get("operation_kind")
                intent_kind = "planned_new_file" if str(requested_operation_kind or "").lower() in FILE_CREATE_OPERATIONS else "existing_file"
                resolved_file_path = self._resolve_single_path(
                    state,
                    raw_path=file_path,
                    project_path=project_path,
                    operation="write",
                    intent_kind=intent_kind,
                    source=f"{tool_name}:file_path",
                    evidence=[need.question],
                )
                if not resolved_file_path:
                    return None
                payload["file_path"] = resolved_file_path
            else:
                payload["file_path"] = file_path
            operation_kind = self._file_writer_operation_kind(
                payload["file_path"],
                need.operation_kind or attrs.get("operation_kind"),
                attrs.get("overwrite", True),
            )
            if operation_kind:
                payload["operation_kind"] = operation_kind
            if content is not None:
                payload["content"] = content
            if project_path:
                payload["project_path"] = project_path
            return ToolInputMetadata.from_mapping(tool_name, payload)
        if tool_name == "file_patch_writer":
            file_path = need.target_path or attrs.get("file_path")
            if not file_path:
                return None
            resolved_file_path = self._resolve_single_path(
                state,
                raw_path=file_path,
                project_path=project_path,
                operation="patch",
                intent_kind="existing_file",
                source=f"{tool_name}:file_path",
                evidence=[need.question],
            )
            if not resolved_file_path:
                return None
            payload = {
                "file_path": resolved_file_path,
                "operation_kind": need.operation_kind or attrs.get("operation_kind") or "modify_symbol",
                "target_scope": need.target_scope or attrs.get("target_scope"),
                "symbol_name": need.symbol_name or attrs.get("symbol_name"),
                "symbol_type": need.symbol_type or attrs.get("symbol_type"),
                "insertion_hint": need.insertion_hint or attrs.get("insertion_hint"),
                "patch_mode": need.patch_mode or attrs.get("patch_mode"),
                **attrs,
            }
            if project_path:
                payload["project_path"] = project_path
            return ToolInputMetadata.from_mapping(tool_name, payload)
        if tool_name == "file_delete_tool":
            file_path = need.target_path or attrs.get("file_path")
            if not file_path:
                return None
            resolved_file_path = self._resolve_single_path(
                state,
                raw_path=file_path,
                project_path=project_path,
                operation="delete",
                intent_kind="existing_file",
                source=f"{tool_name}:file_path",
                evidence=[need.question],
            )
            if not resolved_file_path:
                return None
            payload = dict(attrs)
            payload["file_path"] = resolved_file_path
            payload["operation_kind"] = need.operation_kind or attrs.get("operation_kind") or "delete_file"
            if project_path:
                payload["project_path"] = project_path
            return ToolInputMetadata.from_mapping(tool_name, payload)
        if tool_name == "code_generator":
            task_description = attrs.get("task_description") or need.question
            return ToolInputMetadata.from_mapping(
                tool_name,
                {
                    "task_description": task_description,
                    "language": attrs.get("language", "python"),
                    "operation_kind": need.operation_kind or attrs.get("operation_kind") or "file_create",
                    **attrs,
                },
            )
        if tool_name == "code_unit_generator":
            task_description = attrs.get("task_description") or need.question
            file_path = need.target_path or attrs.get("file_path")
            if file_path and project_path:
                resolved_file_path = self._resolve_single_path(
                    state,
                    raw_path=file_path,
                    project_path=project_path,
                    operation="read",
                    intent_kind="existing_file",
                    source=f"{tool_name}:file_path",
                    evidence=[need.question],
                )
                if not resolved_file_path:
                    return None
                file_path = resolved_file_path
            return ToolInputMetadata.from_mapping(
                tool_name,
                {
                    "task_description": task_description,
                    "language": attrs.get("language", "python"),
                    "file_path": file_path,
                    "operation_kind": need.operation_kind or attrs.get("operation_kind") or "add_symbol",
                    "target_scope": need.target_scope or attrs.get("target_scope") or "symbol",
                    "symbol_name": need.symbol_name or attrs.get("symbol_name"),
                    "symbol_type": need.symbol_type or attrs.get("symbol_type"),
                    "insertion_hint": need.insertion_hint or attrs.get("insertion_hint"),
                    **attrs,
                },
            )
        if tool_name == "code_editor":
            task_description = attrs.get("task_description") or need.question
            file_path = need.target_path or attrs.get("file_path")
            if file_path and project_path:
                resolved_file_path = self._resolve_single_path(
                    state,
                    raw_path=file_path,
                    project_path=project_path,
                    operation="read",
                    intent_kind="existing_file",
                    source=f"{tool_name}:file_path",
                    evidence=[need.question],
                )
                if not resolved_file_path:
                    return None
                file_path = resolved_file_path
            return ToolInputMetadata.from_mapping(
                tool_name,
                {
                    "task_description": task_description,
                    "language": attrs.get("language", "python"),
                    "file_path": file_path,
                    "operation_kind": need.operation_kind or attrs.get("operation_kind") or "modify_symbol",
                    "target_scope": need.target_scope or attrs.get("target_scope") or "symbol",
                    "symbol_name": need.symbol_name or attrs.get("symbol_name"),
                    "symbol_type": need.symbol_type or attrs.get("symbol_type"),
                    "patch_mode": need.patch_mode or attrs.get("patch_mode"),
                    **attrs,
                },
            )
        if tool_name == "code_executor":
            code = attrs.get("code")
            if not code:
                return None
            return ToolInputMetadata.from_mapping(
                tool_name,
                {
                    "code": code,
                    "language": attrs.get("language", "python"),
                    **attrs,
                },
            )
        if tool_name == "readme_tool":
            readme_project = need.target_path or attrs.get("project_path")
            if not readme_project:
                return None
            readme_project = self._readme_project_path(readme_project)
            if project_path:
                readme_project = self._resolve_single_path(
                    state,
                    raw_path=readme_project,
                    project_path=project_path,
                    operation="read",
                    intent_kind="existing_directory",
                    source=f"{tool_name}:project_path",
                    evidence=[need.question],
                )
                if not readme_project:
                    return None
            payload = dict(attrs)
            payload["project_path"] = readme_project
            return ToolInputMetadata.from_mapping(tool_name, payload)
        return None

    def _project_root_from_attrs(self, attrs: dict[str, Any]) -> str:
        raw_project = attrs.get("project_path") or attrs.get("cwd") or ""
        if not raw_project:
            return ""
        return str(resolve_project_path(raw_project))

    def _resolve_single_path(
        self,
        state: RuntimeStateMetadata,
        *,
        raw_path: Any,
        project_path: str,
        operation: str,
        intent_kind: str,
        source: str,
        evidence: list[str] | None = None,
    ) -> str | None:
        if not raw_path:
            return None
        if not project_path:
            return str(Path(str(raw_path)).expanduser())
        resolver = ProjectPathResolver(project_path)
        intent = PathIntentMetadata(
            project_root=project_path,
            raw_path=str(raw_path),
            intent_kind=intent_kind,
            operation=operation,
            source=source,
            evidence=list(evidence or []),
        )
        state.record_path_intent(intent)
        resolution = resolver.resolve(intent)
        state.record_path_resolution(resolution)
        if resolution.status in {"blocked", "ambiguous"}:
            state.add_unknown(resolution.reason or f"Could not resolve path for {source}")
            return None
        return resolution.resolved_path

    def _resolve_many_paths(
        self,
        state: RuntimeStateMetadata,
        *,
        raw_paths: list[str],
        project_path: str,
        operation: str,
        intent_kind: str,
        source: str,
        evidence: list[str] | None = None,
    ) -> list[str]:
        resolved: list[str] = []
        for raw_path in raw_paths:
            grounded = self._resolve_single_path(
                state,
                raw_path=raw_path,
                project_path=project_path,
                operation=operation,
                intent_kind=intent_kind,
                source=source,
                evidence=evidence,
            )
            if grounded:
                resolved.append(grounded)
        return list(dict.fromkeys(resolved))

    def _resolve_command_text(
        self,
        state: RuntimeStateMetadata,
        *,
        command: str,
        project_path: str,
        source: str,
        evidence: list[str] | None = None,
    ) -> str | None:
        grounded_command, intents, resolutions = ground_command_paths_within_project(
            command,
            project_path,
            source=source,
            evidence=evidence,
        )
        for intent in intents:
            state.record_path_intent(intent)
        for resolution in resolutions:
            state.record_path_resolution(resolution)
        blocking = next((item for item in resolutions if item.status in {"blocked", "ambiguous"}), None)
        if blocking is not None:
            state.add_unknown(blocking.reason or f"Could not resolve command path for {source}")
            return None
        return grounded_command

    def _readme_project_path(self, project_path: Any) -> str:
        path = Path(str(project_path)).expanduser()
        if path.name.lower().startswith("readme") and path.suffix:
            return str(path.parent)
        return str(path)

    def _file_writer_operation_kind(self, file_path: Any, operation_kind: Any, overwrite: Any) -> str | None:
        operation = str(operation_kind).lower() if operation_kind else None
        if overwrite is False:
            return operation
        if (operation is None or operation in {"create_file", "file_create", "directory_generate"}) and Path(str(file_path)).expanduser().exists():
            return "file_replace"
        return operation or "create_file"

    def _requires_confirmation(self, tool_name: str, need: DecisionNeedMetadata) -> bool:
        return self.guard.requires_confirmation(tool_name, need, self.registry)

    def _risk_value(self, risk_level: str | None) -> int:
        return RISK_ORDER.get(str(risk_level or "medium").lower(), 1)

    def _looks_like_directory_need(self, need: DecisionNeedMetadata) -> bool:
        target_path = need.target_path or need.attributes.get("file_path") or need.attributes.get("directory_path")
        if target_path and self._path_is_existing_directory(target_path):
            return True
        question = f"{need.question} {need.decision_to_unlock or ''}".lower()
        directory_tokens = (
            "files and directories",
            "directories exist",
            "what files exist",
            "list directory",
            "directory listing",
            "project folder",
            "project structure",
            "folder contents",
        )
        return any(token in question for token in directory_tokens)

    def _looks_like_project_root_read_need(self, need: DecisionNeedMetadata) -> bool:
        need_type = str(need.need_type or "").lower().replace("-", "_")
        if need_type in {"project_structure", "directory_read", "read_directory", "multi_file_read"}:
            return True
        text = f"{need.question} {need.target_path or ''}".lower()
        return "project" in text and any(term in text for term in ("structure", "directory", "root", "files"))

    def _should_use_directory_sketch(self, need: DecisionNeedMetadata, payload: dict[str, Any]) -> bool:
        if payload.get("file_paths"):
            return False
        need_type = str(need.need_type or "").lower().replace("-", "_")
        if need_type in {"project_structure", "directory_read", "read_directory", "multi_file_read"}:
            return True
        question = f"{need.question} {need.decision_to_unlock or ''}".lower()
        return any(
            token in question
            for token in (
                "project structure",
                "files and directories",
                "directories exist",
                "what files exist",
                "directory listing",
            )
        )

    def _path_is_existing_directory(self, path_value: Any) -> bool:
        try:
            return Path(str(path_value)).expanduser().is_dir()
        except OSError:
            return False

    def _looks_like_non_executable_file_need(self, need: DecisionNeedMetadata) -> bool:
        language = str(need.attributes.get("language") or "").lower()
        if language and language not in {"bash", "python", "shell"}:
            return True
        target_path = need.target_path or need.attributes.get("file_path")
        return bool(target_path and Path(str(target_path)).suffix.lower() in NON_EXECUTABLE_FILE_SUFFIXES)

    def _decision_reason(self, tool_name: str, need: DecisionNeedMetadata) -> str:
        unlock = f" to unlock {need.decision_to_unlock}" if need.decision_to_unlock else ""
        return f"{tool_name} can answer '{need.question}'{unlock} during {need.phase.value}."

    def _alternatives_for_need(self, need: DecisionNeedMetadata) -> list[str]:
        need_type = need.need_type.lower().replace("-", "_")
        if need_type in {"file_read", "read_file", "inspect_file"}:
            return ["multi_file_reader"]
        if need_type in {"project_structure", "directory_read", "read_directory", "multi_file_read"}:
            return ["file_reader"]
        if need_type in {"command_check", "smoke_test", "test", "verify_command"}:
            return ["static inspection", "runtime verifier"]
        if need_type in {"file_write", "write_file"}:
            return ["file_patch_writer", "edit plan", "ask user"]
        if need_type in {"file_delete", "delete_file", "remove_file"}:
            return ["file_reader", "edit plan", "ask user"]
        if need_type in {"code_unit_generate", "generate_code_unit", "add_symbol"}:
            return ["code_generator"]
        if need_type in {"code_symbol_modify", "code_patch", "modify_symbol"}:
            return ["code_unit_generator", "code_generator"]
        return []


class FileSelector:
    """Promote evidence-backed candidate files into editable selected files."""

    def select(
        self,
        state: RuntimeStateMetadata,
        file_paths: list[str],
        evidence: dict[str, list[str]] | None = None,
    ) -> list[str]:
        evidence = evidence or {}
        selected: list[str] = []
        for file_path in file_paths:
            file_evidence = list(evidence.get(file_path) or state.candidate_files.get(file_path) or [])
            if not file_evidence:
                state.add_unknown(f"Missing file-selection evidence for {file_path}")
                continue
            for item in file_evidence:
                state.select_file(file_path, item)
            selected.append(file_path)
        return selected


class EditGuard:
    """Deterministically approve or reject edit plans before write operations."""

    def approve(self, state: RuntimeStateMetadata, edit_plan: EditPlanMetadata) -> GuardDecisionMetadata:
        missing_evidence = self._missing_evidence(edit_plan)
        target_count = len(set(edit_plan.target_files))
        budget_kind = str(edit_plan.attributes.get("budget_kind") or "file_edit")
        over_edit_budget = budget_kind != "file_create" and target_count + state.budget.file_edits_used > state.budget.max_file_edits
        over_create_budget = budget_kind == "file_create" and target_count + state.budget.file_creates_used > state.budget.max_file_creates
        unselected = [file_path for file_path in edit_plan.target_files if file_path not in state.selected_files]
        missing_verification = not edit_plan.verification
        high_risk_without_constraints = (
            RISK_ORDER.get(edit_plan.risk_level.lower(), 1) >= RISK_ORDER["high"]
            and not edit_plan.forbidden_changes
        )

        if missing_evidence:
            return GuardDecisionMetadata(
                approved=False,
                reason="Edit plan lacks evidence.",
                risk_level=edit_plan.risk_level,
                blocked_files=edit_plan.target_files,
                required_evidence=missing_evidence,
                required_verification=edit_plan.verification,
            )
        if over_edit_budget or over_create_budget:
            return GuardDecisionMetadata(
                approved=False,
                reason=(
                    "Edit plan exceeds the runtime file create budget."
                    if over_create_budget
                    else "Edit plan exceeds the runtime file edit budget."
                ),
                risk_level=edit_plan.risk_level,
                blocked_files=edit_plan.target_files,
                required_evidence=[],
                required_verification=edit_plan.verification,
            )
        if unselected:
            return GuardDecisionMetadata(
                approved=False,
                reason="Target files must be selected from evidence-backed candidates before editing.",
                risk_level=edit_plan.risk_level,
                blocked_files=unselected,
                required_evidence=[f"select_file:{file_path}" for file_path in unselected],
                required_verification=edit_plan.verification,
            )
        if missing_verification:
            return GuardDecisionMetadata(
                approved=False,
                reason="Edit plan must include verification before write tools can run.",
                risk_level=edit_plan.risk_level,
                blocked_files=edit_plan.target_files,
                required_evidence=[],
                required_verification=["Add a verification command, smoke check, or static check."],
            )
        if high_risk_without_constraints:
            return GuardDecisionMetadata(
                approved=False,
                reason="High-risk edit plans must state forbidden changes.",
                risk_level=edit_plan.risk_level,
                blocked_files=edit_plan.target_files,
                required_evidence=[],
                required_verification=edit_plan.verification,
            )

        return GuardDecisionMetadata(
            approved=True,
            reason="Edit plan is evidence-backed, scoped, and verifiable.",
            risk_level=edit_plan.risk_level,
            required_verification=edit_plan.verification,
        )

    def _missing_evidence(self, edit_plan: EditPlanMetadata) -> list[str]:
        missing: list[str] = []
        if not edit_plan.evidence:
            missing.append("At least one evidence item is required.")
        if not edit_plan.target_files:
            missing.append("At least one target file is required.")
        if not edit_plan.allowed_changes:
            missing.append("Allowed changes must be stated.")
        return missing


class StateUpdater:
    """Absorb tool results into explicit runtime state."""

    def __init__(
        self,
        guard: RuntimeGuard | None = None,
        *,
        state_event_sink: Callable[[RuntimeStateMetadata, str, str], None] | None = None,
    ) -> None:
        self.guard = guard or RuntimeGuard()
        self.state_event_sink = state_event_sink

    def apply_tool_result(
        self,
        state: RuntimeStateMetadata,
        selection: ToolSelection,
        execution_result: Any,
    ) -> RuntimeStateMetadata:
        previous_phase = _phase_value(state.phase)
        previous_verification_status = str(state.verification_status or "")
        progress_before = self._progress_signature(state)
        tool_name = selection.tool_name
        success = bool(getattr(execution_result, "success", False))
        input_params = selection.input_metadata.to_params()
        output_metadata = getattr(execution_result, "output_metadata", None)
        error = getattr(getattr(execution_result, "error", None), "error_message", None)
        file_create = tool_name == "file_writer" and str(input_params.get("operation_kind") or "").lower() in FILE_CREATE_OPERATIONS

        state.budget.consume_tool_call(
            file_read=tool_name in READ_TOOLS,
            file_edit=tool_name in WRITE_TOOLS and not file_create,
            file_create=file_create,
        )
        state.record_tool_event(
            {
                "tool_name": tool_name,
                "step_id": selection.step_id,
                "success": success,
                "phase": _phase_value(state.phase),
                "input": input_params,
                "error": error,
            }
        )

        was_verifying = _phase_is(state.phase, AgentPhase.VERIFY)
        if not success:
            state.add_unknown(error or f"{tool_name} failed")
            state.verification_status = "failed" if was_verifying else state.verification_status
            replan_reason = self.guard.should_replan(state)
            if replan_reason and state.budget.replan_rounds_used < state.budget.max_replan_rounds:
                state.request_replan(replan_reason)
            else:
                state.phase = AgentPhase.RECOVER
            self._emit_state_changes(state, previous_phase, previous_verification_status)
            return state

        matching_decisions = [decision for decision in state.decision_history if decision.selected_tool == tool_name]
        if matching_decisions:
            state.resolve_unknown(matching_decisions[-1].question)
        if tool_name in READ_TOOLS:
            self._absorb_file_read(state, selection, output_metadata)
        elif tool_name in WRITE_TOOLS:
            self._absorb_file_write(state, input_params, output_metadata)
        elif tool_name in EXECUTION_TOOLS:
            self._absorb_execution(state, selection, output_metadata, was_verifying)
        elif tool_name == "web_searcher":
            state.add_fact(f"Reference search completed for: {input_params.get('query', '')}".strip())

        self._update_progress_stop_condition(state, progress_before)
        self._emit_state_changes(state, previous_phase, previous_verification_status)
        return state

    def _emit_state_changes(
        self,
        state: RuntimeStateMetadata,
        previous_phase: str,
        previous_verification_status: str,
    ) -> None:
        if self.state_event_sink is None:
            return
        current_phase = _phase_value(state.phase)
        current_verification_status = str(state.verification_status or "")
        if current_phase != previous_phase:
            self.state_event_sink(state, "phase", previous_phase)
        if current_verification_status != previous_verification_status:
            self.state_event_sink(state, "verification", previous_verification_status)

    def next_phase(self, state: RuntimeStateMetadata) -> AgentPhase:
        if _phase_value(state.phase) in {AgentPhase.BLOCKED.value, AgentPhase.RECOVER.value, AgentPhase.SUMMARIZE.value}:
            return state.phase
        if state.modified_files and state.verification_status != "passed":
            return AgentPhase.VERIFY
        try:
            index = [phase.value for phase in PHASE_SEQUENCE].index(_phase_value(state.phase))
        except ValueError:
            return AgentPhase.BLOCKED
        return PHASE_SEQUENCE[min(index + 1, len(PHASE_SEQUENCE) - 1)]

    def _absorb_file_read(self, state: RuntimeStateMetadata, selection: ToolSelection, output_metadata: Any) -> None:
        params = selection.input_metadata.to_params()
        file_paths = list(params.get("file_paths") or [])
        if params.get("file_path"):
            file_paths.append(str(params["file_path"]))
        if params.get("directory_path"):
            state.add_fact(f"Inspected project directory: {params['directory_path']}")

        result = getattr(output_metadata, "result", None)
        files_from_result = getattr(result, "files", None) or []
        file_path_from_result = getattr(result, "file_path", None)
        if file_path_from_result:
            file_paths.append(str(file_path_from_result))
        file_paths.extend(str(item) for item in files_from_result)
        for file_path in dict.fromkeys(file_paths):
            state.add_candidate_file(file_path, f"{selection.tool_name} returned evidence for {file_path}")
        if file_paths:
            state.add_fact(f"Read {len(dict.fromkeys(file_paths))} file path(s) for evidence.")

    def _absorb_file_write(self, state: RuntimeStateMetadata, input_params: dict[str, Any], output_metadata: Any) -> None:
        result = getattr(output_metadata, "result", None)
        file_path = str(getattr(result, "file_path", "") or input_params.get("file_path") or "")
        state.add_modified_file(file_path)
        state.verification_status = "required"
        state.phase = AgentPhase.VERIFY
        state.add_fact(f"Modified file: {file_path}")

    def _absorb_execution(
        self,
        state: RuntimeStateMetadata,
        selection: ToolSelection,
        output_metadata: Any,
        was_verifying: bool,
    ) -> None:
        if was_verifying or _phase_is(state.phase, AgentPhase.VERIFY) or state.verification_status == "required":
            state.budget.consume_verification_attempt()
            state.verification_status = "passed"
            state.phase = AgentPhase.SUMMARIZE
            state.completion_reason = "verification passed"
        elif self._execution_changed_project(state, selection):
            state.verification_status = "required"
            state.phase = AgentPhase.VERIFY
            state.add_fact(f"Project state changed via {selection.tool_name}; verification required.")
        else:
            state.add_fact(f"Executed command via {getattr(output_metadata, 'tool_name', 'tool')}.")

    def _execution_changed_project(self, state: RuntimeStateMetadata, selection: ToolSelection) -> bool:
        if selection.tool_name != "command_executor":
            return False
        target_files = set(selection.input_metadata.to_params().get("file_paths") or [])
        if not target_files:
            target_files = set(selection.input_metadata.to_params().get("files") or [])
        if not target_files:
            command_cwd = selection.input_metadata.to_params().get("cwd")
            target_files = {str(command_cwd or ".")}
        for edit_plan in state.planned_edits:
            if set(edit_plan.target_files).intersection({str(item) for item in target_files}):
                return True
        return False

    def _progress_signature(self, state: RuntimeStateMetadata) -> tuple[int, int, int, int, int]:
        return (
            len(state.known_facts),
            len(state.unknowns),
            len(state.resolved_questions),
            len(state.candidate_files),
            len(state.modified_files),
        )

    def _update_progress_stop_condition(self, state: RuntimeStateMetadata, before: tuple[int, int, int, int, int]) -> None:
        after = self._progress_signature(state)
        if after != before:
            state.no_progress_rounds = 0
            return
        state.no_progress_rounds += 1
        if state.no_progress_rounds >= 3:
            state.block("no new runtime facts after repeated tool results")


class RuntimeVerifier:
    """Select the smallest verification plan after a write operation."""

    def plan(self, state: RuntimeStateMetadata, context: dict[str, Any] | None = None) -> VerificationPlanMetadata:
        context = context or {}
        timeout = None
        command = context.get("test_command")
        if not command:
            python_target = self._python_entry_file(state)
            if python_target:
                python_command = str(context.get("python_command") or "python")
                command = f"{shlex.quote(python_command)} {shlex.quote(python_target)} --help"
                timeout = 5
        command = command or context.get("run_command") or self._pytest_command(context) or "python -m compileall ."
        return VerificationPlanMetadata(
            reason="Write operation requires verification.",
            commands=[command],
            target_files=list(state.modified_files),
            fallback_checks=["static check"] if command != "python -m compileall ." else [],
            attributes={"timeout": timeout} if timeout else {},
        )

    def _pytest_command(self, context: dict[str, Any]) -> str | None:
        project_path = str(context.get("project_path") or context.get("cwd") or "")
        if project_path:
            return "pytest"
        return None

    def _python_entry_file(self, state: RuntimeStateMetadata) -> str | None:
        for file_path in reversed(state.modified_files):
            if str(file_path).endswith(".py"):
                return str(file_path)
        return None


class RuntimeReporter:
    """Build the single auditable report from runtime state."""

    def report(self, state: RuntimeStateMetadata) -> RuntimeReportMetadata:
        residual_risks: list[str] = []
        if state.unknowns:
            residual_risks.append("unresolved runtime questions remain")
        if state.verification_status not in {"passed", "not_required"}:
            residual_risks.append(f"verification status is {state.verification_status}")
        if _phase_value(state.phase) in {AgentPhase.RECOVER.value, AgentPhase.BLOCKED.value}:
            residual_risks.append(f"runtime stopped in {_phase_value(state.phase)}")
        return RuntimeReportMetadata(
            goal=state.goal,
            phase=state.phase,
            completion_reason=state.completion_reason,
            known_facts=list(state.known_facts),
            unresolved_questions=list(state.unknowns),
            path_resolutions=list(state.path_resolutions),
            selected_files=dict(state.selected_files),
            modified_files=list(state.modified_files),
            planned_edits=list(state.planned_edits),
            verification_status=state.verification_status,
            risk_level=state.risk_level,
            tool_decisions=list(state.decision_history),
            tool_history=list(state.tool_history),
            residual_risks=residual_risks,
        )


class _RuntimeSessionExecutor:
    """Run the runtime session mechanics owned by AgentRuntimeController."""

    def __init__(self, runtime: Any) -> None:
        self.runtime = runtime

    def run(self, goal: str, context: dict[str, Any], mode: str = "standard") -> dict[str, Any]:
        """Run the full execution shell."""
        self._log(
            "session_started",
            input_summary={"goal": goal, "mode": mode},
            success=None,
        )
        if mode == "enhanced_ui":
            return self._run_enhanced_ui(goal, context)
        if mode == "standard":
            return self._run_standard(goal, context)
        raise ValueError(f"Unsupported autopilot session mode: {mode}")

    def _run_enhanced_ui(self, goal: str, context: dict[str, Any]) -> dict[str, Any]:
        runtime = self.runtime
        runtime.tracker.start_tracking()
        stages = [
            "Semantic Analysis",
            "Memory Retrieval",
            "Task Decomposition",
            "Execution",
            "Evaluation",
            "Iteration 1",
            "Iteration 2",
            "Result Assembly",
        ]
        stage_statuses = {stage: "pending" for stage in stages}
        runtime.enhanced_ui.set_task_graph_state(
            goal=goal,
            stages=stages,
            stage_statuses=stage_statuses,
            current_stage="Semantic Analysis",
            tasks=[],
        )
        runtime.enhanced_ui.set_current_task_state(
            title="Semantic Analysis",
            details=f"Goal: {goal[:120]}",
            status="running",
        )

        try:
            stage_statuses["Semantic Analysis"] = "running"
            runtime.enhanced_ui.set_task_graph_state(
                stage_statuses=stage_statuses,
                current_stage="Semantic Analysis",
            )
            with runtime.tracker.track_task("Semantic Analysis", {"goal": goal}):
                semantic = self._analyze_goal(goal, task_id=str(context.get("task_id") or ""))

            stage_statuses["Semantic Analysis"] = "completed"
            runtime.enhanced_ui.set_task_graph_state(stage_statuses=stage_statuses)
            runtime.enhanced_ui.log_activity("success", f"Analysis complete: {semantic.task_type.value}")
            runtime.enhanced_ui.set_current_task_state(
                title="Semantic Analysis",
                details=(
                    f"Task Type: {semantic.task_type.value}\n"
                    f"Risk Level: {semantic.risk_level.value}\n"
                    f"Required Resources: {len(semantic.required_resources)}"
                ),
                status="completed",
            )
            time.sleep(1.5)

            stage_statuses["Memory Retrieval"] = "running"
            runtime.enhanced_ui.set_task_graph_state(
                stage_statuses=stage_statuses,
                current_stage="Memory Retrieval",
            )
            runtime.enhanced_ui.set_current_task_state(
                title="Memory Retrieval",
                details="Searching for relevant past experiences",
                status="running",
            )
            with runtime.tracker.track_task("Memory Retrieval", {"query": goal}):
                memories = runtime.memory_store.query(goal, limit=5)

            stage_statuses["Memory Retrieval"] = "completed"
            runtime.enhanced_ui.set_task_graph_state(stage_statuses=stage_statuses)
            if memories.memories:
                runtime.enhanced_ui.log_activity("success", f"Found {len(memories.memories)} relevant memories")
                memory_info = f"Found {len(memories.memories)} relevant memories:\n\n"
                for i, mem in enumerate(memories.memories[:3], 1):
                    memory_info += f"{i}. [{mem.memory_type.value}] {mem.content[:60]}...\n"
                runtime.enhanced_ui.set_current_task_state(
                    title="Memory Retrieval",
                    details=memory_info,
                    status="completed",
                )
                time.sleep(1.5)
            else:
                runtime.enhanced_ui.log_activity("info", "No relevant memories found")
                runtime.enhanced_ui.set_current_task_state(
                    title="Memory Retrieval",
                    details="No relevant memories found",
                    status="completed",
                )

            self._enrich_context(context, goal, semantic, memories)
            fast_result = runtime._try_simple_code_artifact_fast_path(goal, semantic)
            if fast_result is not None:
                self._log("session_fast_path_completed", output_summary={"mode": "enhanced_ui"}, success=True)
                return fast_result

            stage_statuses["Task Decomposition"] = "running"
            runtime.enhanced_ui.set_task_graph_state(
                stage_statuses=stage_statuses,
                current_stage="Task Decomposition",
            )
            runtime.enhanced_ui.set_current_task_state(
                title="Task Decomposition",
                details="Breaking down task into executable subtasks",
                status="running",
            )
            with runtime.tracker.track_task("Task Decomposition", {"goal": goal}):
                decomposition = runtime.task_decomposer.decompose(
                    task_description=goal,
                    context=context,
                )

            stage_statuses["Task Decomposition"] = "completed"
            runtime.enhanced_ui.set_task_graph_state(
                stage_statuses=stage_statuses,
                tasks=runtime._dashboard_task_items(decomposition.subtasks),
            )
            runtime.enhanced_ui.log_activity("success", f"Created {len(decomposition.subtasks)} subtasks")

            breakdown_info = f"Created {len(decomposition.subtasks)} subtasks:\n\n"
            for i, subtask in enumerate(decomposition.subtasks[:5], 1):
                breakdown_info += f"{i}. {subtask.description[:70]}...\n"
            if len(decomposition.subtasks) > 5:
                breakdown_info += f"\n... and {len(decomposition.subtasks) - 5} more tasks"
            runtime.enhanced_ui.set_current_task_state(
                title="Task Decomposition",
                details=breakdown_info,
                status="completed",
            )
            time.sleep(2.0)
            time.sleep(3.0)

            stage_statuses["Execution"] = "running"
            runtime.enhanced_ui.set_task_graph_state(
                stage_statuses=stage_statuses,
                current_stage="Execution",
                tasks=runtime._dashboard_task_items(decomposition.subtasks),
            )
            runtime.enhanced_ui.set_current_task_state(
                title="Execution",
                details=f"Running {len(decomposition.subtasks)} tasks",
                status="running",
            )

            results = runtime._execute_tasks(decomposition.subtasks, goal)
            all_tasks_completed = all(t.status == TaskStatus.COMPLETED for t in decomposition.subtasks)
            stage_statuses["Execution"] = "completed" if all_tasks_completed else "failed"
            runtime.enhanced_ui.set_task_graph_state(
                stage_statuses=stage_statuses,
                tasks=runtime._dashboard_task_items(decomposition.subtasks),
            )
            readme_result, written_files, project_path, improvement_result = self._finalize_project_outputs(
                goal,
                results,
                all_tasks_completed,
            )

            success, iteration_error_msg = self._update_stats(decomposition, improvement_result)
            execution_failure = self._execution_failure_context(decomposition.subtasks)
            if all_tasks_completed:
                stage_statuses["Result Assembly"] = "running"
                runtime.enhanced_ui.set_task_graph_state(
                    stage_statuses=stage_statuses,
                    current_stage="Result Assembly",
                )
                runtime.enhanced_ui.set_current_task_state(
                    title="Result Assembly",
                    details="Assembling final result",
                    status="running",
                )
                with runtime.tracker.track_task("Result Assembly", {}):
                    runtime.task_decomposer.assemble_results(
                        decomposition.original_task,
                        decomposition.subtasks,
                    )
                stage_statuses["Result Assembly"] = "completed"
                runtime.enhanced_ui.set_task_graph_state(stage_statuses=stage_statuses)
            else:
                stage_statuses["Result Assembly"] = "failed"
                runtime.enhanced_ui.set_task_graph_state(stage_statuses=stage_statuses)
            runtime._stop_tracking_if_owned()
            self._set_enhanced_completion_state(success, readme_result, improvement_result, iteration_error_msg, execution_failure)

            result = self._build_result(
                goal=goal,
                semantic=semantic,
                decomposition=decomposition,
                results=results,
                readme_result=readme_result,
                improvement_result=improvement_result,
                iteration_error_msg=iteration_error_msg,
                success=success,
                include_final_result=False,
                execution_failure=execution_failure,
            )
            self._log(
                "session_completed",
                output_summary={"mode": "enhanced_ui", "success": success, "project_path": str(project_path) if project_path else None},
                success=success,
            )
            return result

        except Exception as exc:
            runtime.tracker.stop_tracking()
            runtime.enhanced_ui.set_current_task_state(
                title="Error",
                details=f"Execution failed: {str(exc)}",
                status="failed",
            )
            self._log("session_failed", success=False, error=str(exc))
            raise

    def _run_standard(self, goal: str, context: dict[str, Any]) -> dict[str, Any]:
        runtime = self.runtime
        try:
            runtime._show_start_panel(goal)

            runtime.console.print("[bold cyan]🧠 Analyzing goal...[/bold cyan]")
            semantic = self._analyze_goal(goal, task_id=str(context.get("task_id") or ""))
            runtime.console.print(f"  • Task type: [cyan]{semantic.task_type.value}[/cyan]")
            runtime.console.print(
                f"  • Risk level: [{'red' if semantic.risk_level.value == 'high' else 'yellow' if semantic.risk_level.value == 'medium' else 'green'}]{semantic.risk_level.value}[/]"
            )
            runtime.console.print(f"  • Confidence: {semantic.confidence:.2f}")
            runtime.console.print()

            runtime.console.print("[bold cyan]🧠 Retrieving memories...[/bold cyan]")
            memories = runtime.memory_store.query(goal, limit=5)
            if memories.memories:
                runtime.console.print(f"  • Found {len(memories.memories)} relevant memories")
                for mem in memories.memories[:3]:
                    runtime.console.print(f"    - [{mem.memory_type.value}] {mem.content[:60]}...")
            else:
                runtime.console.print("  • No relevant memories found")
            runtime.console.print()

            self._enrich_context(context, goal, semantic, memories)
            fast_result = runtime._try_simple_code_artifact_fast_path(goal, semantic)
            if fast_result is not None:
                self._log("session_fast_path_completed", output_summary={"mode": "standard"}, success=True)
                return fast_result

            runtime.console.print("[bold cyan]🔍 Decomposing task...[/bold cyan]")
            decomposition = runtime.task_decomposer.decompose(
                task_description=goal,
                context=context,
            )

            runtime.console.print(f"  • Original task: {decomposition.original_task.description}")
            runtime.console.print(f"  • Subtasks: {len(decomposition.subtasks)}")
            runtime.console.print(f"  • Estimated effort: {decomposition.estimated_total_effort:.1f} units")
            runtime.console.print()
            runtime._show_task_tree(decomposition)

            runtime.logger.log_event(
                "task_decomposition",
                {
                    "goal": goal,
                    "original_task_id": decomposition.original_task.id,
                    "subtask_count": len(decomposition.subtasks),
                    "estimated_effort": decomposition.estimated_total_effort,
                    "rationale": decomposition.decomposition_rationale,
                },
                session_id=runtime.session_id,
                turn_id=1,
            )

            runtime.console.print("[bold cyan]⚡ Executing tasks...[/bold cyan]")
            results = runtime._execute_tasks(decomposition.subtasks, goal)
            all_tasks_completed = all(t.status == TaskStatus.COMPLETED for t in decomposition.subtasks)
            readme_result, written_files, project_path, improvement_result = self._finalize_project_outputs(
                goal,
                results,
                all_tasks_completed,
            )

            final_result = None
            execution_failure = self._execution_failure_context(decomposition.subtasks)
            if all_tasks_completed:
                runtime.console.print()
                runtime.console.print("[bold cyan]📦 Assembling results...[/bold cyan]")
                final_result = runtime.task_decomposer.assemble_results(
                    decomposition.original_task,
                    decomposition.subtasks,
                )

            success, iteration_error_msg = self._update_stats(decomposition, improvement_result)
            runtime._show_completion_summary(decomposition, results)
            if iteration_error_msg:
                runtime.console.print(f"[yellow]Autonomous iteration warning:[/yellow] {iteration_error_msg}")

            result = self._build_result(
                goal=goal,
                semantic=semantic,
                decomposition=decomposition,
                results=results,
                readme_result=readme_result,
                improvement_result=improvement_result,
                iteration_error_msg=iteration_error_msg,
                success=success,
                include_final_result=True,
                final_result=final_result,
                execution_failure=execution_failure,
            )
            self._log(
                "session_completed",
                output_summary={"mode": "standard", "success": success, "project_path": str(project_path) if project_path else None},
                success=success,
            )
            return result

        except Exception as exc:
            runtime.console.print(f"\n[bold red]❌ Execution failed: {exc}[/bold red]")
            runtime.stats["success"] = False
            runtime.stats["end_time"] = datetime.now()
            runtime.logger.log_event(
                "autopilot_failed",
                {
                    "goal": goal,
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                },
                session_id=runtime.session_id or "unknown",
                turn_id=1,
            )
            self._log("session_failed", success=False, error=str(exc))
            raise

    def _analyze_goal(self, goal: str, *, task_id: str = "") -> Any:
        runtime = self.runtime
        analyzer = runtime.semantic_analyzer
        try:
            semantic = analyzer.analyze_goal(goal)
            hooks = getattr(runtime, "runtime_diagnostics_hooks", None)
            if hooks:
                task_card = TaskCard(
                    goal=goal,
                    task_type=semantic.task_type,
                    risk_level=semantic.risk_level,
                    required_resources=list(semantic.required_resources),
                    expected_deliverables=list(semantic.expected_deliverables),
                    constraints=[],
                    context={},
                )
                resolved_task_id = str(task_id or getattr(runtime, "session_id", "") or "unknown")
                session_id = str(getattr(runtime, "session_id", "") or resolved_task_id)
                hooks.on_task_card_ready(
                    task_id=resolved_task_id,
                    task_card=task_card,
                    session_id=session_id,
                )
            return semantic
        except (InvalidLLMResponseError, LLMProviderError, LLMTimeoutError) as exc:
            fallback = getattr(analyzer, "fallback_goal_analysis", None)
            if not callable(fallback):
                raise
            semantic = fallback(goal, type(exc).__name__)
            self._log(
                "semantic_analysis_fallback",
                success=True,
                input_summary={"goal": goal, "reason": str(exc)},
                output_summary={"task_type": semantic.task_type.value},
                level="WARNING",
            )
            if runtime.enhanced_ui:
                runtime.enhanced_ui.log_activity(
                    "warning",
                    f"Semantic analysis fallback: {type(exc).__name__}",
                )
            return semantic

    def _enrich_context(self, context: dict[str, Any], goal: str, semantic: Any, memories: Any) -> None:
        context["semantic_analysis"] = semantic.model_dump()
        context["memories"] = [m.model_dump() for m in memories.memories]
        context["goal"] = goal

    def _finalize_project_outputs(
        self,
        goal: str,
        results: list[Any],
        all_tasks_completed: bool,
    ) -> tuple[Any, list[str], Any, dict[str, Any] | None]:
        runtime = self.runtime
        readme_result = runtime._finalize_project_readme(goal, results) if all_tasks_completed else None
        written_files = runtime._collect_written_files(results)
        project_path = runtime._infer_project_path_from_files(goal, written_files) if written_files else None
        can_iterate = bool(all_tasks_completed and project_path and written_files)
        self._log(
            "project_iteration_decision",
            input_summary={
                "all_tasks_completed": all_tasks_completed,
                "written_files": written_files,
                "project_path": str(project_path) if project_path else None,
                "enable_iterative_improvement": getattr(runtime, "enable_iterative_improvement", None),
                "required_successful_improvements": getattr(runtime, "required_successful_improvements", None),
            },
            output_summary={"will_attempt_iteration": can_iterate},
        )
        if can_iterate:
            improvement_result = runtime._run_iterative_improvement(
                goal=goal,
                project_path=project_path,
                written_files=written_files,
                readme_path=(
                    readme_result.output.get("file_path")
                    if readme_result and getattr(readme_result, "output", None) is not None
                    else None
                ),
            )
            if improvement_result is None:
                self._append_iteration_skip_note("Project improvement skipped: disabled or 0 iterations selected")
        else:
            improvement_result = None
            self._append_iteration_skip_note(self._iteration_skip_reason(all_tasks_completed, written_files, project_path))
        return readme_result, written_files, project_path, improvement_result

    def _iteration_skip_reason(
        self,
        all_tasks_completed: bool,
        written_files: list[str],
        project_path: Any,
    ) -> str:
        if not all_tasks_completed:
            return "Project improvement skipped: task execution did not complete successfully"
        if not written_files:
            return "Project improvement skipped: no written files detected"
        if not project_path:
            return "Project improvement skipped: project path could not be inferred"
        return "Project improvement skipped"

    def _append_iteration_skip_note(self, reason: str) -> None:
        runtime = self.runtime
        enhanced_ui = getattr(runtime, "enhanced_ui", None)
        if not enhanced_ui or not hasattr(enhanced_ui, "task_graph_state"):
            return
        tasks = list(enhanced_ui.task_graph_state.get("tasks") or [])
        note_id = "project_improvement_skipped"
        if any(task.get("id") == note_id for task in tasks if isinstance(task, dict)):
            return
        tasks.append(
            {
                "id": note_id,
                "description": reason,
                "status": "completed",
                "kind": "note",
            }
        )
        enhanced_ui.set_task_graph_state(tasks=tasks, current_task_id=None)
        if hasattr(enhanced_ui, "log_activity"):
            enhanced_ui.log_activity("info", reason)

    def _update_stats(self, decomposition: Any, improvement_result: dict[str, Any] | None) -> tuple[bool, str | None]:
        runtime = self.runtime
        success = all(t.status == TaskStatus.COMPLETED for t in decomposition.subtasks)
        iteration_error_msg = None
        if improvement_result is not None and not improvement_result.get("success", False):
            iteration_error_msg = runtime._format_iteration_failure(improvement_result)
            success = False
        runtime.stats["success"] = success
        runtime.stats["tasks_completed"] = len([t for t in decomposition.subtasks if t.status == TaskStatus.COMPLETED])
        runtime.stats["tasks_failed"] = len([t for t in decomposition.subtasks if t.status == TaskStatus.FAILED])
        runtime.stats["end_time"] = datetime.now()
        return success, iteration_error_msg

    def _set_enhanced_completion_state(
        self,
        success: bool,
        readme_result: Any,
        improvement_result: dict[str, Any] | None,
        iteration_error_msg: str | None,
        execution_failure: dict[str, Any] | None = None,
    ) -> None:
        runtime = self.runtime
        if success:
            success_details = f"Goal completed successfully!\n\nCompleted {runtime.stats['tasks_completed']} tasks"
            if readme_result:
                if readme_result.success and readme_result.output is not None:
                    success_details += f"\nREADME: {readme_result.output.get('file_path')}"
                elif readme_result.error_message:
                    success_details += f"\nREADME generation failed: {readme_result.error_message}"
            if improvement_result and improvement_result.get("validation"):
                success_details += (
                    f"\nImprovements applied: {improvement_result.get('completed_improvements', 0)}/"
                    f"{improvement_result.get('required_improvements', runtime.required_successful_improvements)}"
                )
                if iteration_error_msg:
                    success_details += f"\nIteration warning: {iteration_error_msg}"
            runtime.enhanced_ui.set_current_task_state(
                title="Success",
                details=success_details,
                status="completed",
            )
        else:
            failure_details = (
                f"Goal execution failed\n\nCompleted: {runtime.stats['tasks_completed']}, "
                f"Failed: {runtime.stats['tasks_failed']}"
            )
            if iteration_error_msg:
                failure_details = (
                    f"Iteration warning: {iteration_error_msg}\n"
                    f"Completed: {runtime.stats['tasks_completed']}, Failed: {runtime.stats['tasks_failed']}"
                )
            elif execution_failure:
                lines = [
                    execution_failure.get("failure_reason") or "Goal execution failed",
                    "",
                ]
                if execution_failure.get("task_description"):
                    lines.append(f"Task: {execution_failure['task_description']}")
                if execution_failure.get("task_id"):
                    lines.append(f"Task ID: {execution_failure['task_id']}")
                lines.extend(
                    [
                        f"Stage: {execution_failure.get('failure_stage') or 'unknown'}",
                        f"Tool: {execution_failure.get('failed_tool') or 'unknown'}",
                    ]
                )
                if execution_failure.get("failed_call_id"):
                    lines.append(f"Call: {execution_failure['failed_call_id']}")
                if execution_failure.get("failed_step_id"):
                    lines.append(f"Step: {execution_failure['failed_step_id']}")
                if execution_failure.get("file_path"):
                    lines.append(f"File: {execution_failure['file_path']}")
                if execution_failure.get("error_type"):
                    lines.append(f"Error Type: {execution_failure['error_type']}")
                if execution_failure.get("suggested_recovery"):
                    lines.append(f"Recovery: {execution_failure['suggested_recovery']}")
                if execution_failure.get("response_preview"):
                    lines.append(f"Response Preview: {str(execution_failure['response_preview'])[:1000]}")
                failure_details = "\n".join(lines)
            runtime.enhanced_ui.set_current_task_state(
                title="Failed",
                details=failure_details,
                status="failed",
            )

    def _execution_failure_context(self, subtasks: list[Any]) -> dict[str, Any] | None:
        failed_tasks = [
            task
            for task in subtasks
            if getattr(task, "status", None) in {TaskStatus.FAILED, TaskStatus.BLOCKED}
        ]
        if not failed_tasks:
            return None
        task = failed_tasks[0]
        task_result_metadata = getattr(task, "result_metadata", None) or getattr(task, "result", None)
        failure = getattr(task_result_metadata, "failure", None)
        details = getattr(failure, "details", {}) or {}
        tool_loop = details.get("tool_loop") if isinstance(details, dict) else None
        final_error = tool_loop.get("final_error") if isinstance(tool_loop, dict) else None
        final_details = final_error.get("details") if isinstance(final_error, dict) and isinstance(final_error.get("details"), dict) else {}
        input_summary = details.get("input_summary") if isinstance(details, dict) and isinstance(details.get("input_summary"), dict) else {}
        final_input = final_details.get("input_summary") if isinstance(final_details.get("input_summary"), dict) else {}
        tool_name = None
        call_id = None
        step_id = None
        if isinstance(details, dict):
            tool_name = details.get("tool_name") or details.get("failed_tool")
            call_id = details.get("call_id")
            step_id = details.get("step_id")
        if isinstance(final_error, dict):
            tool_name = tool_name or final_details.get("tool_name")
            call_id = call_id or final_details.get("call_id")
            step_id = step_id or final_details.get("step_id")
        if not tool_name and isinstance(tool_loop, dict):
            events = tool_loop.get("events") or []
            for event in reversed(events):
                if isinstance(event, dict) and event.get("event_type") == "error":
                    tool_name = event.get("tool_name")
                    call_id = event.get("call_id")
                    step_id = event.get("step_id")
                    break
        error_type = None
        response_preview = None
        suggested_recovery = None
        file_path = None
        if isinstance(details, dict):
            error_type = (
                details.get("error_type")
                or details.get("failure_error_type")
                or final_details.get("error_type")
                or (final_error.get("error_type") if isinstance(final_error, dict) else None)
            )
            suggested_recovery = (
                details.get("suggested_recovery")
                or final_details.get("suggested_recovery")
                or details.get("recovery_strategy")
                or final_details.get("recovery_strategy")
            )
            response_preview = (
                details.get("response_preview")
                or details.get("response_preview_start")
                or final_details.get("response_preview")
                or final_details.get("response_preview_start")
                or details.get("response_text")
                or final_details.get("response_text")
            )
            file_path = (
                details.get("file_path")
                or final_details.get("file_path")
                or input_summary.get("file_path")
                or final_input.get("file_path")
                or final_details.get("received_path")
            )
        return {
            "task_id": getattr(task, "id", None),
            "task_description": getattr(task, "description", None),
            "failure_stage": (details.get("failure_stage") if isinstance(details, dict) else None) or "Task Executor",
            "failed_tool": tool_name or "tool_event_loop",
            "failed_call_id": call_id,
            "failed_step_id": step_id,
            "failure_reason": getattr(failure, "error_message", None) or getattr(task, "error", None),
            "file_path": file_path,
            "error_type": error_type,
            "suggested_recovery": suggested_recovery,
            "response_preview": response_preview,
        }

    def _build_result(
        self,
        *,
        goal: str,
        semantic: Any,
        decomposition: Any,
        results: list[Any],
        readme_result: Any,
        improvement_result: dict[str, Any] | None,
        iteration_error_msg: str | None,
        success: bool,
        include_final_result: bool,
        final_result: Any | None = None,
        execution_failure: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        runtime = self.runtime
        result = {
            "success": success,
            "goal": goal,
            "semantic_analysis": semantic,
            "decomposition": decomposition,
            "results": results,
            "readme": readme_result,
            "validation": improvement_result.get("validation") if improvement_result else None,
            "evaluation": improvement_result.get("evaluation") if improvement_result else None,
            "completed_improvements": improvement_result.get("completed_improvements", 0) if improvement_result else 0,
            "required_improvements": improvement_result.get("required_improvements", runtime.required_successful_improvements) if improvement_result else runtime.required_successful_improvements,
            "completed_iterations": improvement_result.get("completed_iterations", 0) if improvement_result else 0,
            "required_iterations": improvement_result.get("required_iterations", runtime.required_successful_improvements) if improvement_result else runtime.required_successful_improvements,
            "improvement_report": improvement_result.get("improvement_report", {}) if improvement_result else {},
            "iterations": improvement_result.get("iterations", []) if improvement_result else [],
            "partial_success": improvement_result.get("partial_success", False) if improvement_result else False,
            "iteration_error": iteration_error_msg,
            "failure_stage": (
                improvement_result.get("failure_stage")
                if improvement_result
                else (execution_failure or {}).get("failure_stage")
            ),
            "failed_iteration": improvement_result.get("failed_iteration") if improvement_result else None,
            "failed_tool": (
                improvement_result.get("failed_tool")
                if improvement_result
                else (execution_failure or {}).get("failed_tool")
            ),
            "failed_call_id": (execution_failure or {}).get("failed_call_id"),
            "failed_step_id": (execution_failure or {}).get("failed_step_id"),
            "task_id": (execution_failure or {}).get("task_id"),
            "task_description": (execution_failure or {}).get("task_description"),
            "file_path": (execution_failure or {}).get("file_path"),
            "error_type": (execution_failure or {}).get("error_type"),
            "suggested_recovery": (execution_failure or {}).get("suggested_recovery"),
            "response_preview": (execution_failure or {}).get("response_preview"),
            "failure_reason": (
                improvement_result.get("failure_reason")
                if improvement_result
                else (execution_failure or {}).get("failure_reason")
            ),
            "retry_attempted": improvement_result.get("retry_attempted", False) if improvement_result else False,
            "retry_history": improvement_result.get("retry_history", []) if improvement_result else [],
            "remaining_goals": improvement_result.get("remaining_goals", []) if improvement_result else [],
            "stats": runtime.stats,
        }
        if include_final_result:
            result["final_result"] = final_result
        if not success and result.get("failure_reason"):
            self._log(
                "session_failure_context",
                output_summary={
                    "task_id": (execution_failure or {}).get("task_id"),
                    "failure_stage": result.get("failure_stage"),
                    "failed_tool": result.get("failed_tool"),
                    "failed_call_id": result.get("failed_call_id"),
                    "failed_step_id": result.get("failed_step_id"),
                    "file_path": result.get("file_path"),
                    "error_type": result.get("error_type"),
                    "suggested_recovery": result.get("suggested_recovery"),
                    "failure_reason": result.get("failure_reason"),
                },
                success=False,
                error=result.get("failure_reason"),
                level="ERROR",
            )
        return result

    def _log(
        self,
        event_type: str,
        *,
        success: bool | None = None,
        input_summary: Any | None = None,
        output_summary: Any | None = None,
        error: str | None = None,
        level: str | None = None,
    ) -> None:
        logger = getattr(self.runtime, "logger", None)
        if not logger:
            return
        logger.log_structured_event(
            source_type="module",
            source_name="autonomous_iteration.runtime_controller",
            phase="session_execution",
            event_type=event_type,
            session_id=getattr(self.runtime, "session_id", None) or "unknown",
            turn_id=1,
            success=success,
            input_summary=input_summary,
            output_summary=output_summary,
            error=error,
            level=level,
        )


class AgentRuntimeController:
    """High-level phase controller wrapping the existing autopilot execution path."""

    def __init__(
        self,
        runtime: Any,
        *,
        router: ToolRouter | None = None,
        state_updater: StateUpdater | None = None,
        runtime_guard: RuntimeGuard | None = None,
        file_selector: FileSelector | None = None,
        edit_guard: EditGuard | None = None,
        verifier: RuntimeVerifier | None = None,
        reporter: RuntimeReporter | None = None,
        session_executor: Any | None = None,
    ) -> None:
        self.runtime = runtime
        self.runtime_guard = runtime_guard or RuntimeGuard()
        self.router = router or ToolRouter(getattr(runtime, "tool_registry", None), guard=self.runtime_guard)
        self._active_task_id: str = ""
        self.state_updater = state_updater or StateUpdater(
            self.runtime_guard,
            state_event_sink=self._handle_state_event_change,
        )
        self.file_selector = file_selector or FileSelector()
        self.edit_guard = edit_guard or EditGuard()
        self.verifier = verifier or RuntimeVerifier()
        self.reporter = reporter or RuntimeReporter()
        self.session_executor = session_executor or _RuntimeSessionExecutor(runtime)
        self.state: RuntimeStateMetadata | None = None

    def run(self, goal: str, context: dict[str, Any] | None = None, *, mode: str = "standard") -> dict[str, Any]:
        """Run a goal while maintaining explicit runtime state."""
        context = context or {}
        state = RuntimeStateMetadata(goal=goal)
        self.state = state
        self._active_task_id = str(context.get("task_id") or getattr(self.runtime, "session_id", "") or "")
        apply_read_only_runtime_mode(
            state,
            goal,
            tags=[str(tag) for tag in context.get("tags") or []],
            task_type=str(context.get("task_type") or ""),
        )
        state.add_fact(f"User goal captured: {goal}")
        if context.get("project_path"):
            state.add_fact(f"Project path: {context['project_path']}")
            state.add_candidate_file(str(context["project_path"]), "project_path provided by caller")
        state.phase = AgentPhase.UNDERSTAND_PROJECT if context.get("project_path") else AgentPhase.UNDERSTAND_TASK
        self._emit_runtime_phase_change("", _phase_value(state.phase), state.verification_status, state.completion_reason, state)

        try:
            result = self.session_executor.run(goal, context, mode=mode)
        except Exception as exc:
            state.phase = AgentPhase.RECOVER
            hooks = getattr(self.runtime, "runtime_diagnostics_hooks", None)
            if hooks:
                hooks.on_failure(
                    FailureMetadata(
                        error_type=type(exc).__name__,
                        error_message=str(exc),
                        recoverable=False,
                    ),
                    source="runtime_failure",
                    task_id=str(context.get("task_id") or getattr(self.runtime, "session_id", "") or ""),
                )
            raise

        if isinstance(result, dict):
            self._absorb_session_result(state, result)
            return self._runtime_result(state, result)

        state.phase = AgentPhase.SUMMARIZE
        state.completion_reason = "runtime session returned non-dict result"
        return self._runtime_result(state, {"result": result, "success": bool(result)})

    def _absorb_session_result(self, state: RuntimeStateMetadata, result: dict[str, Any]) -> None:
        previous_phase = _phase_value(state.phase)
        previous_verification_status = str(state.verification_status or "")
        success = bool(result.get("success"))
        stats = result.get("stats")
        if isinstance(stats, dict):
            for key in ("tasks_completed", "tasks_failed"):
                if key in stats:
                    state.add_fact(f"{key}: {stats[key]}")
        for file_path in result.get("written_files") or result.get("changed_files") or []:
            state.add_modified_file(str(file_path))
        if state.modified_files:
            state.verification_status = "passed" if success else "failed"
        state.phase = AgentPhase.SUMMARIZE if success else AgentPhase.RECOVER
        state.completion_reason = "runtime session completed" if success else str(result.get("error") or "runtime session failed")
        if _phase_value(state.phase) != previous_phase:
            self._emit_runtime_phase_change(previous_phase, _phase_value(state.phase), state.verification_status, state.completion_reason, state)
        if str(state.verification_status or "") != previous_verification_status:
            self._emit_verification_state_change(previous_verification_status, str(state.verification_status or ""), _phase_value(state.phase), state.completion_reason, state)

    def _runtime_result(self, state: RuntimeStateMetadata, session_result: dict[str, Any]) -> dict[str, Any]:
        report = self.reporter.report(state)
        hooks = getattr(self.runtime, "runtime_diagnostics_hooks", None)
        if hooks:
            root_task_id = self._active_task_id or str(getattr(self.runtime, "session_id", "") or "")
            hooks.on_runtime_state_updated(state)
            if bool(session_result.get("success")) and report.residual_risks:
                hooks.on_suspicious_success(
                    task_id=root_task_id,
                    evidence=list(report.residual_risks),
                )
            hooks.on_task_finished(
                task_id=root_task_id,
                success=bool(session_result.get("success")),
                summary={
                    "phase": state.phase.value if hasattr(state.phase, "value") else str(state.phase),
                    "verification_status": state.verification_status,
                    "modified_files": list(state.modified_files),
                    "completion_reason": state.completion_reason,
                },
                session_id=str(getattr(self.runtime, "session_id", "") or ""),
            )
        result = {
            "success": bool(session_result.get("success")),
            "goal": state.goal,
            "agent_runtime_state": state.to_json_dict(),
            "runtime_report": report.to_json_dict(),
            "session_result": session_result,
        }
        for key in (
            "failure_reason",
            "failure_stage",
            "failed_tool",
            "failed_call_id",
            "failed_step_id",
            "task_id",
            "task_description",
            "file_path",
            "error_type",
            "suggested_recovery",
            "response_preview",
        ):
            value = session_result.get(key)
            if value not in (None, "", [], {}):
                result[key] = value
        return result

    def _handle_state_event_change(self, state: RuntimeStateMetadata, change_kind: str, previous_value: str) -> None:
        if change_kind == "phase":
            self._emit_runtime_phase_change(
                previous_value,
                _phase_value(state.phase),
                str(state.verification_status or ""),
                state.completion_reason,
                state,
            )
            return
        if change_kind == "verification":
            self._emit_verification_state_change(
                previous_value,
                str(state.verification_status or ""),
                _phase_value(state.phase),
                state.completion_reason,
                state,
            )

    def _emit_runtime_phase_change(
        self,
        previous_phase: str,
        phase: str,
        verification_status: str,
        completion_reason: str,
        state: RuntimeStateMetadata,
    ) -> None:
        hooks = getattr(self.runtime, "runtime_diagnostics_hooks", None)
        if not hooks:
            return
        hooks.on_runtime_phase_changed(
            task_id=self._active_task_id or str(getattr(self.runtime, "session_id", "") or ""),
            session_id=str(getattr(self.runtime, "session_id", "") or ""),
            previous_phase=previous_phase,
            phase=phase,
            verification_status=verification_status,
            completion_reason=completion_reason,
            state=state,
        )

    def _emit_verification_state_change(
        self,
        previous_status: str,
        verification_status: str,
        phase: str,
        reason: str,
        state: RuntimeStateMetadata,
    ) -> None:
        hooks = getattr(self.runtime, "runtime_diagnostics_hooks", None)
        if not hooks:
            return
        hooks.on_verification_state_changed(
            task_id=self._active_task_id or str(getattr(self.runtime, "session_id", "") or ""),
            session_id=str(getattr(self.runtime, "session_id", "") or ""),
            previous_status=previous_status,
            verification_status=verification_status,
            phase=phase,
            reason=reason,
            state=state,
        )

    def handle_streamed_need(self, need: DecisionNeedMetadata) -> list[ToolSelection]:
        """Interrupt generation for one need and route it through the runtime state."""
        if self.state is None:
            self.state = RuntimeStateMetadata(goal=need.question or "streamed need")
        self.state.record_tool_event(
            {
                "event_type": "stream_need_interrupt",
                "phase": _phase_value(self.state.phase),
                "need_type": need.need_type,
                "question": need.question,
            }
        )
        return self.router.route(self.state, need)

    def absorb_streamed_tool_result(self, selection: ToolSelection, execution_result: Any) -> RuntimeStateMetadata:
        """Resume generation after a streamed tool result has been absorbed."""
        if self.state is None:
            self.state = RuntimeStateMetadata(goal=selection.step_id)
        self.state_updater.apply_tool_result(self.state, selection, execution_result)
        self.state.record_tool_event(
            {
                "event_type": "stream_need_resume",
                "phase": _phase_value(self.state.phase),
                "tool_name": selection.tool_name,
                "success": bool(getattr(execution_result, "success", False)),
            }
        )
        return self.state
