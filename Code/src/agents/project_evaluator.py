"""Project-level evaluator agent for iterative improvement."""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any

from core.llm import LLMMessage, LLMRequest
from models.evaluation_models import EvaluationResult


class ProjectEvaluatorAgent:
    """Evaluate whether a generated project satisfies the user's goal."""

    def __init__(self, llm_client: Any | None = None, satisfaction_threshold: float = 0.85):
        self.llm_client = llm_client
        self.satisfaction_threshold = satisfaction_threshold

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
        """Evaluate a generated project with static checks plus optional LLM judgment."""
        project = Path(project_path).expanduser()
        files = [Path(path).expanduser() for path in written_files]
        readme = Path(readme_path).expanduser() if readme_path else project / "README.md"

        static_result = self._static_evaluation(
            goal=goal,
            project_path=project,
            files=files,
            readme_path=readme,
            run_command=run_command,
            static_review=static_review or {},
        )
        llm_result = self._llm_evaluation(
            goal=goal,
            project_path=project,
            files=files,
            readme_path=readme,
            run_command=run_command,
            static_result=static_result,
            iteration=iteration,
        )
        result = self._merge_evaluations(static_result, llm_result)
        result.approved = result.satisfaction_score >= self.satisfaction_threshold and not self._has_hard_failure(result)
        return result

    def _static_evaluation(
        self,
        *,
        goal: str,
        project_path: Path,
        files: list[Path],
        readme_path: Path,
        run_command: str,
        static_review: dict[str, Any],
    ) -> EvaluationResult:
        issues: list[str] = []
        opportunities: list[str] = []
        actions: list[str] = []

        existing_files = [path for path in files if path.exists()]
        if not existing_files:
            issues.append("No generated project files were found.")
            actions.append("Regenerate the project files in the requested directory.")
            return EvaluationResult(
                approved=False,
                satisfaction_score=0.15,
                summary="Project files are missing.",
                issues=issues,
                improvement_opportunities=opportunities,
                recommended_actions=actions,
                next_iteration_goal="Regenerate the missing project files.",
            )

        code_text = "\n\n".join(self._read_text(path) for path in existing_files if path.suffix == ".py")
        readme_text = self._read_text(readme_path)

        syntax_ok = True
        for path in existing_files:
            if path.suffix != ".py":
                continue
            try:
                ast.parse(self._read_text(path))
            except SyntaxError as exc:
                syntax_ok = False
                issues.append(f"Syntax error in {path.name} at line {exc.lineno}: {exc.msg}")
                actions.append(f"Fix the syntax error in {path.name}.")

        if "{{" in code_text or "}}" in code_text:
            issues.append("Generated code still contains template placeholders.")
            actions.append("Replace placeholder content with real implementation.")

        effective_run_command = run_command or self._extract_run_command(readme_text)
        if not effective_run_command:
            issues.append("README does not clearly explain how to run the project.")
            actions.append("Add a concrete run command to README.md.")

        goal_lower = goal.lower()
        is_game = any(keyword in goal_lower for keyword in ("snake", "贪吃蛇", "game", "小游戏"))
        if is_game:
            missing_game_features = self._missing_game_features(code_text)
            if missing_game_features:
                issues.extend(missing_game_features)
                actions.append("Improve the game loop, controls, scoring, and restart/game-over experience.")

        review_score = static_review.get("quality_score")
        if review_score is not None and review_score < 0.8:
            issues.append(f"Static code quality score is {review_score:.2f}.")
            actions.extend(static_review.get("suggestions") or [])

        functionality = 0.75 if existing_files else 0.0
        if is_game:
            functionality = 1.0 - min(0.45, 0.09 * len(self._missing_game_features(code_text)))
        runnability = 1.0 if syntax_ok and effective_run_command else 0.55 if syntax_ok else 0.2
        code_quality = float(review_score) if review_score is not None else self._static_code_quality(code_text)
        user_experience = 0.9 if not is_game or not self._missing_game_features(code_text) else 0.55
        documentation = 1.0 if "## Run" in readme_text and effective_run_command else 0.45

        score = (
            functionality * 0.30
            + runnability * 0.25
            + code_quality * 0.20
            + user_experience * 0.15
            + documentation * 0.10
        )
        if not syntax_ok:
            score = min(score, 0.45)
        if "{{" in code_text:
            score = min(score, 0.35)

        if score < self.satisfaction_threshold and not actions:
            opportunities.append("Polish the implementation to better satisfy the original goal.")
            actions.append("Add missing user-facing behavior and improve code structure.")
        if issues:
            opportunities.extend(issues[:3])

        summary = (
            f"Automatic project evaluation scored {score:.2f}. "
            f"Detected {len(issues)} issue(s)."
        )
        return EvaluationResult(
            approved=score >= self.satisfaction_threshold and not issues,
            satisfaction_score=max(0.0, min(1.0, score)),
            summary=summary,
            issues=issues,
            improvement_opportunities=opportunities,
            recommended_actions=actions[:5],
            next_iteration_goal=self._build_next_iteration_goal(goal, actions, issues),
        )

    def _llm_evaluation(
        self,
        *,
        goal: str,
        project_path: Path,
        files: list[Path],
        readme_path: Path,
        run_command: str,
        static_result: EvaluationResult,
        iteration: int,
    ) -> EvaluationResult | None:
        if not self.llm_client or not hasattr(self.llm_client, "complete"):
            return None

        file_previews = []
        for path in files[:5]:
            if path.exists():
                file_previews.append(f"FILE: {path.name}\n{self._read_text(path)[:1800]}")
        readme_preview = self._read_text(readme_path)[:1200]

        prompt = f"""You are OpenPilot's Project Evaluator Agent.
Evaluate the generated project against the user's goal. Return ONLY valid JSON.
Do not include private internal reasoning. Use concise public reasoning in summary.

Goal: {goal}
Project path: {project_path}
Iteration: {iteration}
Run command: {run_command}
Static evaluation: {static_result.model_dump()}
README preview:
{readme_preview}

Project file previews:
{chr(10).join(file_previews)}

Return JSON:
{{
  "approved": false,
  "satisfaction_score": 0.0,
  "summary": "short public evaluation",
  "issues": ["issue"],
  "improvement_opportunities": ["opportunity"],
  "recommended_actions": ["action"],
  "next_iteration_goal": "specific improvement request or null"
}}
"""
        try:
            response = self.llm_client.complete(
                LLMRequest(
                    messages=[LLMMessage(role="user", content=prompt)],
                    response_format="json_object",
                    temperature=0.2,
                ),
                max_retries=2,
                use_cache=False,
            )
        except Exception:
            return None

        payload = response.parsed_json if isinstance(response.parsed_json, dict) else None
        if payload is None:
            try:
                payload = json.loads(response.content)
            except (TypeError, json.JSONDecodeError):
                return None
        if "satisfaction_score" not in payload:
            return None

        try:
            return EvaluationResult(
                approved=bool(payload.get("approved", False)),
                satisfaction_score=float(payload.get("satisfaction_score", 0.0)),
                summary=str(payload.get("summary") or "Project evaluated."),
                issues=[str(item) for item in payload.get("issues") or []],
                improvement_opportunities=[str(item) for item in payload.get("improvement_opportunities") or []],
                recommended_actions=[str(item) for item in payload.get("recommended_actions") or []],
                next_iteration_goal=payload.get("next_iteration_goal"),
            )
        except Exception:
            return None

    def _merge_evaluations(
        self,
        static_result: EvaluationResult,
        llm_result: EvaluationResult | None,
    ) -> EvaluationResult:
        if llm_result is None:
            return static_result

        hard_failure_cap = 1.0
        if self._has_hard_failure(static_result):
            hard_failure_cap = min(hard_failure_cap, 0.55)
        score = min(hard_failure_cap, (static_result.satisfaction_score * 0.55 + llm_result.satisfaction_score * 0.45))
        issues = self._dedupe(static_result.issues + llm_result.issues)
        opportunities = self._dedupe(static_result.improvement_opportunities + llm_result.improvement_opportunities)
        actions = self._dedupe(static_result.recommended_actions + llm_result.recommended_actions)

        return EvaluationResult(
            approved=score >= self.satisfaction_threshold and not self._has_hard_failure(static_result),
            satisfaction_score=max(0.0, min(1.0, score)),
            summary=llm_result.summary or static_result.summary,
            issues=issues,
            improvement_opportunities=opportunities,
            recommended_actions=actions[:5],
            next_iteration_goal=llm_result.next_iteration_goal or static_result.next_iteration_goal,
        )

    def _missing_game_features(self, code: str) -> list[str]:
        code_lower = code.lower()
        checks = [
            ("No visible game loop was detected.", ("while ", "after(", "mainloop", "tick(")),
            ("No controls or keyboard handling were detected.", ("key", "keyboard", "pygame.key", "onkeypress", "curses")),
            ("No score display or score tracking was detected.", ("score",)),
            ("No food/apple target behavior was detected.", ("food", "apple")),
            ("No collision or game-over handling was detected.", ("collision", "game_over", "game over", "self hit")),
        ]
        missing = []
        for message, needles in checks:
            if not any(needle in code_lower for needle in needles):
                missing.append(message)
        return missing

    def _static_code_quality(self, code: str) -> float:
        if not code.strip():
            return 0.1
        score = 0.75
        if "def " in code or "class " in code:
            score += 0.1
        if "try:" in code:
            score += 0.05
        if len([line for line in code.splitlines() if line.strip()]) < 20:
            score -= 0.15
        return max(0.0, min(1.0, score))

    def _extract_run_command(self, readme_text: str) -> str:
        for line in readme_text.splitlines():
            stripped = line.strip()
            if stripped.startswith("python ") or stripped.startswith("npm "):
                return stripped
        return ""

    def _build_next_iteration_goal(self, goal: str, actions: list[str], issues: list[str]) -> str | None:
        if not actions and not issues:
            return None
        focus = actions[:2] or issues[:2]
        return f"Improve the project for this goal: {goal}. Focus on: {'; '.join(focus)}"

    def _has_hard_failure(self, result: EvaluationResult) -> bool:
        hard_markers = ("missing", "syntax error", "placeholder", "no generated project files")
        return any(any(marker in issue.lower() for marker in hard_markers) for issue in result.issues)

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
