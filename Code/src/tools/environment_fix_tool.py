"""Environment Fix Tool - diagnose and repair project-local setup failures."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from core.python_packages import (
    canonical_distribution_name,
    distribution_for_import,
    plausible_distribution_alias,
    replace_requirement_name,
    requirement_name,
)
from core.tool_contracts import PermissionLevel, ToolCapability, ToolDefinition, ToolFailureMode
from memory.memory_models import MemoryRecord, MemoryType
from metadata import (
    EnvironmentFailureMetadata,
    EnvironmentFixResultMetadata,
    FailureMetadata,
    ResultStatus,
    ToolContractMetadata,
    ToolInputMetadata,
    ToolResultMetadata,
    metadata_tool_result,
)
from tools.command_tool import command_executor


ENVIRONMENT_FIX_TOOL_DEFINITION = ToolDefinition(
    name="environment_fix_tool",
    display_name="Environment Fix Tool",
    description="Diagnose and repair project-local Python environment setup failures",
    version="1.0.0",
    capabilities=[ToolCapability.FILE_READ, ToolCapability.FILE_WRITE, ToolCapability.SHELL_EXECUTION],
    permission_level=PermissionLevel.HIGH,
    contract_metadata=ToolContractMetadata(
        tool_name="environment_fix_tool",
        input_metadata_type="ToolInputMetadata",
        output_metadata_type="ToolResultMetadata",
        required_input_fields=["project_path"],
        input_defaults={"encoding": "utf-8"},
    ),
    timeout_seconds=60,
    max_retries=0,
    failure_modes=[
        ToolFailureMode(
            error_type="unsupported_environment_failure",
            description="The setup failure was not recognized as a repairable Python environment issue",
            recovery_strategy="Show the root cause and ask the user for a manual recovery command.",
        ),
    ],
    tags=["environment", "pip", "requirements", "repair"],
    audit_required=True,
)


@metadata_tool_result("environment_fix_tool")
def environment_fix_tool_executor(input_metadata: ToolInputMetadata) -> ToolResultMetadata:
    params = input_metadata.to_params()
    project_path = Path(str(params["project_path"])).expanduser()
    error_text = str(params.get("stderr") or params.get("text") or params.get("context") or "")
    if not error_text:
        error_text = str(params.get("error_message") or "")

    diagnosis = diagnose_environment_failure(project_path, error_text)
    changed_files: list[str] = []
    repair_actions: list[str] = []
    replacement_requirement = ""
    research_queries: list[str] = []
    research_results: list[dict[str, Any]] = []
    memory_record_ids: list[str] = []
    applied = False

    if diagnosis.error_type == "invalid_requirements_file" and diagnosis.affected_file:
        target = Path(diagnosis.affected_file).expanduser()
        if target.exists() and target.is_file():
            original = target.read_text(encoding=str(params.get("encoding") or "utf-8"))
            updated, removed = _sanitize_requirements(original, diagnosis.line_number)
            if updated != original:
                target.write_text(updated, encoding=str(params.get("encoding") or "utf-8"))
                changed_files.append(str(target))
                repair_actions.append(
                    f"Removed invalid requirement line(s) from {target.name}: {', '.join(removed)}"
                )
                applied = True
    elif diagnosis.error_type == "unavailable_distribution" and diagnosis.affected_file:
        target = Path(diagnosis.affected_file).expanduser()
        if target.exists() and target.is_file():
            replacement_requirement, research_queries, research_results, recalled_memory_ids = (
                _resolve_distribution_alias(
                    diagnosis.failed_requirement,
                    memory_store=params.get("_memory_store"),
                    web_searcher=params.get("_web_searcher"),
                )
            )
            memory_record_ids.extend(recalled_memory_ids)
            if replacement_requirement:
                original = target.read_text(encoding=str(params.get("encoding") or "utf-8"))
                updated, replaced_lines = _replace_requirement(
                    original,
                    diagnosis.failed_requirement,
                    replacement_requirement,
                )
                if updated != original:
                    target.write_text(updated, encoding=str(params.get("encoding") or "utf-8"))
                    changed_files.append(str(target))
                    repair_actions.append(
                        f"Replaced unavailable distribution {diagnosis.failed_requirement!r} "
                        f"with {replacement_requirement!r} in {target.name}: {', '.join(replaced_lines)}"
                    )
                    applied = True
                    memory_record_id = _remember_resolved_distribution_alias(
                        params.get("_memory_store"),
                        diagnosis.failed_requirement,
                        replacement_requirement,
                        research_queries,
                        research_results,
                    )
                    if memory_record_id and memory_record_id not in memory_record_ids:
                        memory_record_ids.append(memory_record_id)

    command_executed = False
    user_declined = False
    if not applied and diagnosis.error_type == "environment_setup_failed" and diagnosis.suggested_command:
        try:
            command_result = command_executor(
                ToolInputMetadata.from_mapping(
                    "command_executor",
                    {
                        "command": diagnosis.suggested_command,
                        "mode": "automatic",
                        "cwd": str(project_path),
                        "_command_approval_callback": params.get("_command_approval_callback"),
                    },
                )
            )
            command_executed = True
            command_payload = command_result.result
            if getattr(command_payload, "success", False):
                repair_actions.append(f"Executed environment repair command: {diagnosis.suggested_command}")
                applied = True
            else:
                repair_actions.append(
                    "Environment repair command failed: "
                    f"{getattr(command_payload, 'stderr', '') or getattr(command_payload, 'stdout', '')}"
                )
        except PermissionError as exc:
            user_declined = True
            repair_actions.append(str(exc))

    result = EnvironmentFixResultMetadata(
        project_path=str(project_path),
        environment_failure=diagnosis,
        applied=applied,
        changed_files=changed_files,
        repair_actions=repair_actions,
        replacement_requirement=replacement_requirement,
        research_queries=research_queries,
        research_results=research_results,
        memory_record_ids=memory_record_ids,
        suggested_command=diagnosis.suggested_command,
        command_executed=command_executed,
        requires_confirmation=diagnosis.requires_confirmation,
        user_declined=user_declined,
    )
    if applied:
        return ToolResultMetadata(tool_name="environment_fix_tool", status=ResultStatus.SUCCESS, result=result)

    return ToolResultMetadata(
        tool_name="environment_fix_tool",
        status=ResultStatus.FAIL,
        result=result,
        failure=FailureMetadata(
            error_type="UnsupportedEnvironmentFailure",
            error_message=diagnosis.root_cause or "Environment setup failed, but no automatic repair was available.",
            recoverable=True,
            retry_recommended=False,
            recovery_strategy=diagnosis.suggested_command or "Inspect the environment error and repair project dependencies manually.",
            details={
                "root_cause": diagnosis.root_cause,
                "affected_file": diagnosis.affected_file,
                "failed_requirement": diagnosis.failed_requirement,
                "replacement_requirement": replacement_requirement,
                "research_queries": research_queries,
                "research_results": research_results,
                "suggested_command": diagnosis.suggested_command,
                "pip_notices": diagnosis.pip_notices,
            },
        ),
    )


def diagnose_environment_failure(project_path: Path, error_text: str) -> EnvironmentFailureMetadata:
    """Extract a useful root cause from pip/venv setup output."""
    lines = [line.rstrip() for line in str(error_text or "").splitlines()]
    pip_notices = [line.strip() for line in lines if line.strip().startswith("[notice]")]
    non_notice_lines = [line for line in lines if line.strip() and not line.strip().startswith("[notice]")]
    root_cause = _first_error_line(non_notice_lines) or "\n".join(non_notice_lines[:3]).strip() or str(error_text).strip()

    invalid_requirement = re.search(
        r"ERROR:\s+Invalid requirement:\s+(?P<requirement>.+?)(?:\n|$).*?\(from line (?P<line>\d+) of (?P<path>[^)]+)\)",
        str(error_text),
        flags=re.DOTALL,
    )
    if invalid_requirement:
        affected_file = invalid_requirement.group("path").strip()
        line_number = int(invalid_requirement.group("line"))
        return EnvironmentFailureMetadata(
            raw_stderr=str(error_text or ""),
            root_cause=_first_error_line(non_notice_lines) or f"Invalid requirement in {affected_file}:{line_number}",
            error_type="invalid_requirements_file",
            affected_file=affected_file,
            line_number=line_number,
            pip_notices=pip_notices,
            suggested_command=f"Fix invalid requirement in {affected_file}, then rerun pip install -r requirements.txt",
            requires_confirmation=False,
        )

    unavailable_distribution = re.search(
        r"(?:Could not find a version that satisfies the requirement|No matching distribution found for)"
        r"\s+(?P<requirement>[^\s(]+)",
        str(error_text),
        flags=re.IGNORECASE,
    )
    if unavailable_distribution:
        failed_requirement = requirement_name(unavailable_distribution.group("requirement"))
        affected_file = _extract_existing_requirements_path(project_path, str(error_text))
        return EnvironmentFailureMetadata(
            raw_stderr=str(error_text or ""),
            root_cause=root_cause,
            error_type="unavailable_distribution",
            affected_file=affected_file,
            failed_requirement=failed_requirement,
            pip_notices=pip_notices,
            suggested_command=(
                f"Replace unavailable distribution {failed_requirement!r} with its published package name, "
                "then rerun pip install -r requirements.txt"
            ),
            requires_confirmation=False,
        )

    command_match = re.search(r"To update, run:\s*(?P<command>.+)", str(error_text))
    suggested_command = command_match.group("command").strip() if command_match else ""
    return EnvironmentFailureMetadata(
        raw_stderr=str(error_text or ""),
        root_cause=root_cause,
        error_type="environment_setup_failed",
        affected_file=_extract_existing_requirements_path(project_path, str(error_text)),
        pip_notices=pip_notices,
        suggested_command=suggested_command,
        requires_confirmation=bool(suggested_command and _command_needs_confirmation(suggested_command, project_path)),
    )


def _first_error_line(lines: list[str]) -> str:
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("ERROR:"):
            return stripped
    for line in lines:
        stripped = line.strip()
        if "error" in stripped.lower():
            return stripped
    return ""


def _extract_existing_requirements_path(project_path: Path, text: str) -> str:
    match = re.search(r"(/[^\s)]+requirements\.txt)", text)
    if match:
        return match.group(1)
    candidate = project_path / "requirements.txt"
    return str(candidate) if candidate.exists() else ""


def _sanitize_requirements(content: str, line_number: int | None) -> tuple[str, list[str]]:
    lines = content.splitlines(keepends=True)
    removed: list[str] = []
    updated: list[str] = []
    for index, line in enumerate(lines, start=1):
        stripped = line.strip()
        should_remove = stripped in {'"""', "'''", "```"} or stripped.startswith('"""') or stripped.startswith("'''")
        if line_number is not None and index == line_number and not _looks_like_requirement(stripped):
            should_remove = True
        if should_remove:
            removed.append(f"{index}: {stripped}")
            continue
        updated.append(line)
    return "".join(updated), removed


def _replace_requirement(content: str, failed_requirement: str, replacement: str) -> tuple[str, list[str]]:
    lines = content.splitlines(keepends=True)
    updated: list[str] = []
    replaced_lines: list[str] = []
    for index, line in enumerate(lines, start=1):
        if canonical_distribution_name(requirement_name(line)) == canonical_distribution_name(failed_requirement):
            replacement_line = replace_requirement_name(line, replacement)
            updated.append(replacement_line)
            replaced_lines.append(f"{index}: {line.strip()} -> {replacement_line.strip()}")
            continue
        updated.append(line)
    return "".join(updated), replaced_lines


def _resolve_distribution_alias(
    failed_requirement: str,
    *,
    memory_store: Any = None,
    web_searcher: Any = None,
) -> tuple[str, list[str], list[dict[str, Any]], list[str]]:
    remembered_alias, memory_ids = _recall_resolved_distribution_alias(memory_store, failed_requirement)
    if remembered_alias:
        return remembered_alias, [], [{"source": "memory", "candidate": remembered_alias}], memory_ids

    query = f"site:pypi.org/project {failed_requirement} Python package install"
    research_results = _search_distribution_alias(query, web_searcher=web_searcher)
    for research_result in research_results:
        candidate = str(research_result.get("candidate") or "")
        if plausible_distribution_alias(failed_requirement, candidate):
            return candidate, [query], research_results, []

    known_distribution = distribution_for_import(failed_requirement)
    if known_distribution != failed_requirement and plausible_distribution_alias(failed_requirement, known_distribution):
        research_results.append({"source": "known_import_alias", "candidate": known_distribution})
        return known_distribution, [query], research_results, []
    return "", [query], research_results, []


def _search_distribution_alias(query: str, *, web_searcher: Any = None) -> list[dict[str, Any]]:
    try:
        if callable(web_searcher):
            search_output = web_searcher(query)
        else:
            from tools.web_searcher import web_searcher_executor

            search_result = web_searcher_executor(
                ToolInputMetadata.from_mapping(
                    "web_searcher",
                    {
                        "query": query,
                        "max_results": 5,
                        "max_pages": 0,
                        "max_search_attempts": 3,
                        "search_budget_seconds": 6,
                        "timeout": 3,
                        "llm_cleanup": False,
                    },
                )
            )
            search_output = search_result.result
    except Exception as exc:
        return [{"source": "web_search", "error": str(exc)}]

    if hasattr(search_output, "results"):
        results = list(getattr(search_output, "results") or [])
    elif isinstance(search_output, dict):
        results = list(search_output.get("results") or [])
    elif isinstance(search_output, list):
        results = list(search_output)
    else:
        results = []

    research_results = []
    for item in results:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "")
        candidate = _pypi_project_name(url)
        research_results.append(
            {
                "source": "web_search",
                "url": url,
                "title": str(item.get("title") or ""),
                "candidate": candidate,
            }
        )
    return research_results


def _pypi_project_name(url: str) -> str:
    parsed = urlparse(str(url or ""))
    if parsed.netloc.lower().removeprefix("www.") != "pypi.org":
        return ""
    match = re.match(r"^/project/([^/]+)/?", parsed.path)
    return unquote(match.group(1)) if match else ""


def _recall_resolved_distribution_alias(memory_store: Any, failed_requirement: str) -> tuple[str, list[str]]:
    if not memory_store or not hasattr(memory_store, "load_all"):
        return "", []
    try:
        memories = memory_store.load_all(MemoryType.REFERENCE)
    except Exception:
        return "", []
    for memory in reversed(memories):
        attributes = dict(getattr(memory, "attributes", {}) or {})
        if (
            attributes.get("bug_kind") == "python_distribution_alias"
            and attributes.get("failed_requirement") == failed_requirement
        ):
            replacement = str(attributes.get("replacement_requirement") or "")
            if plausible_distribution_alias(failed_requirement, replacement):
                return replacement, [str(getattr(memory, "id", "") or "")]
    return "", []


def _remember_resolved_distribution_alias(
    memory_store: Any,
    failed_requirement: str,
    replacement_requirement: str,
    research_queries: list[str],
    research_results: list[dict[str, Any]],
) -> str:
    if not memory_store or not hasattr(memory_store, "save"):
        return ""
    existing, memory_ids = _recall_resolved_distribution_alias(memory_store, failed_requirement)
    if existing == replacement_requirement and memory_ids:
        return memory_ids[0]
    try:
        saved = memory_store.save(
            MemoryRecord(
                id="",
                memory_type=MemoryType.REFERENCE,
                content=(
                    f"Resolved Python dependency alias: install {replacement_requirement!r} "
                    f"when code imports or requirements request {failed_requirement!r}."
                ),
                tags=["resolved_bug", "python_packaging", "dependency_alias", failed_requirement],
                confidence=0.96,
                attributes={
                    "bug_kind": "python_distribution_alias",
                    "failed_requirement": failed_requirement,
                    "replacement_requirement": replacement_requirement,
                    "research_queries": research_queries,
                    "research_results": research_results,
                },
            )
        )
    except Exception:
        return ""
    return str(getattr(saved, "id", "") or "")


def _looks_like_requirement(value: str) -> bool:
    if not value or value.startswith("#"):
        return True
    if value.startswith(("-", "--")):
        return True
    if "://" in value or value.startswith(("git+", "file:")):
        return True
    return bool(re.match(r"^[A-Za-z0-9_.-]+(\s*(==|>=|<=|~=|!=|>|<).*)?(\[.*\])?$", value))


def _command_needs_confirmation(command: str, project_path: Path) -> bool:
    lowered = f" {command.lower()} "
    if re.search(r"(^|\s)(sudo|su)\b", lowered):
        return True
    if any(path in lowered for path in (" /usr", " /system", " /library", " /opt/homebrew")):
        return True
    if re.search(r"(^|\s)(brew|apt|apt-get|yum|dnf|pacman)\b", lowered):
        return True
    if " pip install" in lowered and ".venv" not in lowered and str(project_path) not in command:
        return True
    return False
