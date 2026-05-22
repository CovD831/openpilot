"""Warning Check Tool - classify runtime warnings that need repair."""

from __future__ import annotations

from typing import Iterable

from core.tool_contracts import PermissionLevel, ToolCapability, ToolDefinition, ToolFailureMode
from metadata import (
    ResultStatus,
    ToolContractMetadata,
    ToolInputMetadata,
    ToolResultMetadata,
    WarningCheckResultMetadata,
    WarningItemMetadata,
)


WARNING_CHECK_TOOL_DEFINITION = ToolDefinition(
    name="warning_check_tool",
    display_name="Warning Check Tool",
    description=(
        "Classify runtime warnings and decide whether they require repair because they "
        "harm runnability, user-visible output, rendering, resources, or future stability."
    ),
    version="1.0.0",
    capabilities=[ToolCapability.CODE_EXECUTION],
    permission_level=PermissionLevel.AUTO,
    contract_metadata=ToolContractMetadata(
        tool_name="warning_check_tool",
        input_metadata_type="ToolInputMetadata",
        output_metadata_type="ToolResultMetadata",
        required_input_fields=[],
        input_defaults={"warnings": [], "stdout": None, "stderr": None, "command": None, "cwd": None},
    ),
    timeout_seconds=10,
    max_retries=0,
    failure_modes=[
        ToolFailureMode(
            error_type="invalid_input",
            description="Warning check input could not be interpreted",
            recovery_strategy="Provide warning lines, stdout, or stderr metadata.",
        )
    ],
    tags=["warning", "validation", "runtime", "ux"],
    audit_required=False,
)


def warning_check_tool_executor(input_metadata: ToolInputMetadata) -> ToolResultMetadata:
    """Assess runtime warnings and return strict warning-check metadata."""
    warning_lines = _extract_warning_lines(
        explicit_warnings=input_metadata.warnings,
        stdout=input_metadata.stdout or "",
        stderr=input_metadata.stderr or "",
    )
    important: list[WarningItemMetadata] = []
    ignored: list[WarningItemMetadata] = []

    for line in warning_lines:
        item = _classify_warning(line)
        if item.requires_fix:
            important.append(item)
        else:
            ignored.append(item)

    reason = ""
    recommended_fix = ""
    if important:
        reason = "; ".join(item.reason or item.warning_text for item in important[:3])
        recommended_fix = _recommended_fix(important)

    result = WarningCheckResultMetadata(
        command=input_metadata.command or "",
        cwd=input_metadata.cwd or "",
        warnings=important,
        ignored_warnings=ignored,
        requires_fix=bool(important),
        reason=reason,
        recommended_fix=recommended_fix,
    )
    return ToolResultMetadata(tool_name="warning_check_tool", status=ResultStatus.SUCCESS, result=result)


def _extract_warning_lines(*, explicit_warnings: Iterable[str], stdout: str, stderr: str) -> list[str]:
    lines: list[str] = []
    seen: set[str] = set()
    for raw in list(explicit_warnings or []) + stdout.splitlines() + stderr.splitlines():
        line = str(raw).strip()
        if not line or line in seen:
            continue
        lowered = line.lower()
        if _looks_like_warning(line) or _looks_like_ignorable_system_notice(lowered):
            lines.append(line)
            seen.add(line)
    return lines


def _looks_like_warning(line: str) -> bool:
    lowered = line.lower()
    return (
        "warning" in lowered
        or "warn(" in lowered
        or "userwarning" in lowered
        or "deprecationwarning" in lowered
        or "resourcewarning" in lowered
        or "system fonts cannot be loaded" in lowered
        or "fc-list" in lowered
    )


def _looks_like_ignorable_system_notice(lowered: str) -> bool:
    return "tsm adjustcapslockledforkeytransitionhandling" in lowered


def _classify_warning(warning_text: str) -> WarningItemMetadata:
    lowered = warning_text.lower()
    if _looks_like_ignorable_system_notice(lowered):
        return WarningItemMetadata(
            warning_text=warning_text,
            warning_source="platform",
            category="macos_input_system_notice",
            severity="ignore",
            affects_user_experience=False,
            requires_fix=False,
            reason="macOS keyboard subsystem notice; it does not affect generated project behavior.",
        )

    if _is_pygame_font_warning(lowered):
        return WarningItemMetadata(
            warning_text=warning_text,
            warning_source="pygame.sysfont",
            category="font_rendering",
            severity="fix_required",
            affects_user_experience=True,
            requires_fix=True,
            reason=(
                "Pygame system font discovery failed; text may render as boxes or disappear, "
                "which is a user-visible experience problem."
            ),
        )

    if _is_user_visible_resource_warning(lowered):
        return WarningItemMetadata(
            warning_text=warning_text,
            warning_source="runtime",
            category="user_visible_resource",
            severity="fix_required",
            affects_user_experience=True,
            requires_fix=True,
            reason="Warning indicates a missing or unavailable user-visible resource.",
        )

    if "deprecationwarning" in lowered or "resourcewarning" in lowered:
        return WarningItemMetadata(
            warning_text=warning_text,
            warning_source="runtime",
            category="non_blocking_runtime_warning",
            severity="info",
            affects_user_experience=False,
            requires_fix=False,
            reason="Warning is not known to affect current user-visible behavior.",
        )

    return WarningItemMetadata(
        warning_text=warning_text,
        warning_source="runtime",
        category="runtime_warning",
        severity="info",
        affects_user_experience=False,
        requires_fix=False,
        reason="Warning is not classified as requiring automatic repair.",
    )


def _is_pygame_font_warning(lowered: str) -> bool:
    return (
        ("pygame" in lowered and "sysfont" in lowered and "warning" in lowered)
        or ("fc-list" in lowered and "timed-out" in lowered)
        or "system fonts cannot be loaded" in lowered
    )


def _is_user_visible_resource_warning(lowered: str) -> bool:
    resource_terms = ("font", "image", "sound", "asset", "resource", "render", "glyph")
    failure_terms = ("cannot be loaded", "failed to load", "missing", "not found", "unavailable")
    return any(term in lowered for term in resource_terms) and any(term in lowered for term in failure_terms)


def _recommended_fix(warnings: list[WarningItemMetadata]) -> str:
    if any(item.category == "font_rendering" for item in warnings):
        return (
            "Avoid depending on pygame system font discovery. Use pygame.font.Font(None, size), "
            "bundle a known font file, or provide a robust fallback so score and UI text render correctly."
        )
    categories = sorted({item.category for item in warnings})
    return f"Fix runtime warning categories: {', '.join(categories)}."
