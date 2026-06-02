"""Prompt and product-fit context helpers for autonomous iteration."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from metadata import ProductIntentMetadata


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
        candidates = [Path(path).expanduser() for path in written_files]
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
        environment = self.environment_context_getter(project_path)
        stack_preset = environment.get("stack_preset") if isinstance(environment, dict) else None
        stack_preset = stack_preset if isinstance(stack_preset, dict) else {}
        product_judgment = self.infer_product_judgment(
            original_goal=original_goal,
            project_path=project_path,
            written_files=written_files or [],
            current_code=current_code,
            stack_preset=stack_preset,
        )
        product_intent = self.infer_product_intent(
            original_goal=original_goal,
            project_path=project_path,
            written_files=written_files or [],
            current_code=current_code,
            stack_preset=stack_preset,
        )
        quality_rubric = self.quality_rubric_for_product(product_judgment, stack_preset=stack_preset)
        project_context = {
            "project_path": str(project_path) if project_path else "",
            "target_file": str(target_file) if target_file else "",
            "written_files": written_files or [],
            "run_command": run_command,
            "environment": environment,
            "validation_passed": getattr(evaluation, "validation_passed", None),
            "validation_errors": getattr(evaluation, "validation_errors", [])[:3] if evaluation else [],
            "validation_issues": [
                issue.to_json_dict() if hasattr(issue, "to_json_dict") else issue
                for issue in (getattr(evaluation, "validation_issues", [])[:5] if evaluation else [])
            ],
            "warnings": getattr(evaluation, "warnings", [])[:3] if evaluation else [],
            "retry_mode": mode,
        }
        if code_context:
            project_context["current_code_context"] = code_context
        result = {
            "original_goal": original_goal,
            "project_context": project_context,
            "product_intent": product_intent.to_json_dict(),
            "product_judgment": product_judgment,
            "quality_rubric": quality_rubric,
            "stack_preset": stack_preset,
            "ui_iteration_contract": self.ui_iteration_contract(stack_preset),
            "agent_instruction": agent_instruction,
            "iteration_goal": iteration_goal,
            "acceptance_criteria": acceptance_criteria or [],
            "tool_task": tool_task,
        }
        self._log("build_prompt_context", {"goal": original_goal, "mode": mode}, self.prompt_context_layer_summary(result))
        return result

    def infer_product_intent(
        self,
        *,
        original_goal: str,
        project_path: Path | None,
        written_files: list[str],
        current_code: str = "",
        stack_preset: dict[str, Any] | None = None,
    ) -> ProductIntentMetadata:
        judgment = self.infer_product_judgment(
            original_goal=original_goal,
            project_path=project_path,
            written_files=written_files,
            current_code=current_code,
            stack_preset=stack_preset,
        )
        goal_text = original_goal.lower()
        code_text = current_code.lower()
        experience_type = str(judgment.get("project_type") or "general_project")
        runtime_mode = str(judgment.get("preferred_runtime") or "best_fit_for_goal")
        delivery_surface = str(judgment.get("preferred_surface") or judgment.get("preferred_stack") or "project_native")
        core_capabilities = self._core_capabilities_from_goal(goal_text)
        constraints = [
            "Repair runtime, warning, environment, and quality issues without changing the intended user experience.",
            f"Preserve delivery surface: {delivery_surface}.",
            f"Preserve runtime mode: {runtime_mode}.",
        ]
        disallowed = self._disallowed_substitutions(judgment, code_text)
        evidence = [
            f"goal:{original_goal[:200]}",
            f"current_runtime:{judgment.get('current_runtime')}",
            f"preferred_runtime:{runtime_mode}",
            f"preferred_stack:{delivery_surface}",
        ]
        return ProductIntentMetadata(
            experience_type=experience_type,
            runtime_mode=runtime_mode,
            delivery_surface=delivery_surface,
            target_platforms=["local_python"] if "python" in code_text or written_files else [],
            core_capabilities=core_capabilities,
            non_regression_constraints=constraints,
            disallowed_substitutions=disallowed,
            evidence=evidence,
            confidence=0.82 if experience_type != "general_project" else 0.62,
        )

    def infer_product_judgment(
        self,
        *,
        original_goal: str,
        project_path: Path | None,
        written_files: list[str],
        current_code: str = "",
        stack_preset: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        goal_text = original_goal.lower()
        stack_preset = stack_preset or {}
        explicit_terminal = any(term in goal_text for term in ("terminal", "curses", "cli", "shell", "命令行", "终端", "控制台"))
        web_surface = any(term in goal_text for term in ("web", "website", "browser", "site", "网页"))
        assistant_surface = any(term in goal_text for term in ("assistant", "助手", "planner", "tracker", "管理器", "管理系统"))
        interactive = any(term in goal_text for term in ("game", "游戏", "interactive", "交互"))
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
            preferred_stack = "terminal_native"
            recommendation = "User explicitly requested a terminal/CLI experience; preserve that delivery surface."
        elif web_surface:
            preferred_runtime = "browser"
            preferred_stack = "project_native"
            recommendation = "Preserve a browser-facing delivery surface while improving diagnosed project gaps."
        elif assistant_surface:
            preferred_runtime = "browser"
            preferred_stack = "frontend_backend_split"
            recommendation = "A user-facing assistant benefits from a browser UI unless the user explicitly requested terminal-only delivery."
        elif interactive:
            preferred_runtime = "interactive"
            preferred_stack = "project_native"
            recommendation = "Preserve the intended interactive experience while using diagnosis evidence to choose improvements."
        else:
            preferred_runtime = "best_fit_for_goal"
            preferred_stack = "project_native"
            recommendation = "Choose the runtime shape that best matches the user's project category."
        preset_surface = str(stack_preset.get("delivery_surface") or "")
        stack_preset_update: dict[str, Any] = {}
        if preset_surface:
            terminal_conflicts_with_goal = preset_surface == "terminal" and assistant_surface and not explicit_terminal
            if terminal_conflicts_with_goal:
                preferred_runtime = "browser"
                preferred_stack = "frontend_backend_split"
                recommendation = (
                    "Persisted terminal stack preset conflicts with the user-facing assistant goal; "
                    "request a browser UI stack revision before adding more terminal-only polish."
                )
                stack_preset_update = {
                    "delivery_surface": "browser",
                    "architecture": "frontend_backend_split",
                    "frontend_language": "html_css_javascript",
                    "frontend_frameworks": ["vanilla_web"],
                    "ui_strategy": "browser_application",
                    "ui_review_required": True,
                    "rationale": [
                        "The original goal is a user-facing assistant and does not explicitly request a terminal-only interface.",
                        "Generated CLI evidence should not override the user's product surface.",
                    ],
                }
            else:
                preferred_stack = str(stack_preset.get("architecture") or preferred_stack)
                if preset_surface == "browser":
                    preferred_runtime = "browser"
                elif preset_surface == "terminal":
                    preferred_runtime = "terminal"
                elif preset_surface == "interactive_runtime":
                    preferred_runtime = "interactive"
                recommendation = (
                    f"Honor persisted stack preset revision {stack_preset.get('revision', 1)}: "
                    f"{preset_surface} via {preferred_stack}."
                )
        result = {
            "project_type": "interactive_software" if interactive else ("web_software" if web_surface or assistant_surface else "general_project"),
            "explicit_terminal_requested": explicit_terminal,
            "current_runtime": current_runtime,
            "preferred_runtime": preferred_runtime,
            "preferred_stack": preferred_stack,
            "preferred_surface": stack_preset_update.get("delivery_surface") or preset_surface or preferred_stack,
            "recommendation": recommendation,
            "stack_preset_revision": stack_preset.get("revision"),
            "recommended_stack_preset_update": stack_preset_update,
            "ui_strategy": stack_preset.get("ui_strategy"),
            "ui_review_required": bool(stack_preset.get("ui_review_required") or stack_preset_update.get("ui_review_required")),
        }
        self._log("infer_product_judgment", {"goal": original_goal}, result)
        return result

    def _core_capabilities_from_goal(self, goal_text: str) -> list[str]:
        capabilities = []
        if any(term in goal_text for term in ("game", "游戏", "interactive", "交互")):
            capabilities.extend(["interactive_feedback", "user_controls"])
        if any(term in goal_text for term in ("web", "website", "网页", "site")):
            capabilities.extend(["browser_view", "responsive_ui"])
        if any(term in goal_text for term in ("cli", "terminal", "命令行", "终端")):
            capabilities.extend(["terminal_interaction"])
        if any(term in goal_text for term in ("report", "报告", "analysis", "分析")):
            capabilities.extend(["structured_output"])
        return capabilities or ["satisfy_original_goal"]

    def _disallowed_substitutions(self, judgment: dict[str, Any], code_text: str) -> list[str]:
        disallowed = []
        preferred_runtime = judgment.get("preferred_runtime")
        preferred_stack = judgment.get("preferred_stack")
        if preferred_runtime == "standalone_gui":
            disallowed.extend(["terminal_ui", "headless_only", "text_only_substitute"])
        if preferred_runtime == "terminal":
            disallowed.extend(["gui_only_substitute", "web_only_substitute"])
        current_runtime = judgment.get("current_runtime")
        current_matches_intent = (
            current_runtime
            and current_runtime != "unknown"
            and (
                preferred_runtime == "best_fit_for_goal"
                or (preferred_runtime == "standalone_gui" and str(current_runtime).endswith("_gui"))
                or (preferred_runtime == "terminal" and str(current_runtime).startswith("terminal"))
            )
        )
        if current_matches_intent:
            disallowed.append(f"unrequested_runtime_change_from_{current_runtime}")
        if preferred_stack and preferred_stack != "project_native":
            disallowed.append(f"substitute_away_from_{preferred_stack}")
        return disallowed

    def quality_rubric_for_product(
        self,
        product_judgment: dict[str, Any],
        *,
        stack_preset: dict[str, Any] | None = None,
    ) -> list[str]:
        stack_preset = stack_preset or {}
        rubric = [
            "Product fit: the delivery surface must preserve the user goal and inferred project objective.",
            "Functional completeness: the observable behavior must improve a diagnosed success metric before adding low-value polish.",
            "User experience: the primary workflow should be understandable and provide useful feedback.",
            "Reliability and runtime clarity: validation, dependencies, README, and run command must agree.",
            "Technical scalability: choose maintainable changes that keep the next iteration feasible.",
            "Innovation only counts when it is relevant to user value and supported by project evidence.",
        ]
        if stack_preset.get("ui_review_required"):
            rubric.insert(
                2,
                "UI impact is mandatory: every user-facing feature change must add or update coherent controls, states, and feedback on the planned surface.",
            )
        if stack_preset:
            rubric.append(
                "Technology-stack fit: honor the persisted frontend/backend language and framework preset; revise it explicitly before changing architecture."
            )
        self._log("quality_rubric_for_product", product_judgment, {"rubric_items": len(rubric)})
        return rubric

    def ui_iteration_contract(self, stack_preset: dict[str, Any]) -> dict[str, Any]:
        """Require every iteration to assess whether user-facing UI work is implicated."""
        return {
            "assessment_required": True,
            "implementation_required_for_user_facing_change": bool(stack_preset.get("ui_review_required")),
            "delivery_surface": str(stack_preset.get("delivery_surface") or "project_native"),
            "ui_strategy": str(stack_preset.get("ui_strategy") or "evaluate_user_facing_ui"),
            "instruction": (
                "Assess UI impact for every feature addition. When the change is user-facing, implement the corresponding "
                "controls, states, feedback, and navigation on the planned surface instead of treating UI as optional polish."
            ),
        }

    def prompt_context_layer_summary(self, prompt_context: dict[str, Any]) -> dict[str, Any]:
        product = prompt_context.get("product_judgment") or {}
        project_context = prompt_context.get("project_context") or {}
        return {
            "has_original_goal": bool(prompt_context.get("original_goal")),
            "has_product_intent": bool(prompt_context.get("product_intent")),
            "preferred_runtime": product.get("preferred_runtime"),
            "preferred_stack": product.get("preferred_stack"),
            "current_runtime": product.get("current_runtime"),
            "stack_preset_revision": (prompt_context.get("stack_preset") or {}).get("revision"),
            "ui_review_required": (prompt_context.get("ui_iteration_contract") or {}).get(
                "implementation_required_for_user_facing_change"
            ),
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
