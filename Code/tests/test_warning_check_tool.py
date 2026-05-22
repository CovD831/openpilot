from __future__ import annotations

from metadata import ResultStatus, ToolInputMetadata, WarningCheckResultMetadata
from tools.builtin_tools import register_builtin_tools
from tools.tool_registry import ToolRegistry
from tools.warning_check_tool import warning_check_tool_executor


PYGAME_FONT_WARNING = (
    "/site-packages/pygame/sysfont.py:226: UserWarning: Process running '/usr/X11/bin/fc-list' timed-out! "
    "System fonts cannot be loaded on your platform"
)


def test_pygame_font_warning_requires_fix() -> None:
    result = warning_check_tool_executor(
        ToolInputMetadata.from_mapping(
            "warning_check_tool",
            {"stderr": PYGAME_FONT_WARNING, "command": "python main.py", "cwd": "/tmp/project"},
        )
    )

    assert result.status == ResultStatus.SUCCESS
    assert isinstance(result.result, WarningCheckResultMetadata)
    assert result.result.requires_fix is True
    assert result.result.warnings[0].category == "font_rendering"
    assert "pygame system font discovery" in result.result.reason.lower()


def test_macos_tsm_notice_is_ignored() -> None:
    result = warning_check_tool_executor(
        ToolInputMetadata.from_mapping(
            "warning_check_tool",
            {
                "stderr": (
                    "2026-05-22 11:48:09.847 python[69575:38208670] "
                    "TSM AdjustCapsLockLEDForKeyTransitionHandling - ignored"
                )
            },
        )
    )

    assert result.result.requires_fix is False
    assert result.result.warnings == []
    assert result.result.ignored_warnings[0].category == "macos_input_system_notice"


def test_generic_deprecation_warning_does_not_trigger_bug_fix() -> None:
    result = warning_check_tool_executor(
        ToolInputMetadata.from_mapping("warning_check_tool", {"stderr": "DeprecationWarning: old API"})
    )

    assert result.result.requires_fix is False
    assert result.result.warnings == []
    assert result.result.ignored_warnings[0].category == "non_blocking_runtime_warning"


def test_warning_check_tool_is_registered() -> None:
    registry = ToolRegistry()
    register_builtin_tools(registry)

    assert registry.get("warning_check_tool") is not None
