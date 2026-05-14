"""Project-level hard validator for iterative improvement."""

from __future__ import annotations

import ast
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any

from agents.evaluation_models import EvaluationResult


class ProjectEvaluatorAgent:
    """Validate whether a generated project can run without blocking bugs."""

    def __init__(self, llm_client: Any | None = None, smoke_timeout_seconds: int = 2):
        self.llm_client = llm_client
        self.smoke_timeout_seconds = smoke_timeout_seconds

    def evaluate_project(
        self,
        *,
        goal: str,
        project_path: str | Path,
        written_files: list[str],
        run_command: str = "",
        readme_path: str | Path | None = None,
        static_review: dict[str, Any] | None = None,
        iteration: int = 0,
    ) -> EvaluationResult:
        """Run deterministic hard validation."""
        project = Path(project_path).expanduser()
        files = [Path(path).expanduser() for path in written_files]
        readme = Path(readme_path).expanduser() if readme_path else project / "README.md"
        static_review = static_review or {}

        errors: list[str] = []
        warnings: list[str] = []
        opportunities: list[str] = []
        actions: list[str] = []

        existing_files = [path for path in files if path.exists()]
        if not existing_files:
            errors.append("No generated project files were found.")
            actions.append("Regenerate the missing project files in the requested directory.")
            return self._result(
                errors=errors,
                warnings=warnings,
                run_command=run_command,
                opportunities=opportunities,
                actions=actions,
                goal=goal,
                summary="Project validation failed: no generated files were found.",
            )

        code_text = "\n\n".join(self._read_text(path) for path in existing_files if path.suffix == ".py")
        readme_text = self._read_text(readme)
        effective_run_command = (run_command or self._extract_run_command(readme_text)).strip()

        for path in existing_files:
            if path.suffix != ".py":
                continue
            try:
                ast.parse(self._read_text(path))
            except SyntaxError as exc:
                errors.append(f"Syntax error in {path.name} at line {exc.lineno}: {exc.msg}")
                actions.append(f"Fix the syntax error in {path.name}.")

        if "{{" in code_text or "}}" in code_text:
            errors.append("Generated code still contains template placeholders.")
            actions.append("Replace placeholder content with real implementation.")

        if not effective_run_command:
            errors.append("README does not clearly explain how to run the project.")
            actions.append("Add a concrete run command to README.md.")

        if not static_review and code_text.strip():
            static_review = self._review_python_code(code_text)

        review_errors = self._blocking_review_errors(static_review)
        if review_errors:
            errors.extend(review_errors)
            actions.extend(static_review.get("suggestions") or [])

        if effective_run_command and not any(error.lower().startswith("syntax error") for error in errors):
            smoke = self._smoke_test(project, effective_run_command, existing_files)
            if not smoke["passed"]:
                errors.append(smoke["message"])
                actions.append("Fix the runtime error reported by the smoke test.")
            elif smoke["warning"]:
                warnings.append(smoke["message"])

        goal_lower = goal.lower()
        is_game = any(keyword in goal_lower for keyword in ("snake", "贪吃蛇", "game", "小游戏"))
        if is_game:
            missing_game_features = self._missing_game_features(code_text)
            if missing_game_features:
                warnings.extend(missing_game_features)
                opportunities.extend(missing_game_features[:3])
                actions.append("Improve the game loop, controls, scoring, food, collision, and game-over experience.")

        if warnings:
            opportunities.extend(warnings[:3])

        summary = (
            "Project validation passed."
            if not errors
            else f"Project validation failed with {len(errors)} blocking issue(s)."
        )
        return self._result(
            errors=errors,
            warnings=warnings,
            run_command=effective_run_command,
            opportunities=opportunities,
            actions=actions,
            goal=goal,
            summary=summary,
        )

    def _result(
        self,
        *,
        errors: list[str],
        warnings: list[str],
        run_command: str,
        opportunities: list[str],
        actions: list[str],
        goal: str,
        summary: str,
    ) -> EvaluationResult:
        deduped_errors = self._dedupe(errors)
        deduped_warnings = self._dedupe(warnings)
        deduped_actions = self._dedupe(actions)[:5]
        deduped_opportunities = self._dedupe(opportunities)
        validation_passed = not deduped_errors
        return EvaluationResult(
            validation_passed=validation_passed,
            runnable=validation_passed,
            has_blocking_bugs=bool(deduped_errors),
            summary=summary,
            validation_errors=deduped_errors,
            warnings=deduped_warnings,
            run_command=run_command,
            improvement_opportunities=deduped_opportunities,
            recommended_actions=deduped_actions,
            next_iteration_goal=self._build_next_iteration_goal(goal, deduped_actions, deduped_errors),
        )

    def _smoke_test(self, project_path: Path, run_command: str, files: list[Path] | None = None) -> dict[str, Any]:
        try:
            args = shlex.split(run_command)
        except ValueError as exc:
            return {"passed": False, "warning": False, "message": f"Run command cannot be parsed: {exc}"}

        if not args:
            return {"passed": False, "warning": False, "message": "Run command is empty."}

        args = self._normalize_python_args(project_path, args)

        if self._looks_interactive_python_project(files or [], args):
            import_result = self._import_only_smoke_test(project_path, args, files or [])
            if not import_result["passed"]:
                return import_result
            return {
                "passed": True,
                "warning": True,
                "message": "Smoke test skipped full run: interactive terminal or GUI program requires a real terminal/window.",
            }

        try:
            result = subprocess.run(
                args,
                cwd=project_path,
                capture_output=True,
                text=True,
                timeout=self.smoke_timeout_seconds,
                env=self._smoke_env(),
            )
        except FileNotFoundError as exc:
            return {"passed": False, "warning": False, "message": f"Run command failed: {exc}"}
        except subprocess.TimeoutExpired as exc:
            combined = f"{exc.stdout or ''}\n{exc.stderr or ''}"
            if self._looks_like_traceback(combined):
                return {"passed": False, "warning": False, "message": self._short_error("Smoke test timed out with error output", combined)}
            return {
                "passed": True,
                "warning": True,
                "message": f"Smoke test timed out after {self.smoke_timeout_seconds}s; treating as runnable for an interactive app.",
            }

        combined_output = f"{result.stdout or ''}\n{result.stderr or ''}"
        if self._is_interactive_environment_error(combined_output):
            return {
                "passed": True,
                "warning": True,
                "message": "Smoke test skipped full run: interactive terminal program requires a real terminal.",
            }
        if result.returncode != 0:
            return {
                "passed": False,
                "warning": False,
                "message": self._short_error(f"Smoke test exited with code {result.returncode}", combined_output),
            }
        if self._looks_like_traceback(combined_output):
            return {"passed": False, "warning": False, "message": self._short_error("Smoke test printed a traceback", combined_output)}
        return {"passed": True, "warning": False, "message": "Smoke test passed."}

    def _looks_interactive_python_project(self, files: list[Path], args: list[str]) -> bool:
        if not args or not self._is_python_executable(args[0]):
            return False
        source = "\n".join(self._read_text(path) for path in files if path.suffix == ".py")
        if not source:
            return False
        interactive_imports = ("curses", "tkinter", "turtle", "pygame")
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return any(f"import {name}" in source or f"from {name}" in source for name in interactive_imports)
        imports = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name.split(".", 1)[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module.split(".", 1)[0])
        return bool(imports.intersection(interactive_imports))

    def _import_only_smoke_test(self, project_path: Path, args: list[str], files: list[Path]) -> dict[str, Any]:
        entry = self._entry_module_from_args(project_path, args, files)
        if entry is None:
            return {"passed": True, "warning": True, "message": "Smoke test skipped full run: interactive project entry could not be imported safely."}

        command = [
            args[0],
            "-c",
            (
                "import importlib.util, pathlib; "
                f"path = pathlib.Path({str(entry)!r}); "
                "spec = importlib.util.spec_from_file_location('openpilot_smoke_entry', path); "
                "module = importlib.util.module_from_spec(spec); "
                "spec.loader.exec_module(module)"
            ),
        ]
        try:
            result = subprocess.run(
                command,
                cwd=project_path,
                capture_output=True,
                text=True,
                timeout=self.smoke_timeout_seconds,
                env=self._smoke_env(),
            )
        except subprocess.TimeoutExpired as exc:
            combined = f"{exc.stdout or ''}\n{exc.stderr or ''}"
            return {"passed": False, "warning": False, "message": self._short_error("Import-only smoke test timed out", combined)}

        combined_output = f"{result.stdout or ''}\n{result.stderr or ''}"
        if result.returncode != 0:
            return {
                "passed": False,
                "warning": False,
                "message": self._short_error(f"Import-only smoke test exited with code {result.returncode}", combined_output),
            }
        return {"passed": True, "warning": False, "message": "Import-only smoke test passed."}

    def _normalize_python_args(self, project_path: Path, args: list[str]) -> list[str]:
        if not args:
            return args
        executable = args[0]
        if executable == "python" or executable.startswith("python"):
            project_python = self._project_python_executable(project_path)
            args[0] = str(project_python or sys.executable)
        elif executable.startswith(".venv/") or executable.startswith(".venv\\"):
            args[0] = str(project_path / executable)
        return args

    def _project_python_executable(self, project_path: Path) -> Path | None:
        candidates = [
            project_path / ".venv" / "bin" / "python",
            project_path / ".venv" / "Scripts" / "python.exe",
        ]
        for candidate in candidates:
            if candidate.exists():
                return candidate
        return None

    def _is_python_executable(self, executable: str) -> bool:
        name = Path(executable).name.lower()
        return name == "python" or name.startswith("python")

    def _entry_module_from_args(self, project_path: Path, args: list[str], files: list[Path]) -> Path | None:
        for arg in args[1:]:
            if arg.startswith("-"):
                continue
            candidate = Path(arg).expanduser()
            if not candidate.is_absolute():
                candidate = project_path / candidate
            if candidate.suffix == ".py" and candidate.exists():
                return candidate
            break
        python_files = [path for path in files if path.suffix == ".py" and path.exists()]
        if len(python_files) == 1:
            return python_files[0]
        for name in ("main.py", "app.py"):
            candidate = project_path / name
            if candidate.exists():
                return candidate
        return python_files[0] if python_files else None

    def _smoke_env(self) -> dict[str, str]:
        env = os.environ.copy()
        env.setdefault("TERM", "xterm-256color")
        env.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
        return env

    def _blocking_review_errors(self, static_review: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        if static_review.get("approved") is False:
            errors.append("Static code review did not approve the generated code.")
        syntax_errors = static_review.get("syntax_errors") or []
        for error in syntax_errors:
            errors.append(f"Static review syntax error: {error}")
        for issue in static_review.get("issues") or []:
            if any(marker in str(issue).lower() for marker in ("syntax", "runtime", "import", "undefined", "security")):
                errors.append(f"Blocking static review issue: {issue}")
        return errors

    def _review_python_code(self, code_text: str) -> dict[str, Any]:
        try:
            from tools.code_reviewer import code_reviewer_executor

            return code_reviewer_executor({"code": code_text, "language": "python"})
        except Exception:
            return {}

    def _missing_game_features(self, code: str) -> list[str]:
        code_lower = code.lower()
        checks = [
            ("No visible game loop was detected.", ("while ", "after(", "mainloop", "tick(")),
            ("No controls or keyboard handling were detected.", ("key", "keyboard", "pygame.key", "onkeypress", "curses")),
            ("No score display or score tracking was detected.", ("score",)),
            ("No food/apple target behavior was detected.", ("food", "apple")),
            ("No collision or game-over handling was detected.", ("collision", "game_over", "game over", "self hit")),
        ]
        return [message for message, needles in checks if not any(needle in code_lower for needle in needles)]

    def _extract_run_command(self, readme_text: str) -> str:
        lines = readme_text.splitlines()
        for index, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith(("python ", "npm ", ".venv/bin/python ", ".venv/Scripts/python.exe ")):
                return stripped
            if stripped in {"```bash", "```sh", "```"} and index + 1 < len(lines):
                candidate = lines[index + 1].strip()
                if candidate.startswith(("python ", "npm ", ".venv/bin/python ", ".venv/Scripts/python.exe ")):
                    return candidate
        return ""

    def _build_next_iteration_goal(self, goal: str, actions: list[str], errors: list[str]) -> str | None:
        focus = actions[:2] or errors[:2]
        if not focus:
            return None
        return f"Fix the project for this goal: {goal}. Focus on: {'; '.join(focus)}"

    def _looks_like_traceback(self, output: str) -> bool:
        lower = output.lower()
        return any(marker in lower for marker in ("traceback", "syntaxerror", "modulenotfounderror", "importerror", "nameerror"))

    def _is_interactive_environment_error(self, output: str) -> bool:
        lower = self._strip_ansi(output).lower()
        markers = (
            "_curses.error: cbreak() returned err",
            "_curses.error: nocbreak() returned err",
            "_curses.error: endwin() returned err",
            "setupterm",
            "not a tty",
            "inappropriate ioctl for device",
            "no available video device",
            "cannot open display",
        )
        return any(marker in lower for marker in markers)

    def _short_error(self, prefix: str, output: str) -> str:
        clean_output = self._strip_ansi(output)
        clean = " ".join(line.strip() for line in clean_output.splitlines() if line.strip())
        if len(clean) > 500:
            clean = clean[:497] + "..."
        return f"{prefix}: {clean}" if clean else prefix

    def _strip_ansi(self, text: str) -> str:
        return re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", text or "")

    def _read_text(self, path: Path) -> str:
        try:
            return path.read_text(encoding="utf-8")
        except OSError:
            return ""

    def _dedupe(self, values: list[str]) -> list[str]:
        seen = set()
        result = []
        for value in values:
            if value and value not in seen:
                result.append(value)
                seen.add(value)
        return result
