"""Prompt and product-fit context helpers for autonomous iteration."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable


class ImprovementContextHelper:
    """Build deterministic improvement context outside the executor class."""

    def __init__(
        self,
        *,
        environment_context_getter: Callable[[Path | None], dict[str, Any]] | None = None,
        logger: Any | None = None,
        session_id_getter: Callable[[], str | None] | None = None,
    ) -> None:
        self.environment_context_getter = environment_context_getter or (lambda _path: {})
        self.logger = logger
        self.session_id_getter = session_id_getter

    def select_iteration_target_file(self, written_files: list[str], actions: list[str]) -> Path | None:
        candidates = [Path(path).expanduser() for path in written_files if str(path).endswith(".py")]
        existing = [path for path in candidates if path.exists()]
        if len(existing) == 1:
            result = existing[0]
        else:
            action_text = " ".join(actions)
            result = None
            for path in existing:
                if path.name in action_text or str(path) in action_text:
                    result = path
                    break
        self._log(
            "select_iteration_target_file",
            {"written_files": written_files, "actions": actions[:3]},
            {"target_file": str(result) if result else ""},
        )
        return result

    def build_prompt_context(
        self,
        *,
        original_goal: str,
        project_path: Path | None = None,
        written_files: list[str] | None = None,
        run_command: str = "",
        evaluation: Any | None = None,
        iteration_goal: str = "",
        acceptance_criteria: list[str] | None = None,
        tool_task: str = "",
        agent_instruction: str = "",
        target_file: Path | None = None,
        current_code: str = "",
        code_context: str = "",
        mode: str = "",
    ) -> dict[str, Any]:
        product_judgment = self.infer_product_judgment(
            original_goal=original_goal,
            project_path=project_path,
            written_files=written_files or [],
            current_code=current_code,
        )
        quality_rubric = self.quality_rubric_for_product(product_judgment)
        project_context = {
            "project_path": str(project_path) if project_path else "",
            "target_file": str(target_file) if target_file else "",
            "written_files": written_files or [],
            "run_command": run_command,
            "environment": self.environment_context_getter(project_path),
            "validation_passed": getattr(evaluation, "validation_passed", None),
            "validation_errors": getattr(evaluation, "validation_errors", [])[:3] if evaluation else [],
            "warnings": getattr(evaluation, "warnings", [])[:3] if evaluation else [],
            "retry_mode": mode,
        }
        if code_context:
            project_context["current_code_context"] = code_context
        result = {
            "original_goal": original_goal,
            "project_context": project_context,
            "product_judgment": product_judgment,
            "quality_rubric": quality_rubric,
            "agent_instruction": agent_instruction,
            "iteration_goal": iteration_goal,
            "acceptance_criteria": acceptance_criteria or [],
            "tool_task": tool_task,
        }
        self._log("build_prompt_context", {"goal": original_goal, "mode": mode}, self.prompt_context_layer_summary(result))
        return result

    def infer_product_judgment(
        self,
        *,
        original_goal: str,
        project_path: Path | None,
        written_files: list[str],
        current_code: str = "",
    ) -> dict[str, Any]:
        goal_text = original_goal.lower()
        explicit_terminal = any(term in goal_text for term in ("terminal", "curses", "cli", "shell", "命令行", "终端", "控制台"))
        is_game = any(term in goal_text for term in ("snake", "贪吃蛇", "game", "游戏"))
        code_text = current_code.lower()
        if not code_text and project_path:
            for raw_path in written_files[:3]:
                path = Path(raw_path).expanduser()
                if not path.is_absolute():
                    path = project_path / path
                if path.exists() and path.suffix == ".py":
                    try:
                        code_text += "\n" + path.read_text(encoding="utf-8")[:3000].lower()
                    except OSError:
                        pass

        if "pygame" in code_text:
            current_runtime = "pygame_gui"
        elif "import tkinter" in code_text or "from tkinter" in code_text or "tk." in code_text or "tkinter." in code_text:
            current_runtime = "tkinter_gui"
        elif "import curses" in code_text or "curses." in code_text or "stdscr" in code_text:
            current_runtime = "terminal_curses"
        else:
            current_runtime = "unknown"

        if explicit_terminal:
            preferred_runtime = "terminal"
            preferred_stack = "curses"
            recommendation = "User explicitly requested a terminal/CLI experience; improve the terminal implementation."
        elif is_game:
            preferred_runtime = "standalone_gui"
            preferred_stack = "pygame"
            recommendation = (
                "For a simple Python game, default product fit favors a standalone GUI window. "
                "Terminal/curses should be a fallback, not the preferred experience."
            )
        else:
            preferred_runtime = "best_fit_for_goal"
            preferred_stack = "project_native"
            recommendation = "Choose the runtime shape that best matches the user's project category."
        result = {
            "project_type": "interactive_game" if is_game else "general_project",
            "explicit_terminal_requested": explicit_terminal,
            "current_runtime": current_runtime,
            "preferred_runtime": preferred_runtime,
            "preferred_stack": preferred_stack,
            "recommendation": recommendation,
        }
        self._log("infer_product_judgment", {"goal": original_goal}, result)
        return result

    def fallback_should_prefer_pygame(self, prompt_context: dict[str, Any]) -> bool:
        product_judgment = prompt_context.get("product_judgment") or {}
        result = (
            not product_judgment.get("explicit_terminal_requested")
            and product_judgment.get("project_type") == "interactive_game"
            and product_judgment.get("preferred_stack") == "pygame"
            and product_judgment.get("current_runtime") != "pygame_gui"
        )
        self._log("fallback_should_prefer_pygame", product_judgment, {"result": result})
        return result

    def quality_rubric_for_product(self, product_judgment: dict[str, Any]) -> list[str]:
        rubric = [
            "Product fit: the implementation form must match what users normally expect for this project type.",
            "User experience: controls, feedback, scoring/status, and restart/quit flows should be visible and easy to use.",
            "Functional completeness: the observable behavior must satisfy the original goal before adding polish.",
            "Runtime clarity: README and run command must match dependencies and the actual entry point.",
        ]
        if product_judgment.get("preferred_stack") == "pygame":
            rubric.insert(
                1,
                "For a default Python snake game, prefer a standalone pygame GUI over terminal/curses unless terminal was explicitly requested.",
            )
            rubric.append(
                "Do not count terminal-only polish such as resize handling or pause as a better product-fit improvement than migrating a curses game to pygame."
            )
        self._log("quality_rubric_for_product", product_judgment, {"rubric_items": len(rubric)})
        return rubric

    def prompt_context_layer_summary(self, prompt_context: dict[str, Any]) -> dict[str, Any]:
        product = prompt_context.get("product_judgment") or {}
        project_context = prompt_context.get("project_context") or {}
        return {
            "has_original_goal": bool(prompt_context.get("original_goal")),
            "preferred_runtime": product.get("preferred_runtime"),
            "preferred_stack": product.get("preferred_stack"),
            "current_runtime": product.get("current_runtime"),
            "rubric_items": len(prompt_context.get("quality_rubric") or []),
            "tool_task_chars": len(str(prompt_context.get("tool_task") or "")),
            "code_context_chars": len(str(project_context.get("current_code_context") or "")),
        }

    def _log(self, source_name: str, input_summary: Any, output_summary: Any) -> None:
        if not self.logger or not hasattr(self.logger, "log_structured_event"):
            return
        session_id = self.session_id_getter() if self.session_id_getter else "unknown"
        self.logger.log_structured_event(
            source_type="function",
            source_name=f"autonomous_iteration.improvement_context.{source_name}",
            phase="improvement_context",
            event_type="function_completed",
            session_id=session_id or "unknown",
            turn_id=1,
            success=True,
            input_summary=input_summary,
            output_summary=output_summary,
        )
