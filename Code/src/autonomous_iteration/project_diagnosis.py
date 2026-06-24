"""Goal- and metric-driven project diagnosis for autonomous iteration."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from autonomous_iteration.models import EvaluationResult, ProjectStateSnapshot
from metadata import (
    DependencyStrategyMetadata,
    ImprovementCandidateMetadata,
    ProjectDiagnosisMetadata,
    ProjectDimensionAssessmentMetadata,
    ProjectObjectiveMetadata,
    ReferenceInsightMetadata,
    SuccessMetricMetadata,
)


ReferenceProvider = Callable[[str, ProjectStateSnapshot, ProjectObjectiveMetadata], list[Any]]


class ProjectDiagnoser:
    """Build a generic diagnosis and ranked improvement list for software projects."""

    dimensions = (
        "functionality",
        "user_value",
        "user_experience",
        "strategy_design",
        "reliability",
        "technical_scalability",
        "growth_impact",
        "innovation_competitiveness",
    )

    def __init__(
        self,
        *,
        objective_override: ProjectObjectiveMetadata | None = None,
        metric_overrides: list[SuccessMetricMetadata] | None = None,
        preferred_dimensions: list[str] | None = None,
        disallowed_directions: list[str] | None = None,
        allow_reference_search: bool = True,
        reference_provider: ReferenceProvider | None = None,
    ) -> None:
        self.objective_override = objective_override
        self.metric_overrides = metric_overrides or []
        self.preferred_dimensions = {item.strip().lower() for item in preferred_dimensions or [] if item.strip()}
        self.disallowed_directions = [item.strip().lower() for item in disallowed_directions or [] if item.strip()]
        self.allow_reference_search = allow_reference_search
        self.reference_provider = reference_provider

    def diagnose(
        self,
        *,
        project_state: ProjectStateSnapshot,
        evaluation: EvaluationResult,
        iteration: int,
        analysis_seed: dict[str, Any] | None = None,
    ) -> ProjectDiagnosisMetadata:
        objective = self.objective_override or self._infer_objective(project_state)
        metrics = list(self.metric_overrides) or self._infer_metrics(project_state, evaluation, objective)
        assessments = self._assess_dimensions(project_state, evaluation, objective, metrics)
        dependency_strategy = self._build_dependency_strategy(project_state, objective)
        reference_insights = self._local_reference_insights(project_state)
        candidates = self._build_candidates(project_state, evaluation, objective, metrics, assessments, analysis_seed or {}, dependency_strategy)
        if self._should_request_references(objective, candidates, project_state, dependency_strategy) and self.allow_reference_search:
            reference_insights.extend(self._external_reference_insights(project_state, objective, dependency_strategy))
            candidates.extend(self._reference_candidates(reference_insights))
            dependency_strategy = self._enrich_dependency_strategy_with_references(dependency_strategy, reference_insights)
        ranked = self._rank_candidates(candidates)
        selected = ranked[0] if ranked else None
        if selected is not None:
            selected.selected = True
        summary = self._summary(objective, assessments, selected)
        return ProjectDiagnosisMetadata(
            project_path=project_state.project_path,
            iteration=iteration,
            objective=objective,
            success_metrics=metrics,
            dimension_assessments=assessments,
            improvement_candidates=ranked,
            ranked_candidate_ids=[candidate.candidate_id for candidate in ranked],
            selected_candidate=selected,
            reference_insights=reference_insights,
            dependencies=project_state.dependencies,
            dependency_strategy=dependency_strategy,
            stack_preset=project_state.stack_preset,
            summary=summary,
            candidate_shortage_reason="" if selected else "No high-value diagnosis candidate survived constraints.",
            confidence=self._diagnosis_confidence(objective, metrics, ranked, reference_insights),
        )

    def _infer_objective(self, state: ProjectStateSnapshot) -> ProjectObjectiveMetadata:
        text = self._project_text(state)
        project_type = "software_project"
        delivery_surface = "project_native"
        target_users = ["the requester"]
        core_value = ["Satisfy the original project goal with observable software behavior."]
        stack_preset = state.stack_preset
        if self._has_any(text, ("web", "website", "browser", "网页", ".html", "react", "frontend")):
            project_type = "web_app"
            delivery_surface = "browser"
            target_users = ["browser users"]
            core_value = ["Deliver the requested browser workflow clearly and responsively."]
        elif self._has_any(text, ("cli", "command line", "terminal", "命令行", "终端", "argparse", "click.")):
            project_type = "cli_tool"
            delivery_surface = "terminal"
            target_users = ["terminal users"]
            core_value = ["Make the requested command workflow discoverable and reliable."]
        elif self._has_any(text, ("library", "sdk", "package", "module api", "pytest", "__init__.py")):
            project_type = "library"
            delivery_surface = "python_api"
            target_users = ["developers integrating the library"]
            core_value = ["Expose a stable, understandable API that solves the requested problem."]
        elif self._has_any(text, ("csv", "data", "analysis", "report", "pandas", "分析", "数据")):
            project_type = "data_tool"
            delivery_surface = "script_or_report"
            target_users = ["people consuming the generated data result"]
            core_value = ["Produce the requested data transformation or analysis accurately."]
        elif self._has_any(text, ("game", "游戏", "play", "player", "pygame")):
            project_type = "interactive_app"
            delivery_surface = "interactive_runtime"
            target_users = ["people using the interactive software"]
            core_value = ["Provide the requested interactive experience with visible feedback and controls."]
        if stack_preset is not None:
            delivery_surface = stack_preset.delivery_surface or delivery_surface
            if delivery_surface == "browser":
                project_type = "web_app"
                target_users = ["browser users"]
                core_value = ["Deliver the requested browser workflow clearly and responsively."]
            elif delivery_surface == "terminal":
                project_type = "cli_tool"
                target_users = ["terminal users"]
            elif delivery_surface == "interactive_runtime":
                project_type = "interactive_app"
                target_users = ["people using the interactive software"]
        success = [
            "Core behavior from the user goal is present and testable.",
            "The documented run path works without blocking runtime failures.",
            "The next improvement has user or maintainer value beyond low-signal polish.",
        ]
        evidence = [f"goal:{state.goal[:220]}"]
        if state.readme_summary:
            evidence.append(f"readme:{state.readme_summary[:220]}")
        if state.module_summaries:
            evidence.append("modules:" + "; ".join(state.module_summaries[:4]))
        if stack_preset is not None:
            evidence.append(
                f"stack_preset:r{stack_preset.revision} {stack_preset.architecture} "
                f"frontend={stack_preset.frontend_language} backend={stack_preset.backend_language}"
            )
        confidence = 0.78 if project_type != "software_project" else (0.64 if state.readme_summary or state.file_summaries else 0.48)
        return ProjectObjectiveMetadata(
            goal=state.goal,
            project_type=project_type,
            target_users=target_users,
            delivery_surface=delivery_surface,
            core_value=core_value,
            success_definition=success,
            evidence=evidence,
            confidence=confidence,
        )

    def _infer_metrics(
        self,
        state: ProjectStateSnapshot,
        evaluation: EvaluationResult,
        objective: ProjectObjectiveMetadata,
    ) -> list[SuccessMetricMetadata]:
        runtime_evidence = evaluation.validation_errors[:3] or [evaluation.summary]
        metrics = [
            SuccessMetricMetadata(
                metric_id="runtime_ready",
                name="Runnable delivery",
                dimension="reliability",
                target="Documented run path passes hard validation.",
                current_assessment="passed" if evaluation.validation_passed else "blocked",
                evidence=runtime_evidence,
                confidence=0.94,
                required=True,
                satisfied=evaluation.validation_passed,
            ),
            SuccessMetricMetadata(
                metric_id="core_goal_delivery",
                name="Core goal delivery",
                dimension="functionality",
                target=objective.success_definition[0] if objective.success_definition else "Original goal is observable.",
                current_assessment="Needs diagnosis against project state." if evaluation.validation_passed else "Blocked by validation.",
                evidence=[state.goal[:220], *(state.module_summaries[:3] or [])],
                confidence=objective.confidence,
                required=True,
                satisfied=None if evaluation.validation_passed else False,
            ),
            SuccessMetricMetadata(
                metric_id="usable_delivery",
                name="User-facing usability",
                dimension="user_experience",
                target="Primary workflow is understandable with useful feedback.",
                current_assessment="README and project state need UX review.",
                evidence=[state.readme_summary[:220]] if state.readme_summary else ["No README evidence provided."],
                confidence=0.68 if objective.project_type != "software_project" else 0.52,
                required=bool(
                    objective.project_type in {"web_app", "cli_tool", "interactive_app"}
                    or (state.stack_preset and state.stack_preset.ui_review_required)
                ),
            ),
            SuccessMetricMetadata(
                metric_id="maintainable_change",
                name="Maintainable evolution",
                dimension="technical_scalability",
                target="Changes stay modular enough for the next iteration.",
                current_assessment=f"{len(state.safe_target_files)} safe implementation target(s) available.",
                evidence=state.module_summaries[:4],
                confidence=0.58,
                required=False,
            ),
        ]
        if objective.project_type in {"library", "data_tool"}:
            metrics.append(
                SuccessMetricMetadata(
                    metric_id="consumer_contract",
                    name="Consumer contract clarity",
                    dimension="user_value",
                    target="Inputs, outputs, and expected usage are clear for consumers.",
                    current_assessment="Check API/data contract evidence in docs and files.",
                    evidence=[state.readme_summary[:220]] if state.readme_summary else state.module_summaries[:3],
                    confidence=0.62,
                    required=True,
                )
            )
        return metrics

    def _assess_dimensions(
        self,
        state: ProjectStateSnapshot,
        evaluation: EvaluationResult,
        objective: ProjectObjectiveMetadata,
        metrics: list[SuccessMetricMetadata],
    ) -> list[ProjectDimensionAssessmentMetadata]:
        has_readme = bool(state.readme_summary.strip())
        warnings = list(evaluation.warnings[:3])
        validation_gap = evaluation.validation_errors[:3]
        assessment_map: dict[str, ProjectDimensionAssessmentMetadata] = {}
        for dimension in self.dimensions:
            score = 0.62 if evaluation.validation_passed else 0.36
            gaps: list[str] = []
            evidence = [metric.current_assessment for metric in metrics if metric.dimension == dimension][:3]
            risks: list[str] = []
            if dimension == "reliability":
                score = 0.86 if evaluation.validation_passed else 0.12
                gaps.extend(validation_gap)
                risks.extend(validation_gap)
                evidence.extend(state.runtime_evidence[:3])
            elif dimension == "functionality":
                gaps.extend(evaluation.improvement_opportunities[:2])
                evidence.extend(state.module_summaries[:3])
            elif dimension == "user_experience":
                score -= 0.12 if objective.project_type in {"interactive_app", "web_app", "cli_tool"} else 0.0
                gaps.extend(warnings[:2])
                ui_gap = self._ui_surface_gap(state)
                if ui_gap:
                    score -= 0.2
                    gaps.append(ui_gap)
            elif dimension == "technical_scalability":
                evidence.extend(state.module_summaries[:3])
                if len(state.safe_target_files) <= 1:
                    gaps.append("Project structure has limited modularity evidence for future changes.")
            elif dimension == "growth_impact":
                score = 0.45
                gaps.append("Growth, reuse, or adoption evidence is not yet explicit.")
            elif dimension == "innovation_competitiveness":
                score = 0.42
                gaps.append("Differentiation is not yet supported by project evidence.")
            elif dimension == "strategy_design":
                if not has_readme:
                    gaps.append("Strategy and run intent are weakly documented.")
            elif dimension == "user_value":
                evidence.extend(objective.core_value[:2])
            if dimension in {"user_value", "strategy_design"} and not has_readme:
                score -= 0.08
            score = self._bound(score)
            assessment_map[dimension] = ProjectDimensionAssessmentMetadata(
                dimension=dimension,
                score=score,
                summary=f"{dimension.replace('_', ' ').title()} score derived from objective and project evidence.",
                gaps=self._dedupe(gaps),
                evidence=self._dedupe(evidence),
                risks=self._dedupe(risks),
            )
        return list(assessment_map.values())

    def _build_candidates(
        self,
        state: ProjectStateSnapshot,
        evaluation: EvaluationResult,
        objective: ProjectObjectiveMetadata,
        metrics: list[SuccessMetricMetadata],
        assessments: list[ProjectDimensionAssessmentMetadata],
        seed: dict[str, Any],
        dependency_strategy: DependencyStrategyMetadata | None,
    ) -> list[ImprovementCandidateMetadata]:
        if evaluation.has_blocking_bugs or not evaluation.validation_passed:
            return [self._repair_candidate(evaluation)]
        candidates: list[ImprovementCandidateMetadata] = []
        ui_gap = self._ui_surface_gap(state)
        if ui_gap and state.stack_preset is not None:
            candidates.append(
                self._candidate(
                    candidate_id="ui_surface_completion",
                    title=f"Implement the planned {state.stack_preset.ui_strategy} user interface",
                    dimension="user_experience",
                    rationale=ui_gap,
                    criteria=[
                        f"The project exposes its planned {state.stack_preset.delivery_surface} user-facing surface.",
                        "New or existing user-facing capabilities are reachable through coherent UI controls and visible states.",
                        "UI files and backend behavior follow the persisted project stack preset.",
                    ],
                    evidence=[ui_gap, *state.stack_preset.rationale[:2]],
                    candidate_type="ui_surface",
                    value=0.94,
                    impact=0.92,
                    difficulty=0.58,
                    risk=0.3,
                )
            )
        preserve_packages = list(dependency_strategy.preserve_packages if dependency_strategy else [])
        if preserve_packages:
            package_text = ", ".join(preserve_packages[:4])
            candidates.append(
                self._candidate(
                    candidate_id="dependency_preserving_enhancement",
                    title=f"Improve the project using existing dependency capabilities ({package_text})",
                    dimension="technical_scalability",
                    rationale="Existing third-party libraries are project capability evidence and should be preserved during iteration.",
                    criteria=[
                        f"Existing useful packages remain imported or intentionally used: {package_text}.",
                        "The improvement does not replace an existing delivery surface with a lower-capability substitute.",
                    ],
                    evidence=(dependency_strategy.rationale[:4] if dependency_strategy else []),
                    candidate_type="dependency_strategy",
                    value=0.72,
                    impact=0.7,
                    difficulty=0.42,
                    risk=0.25,
                )
            )
        seed_actions = self._text_list(seed.get("recommended_actions"))
        seed_goals = self._text_list(seed.get("must_implement_next"))
        seed_opportunities = self._text_list(seed.get("improvement_opportunities")) or evaluation.improvement_opportunities
        for index, action in enumerate(self._dedupe([*seed_actions, *evaluation.recommended_actions])[:3], 1):
            candidates.append(
                self._candidate(
                    candidate_id=f"seed_action_{index}",
                    title=action,
                    dimension=self._dimension_for_text(action),
                    rationale=str(seed.get("summary") or evaluation.summary),
                    criteria=seed_goals[:3] or [f"Observable improvement delivered: {action}"],
                    evidence=[*seed_opportunities[:2], evaluation.summary],
                    candidate_type="enhancement",
                    value=0.78,
                    impact=0.72,
                    difficulty=0.45,
                )
            )
        for assessment in sorted(assessments, key=lambda item: item.score)[:4]:
            if not assessment.gaps:
                continue
            candidates.append(
                self._candidate(
                    candidate_id=f"gap_{assessment.dimension}",
                    title=self._gap_title(assessment.dimension, objective),
                    dimension=assessment.dimension,
                    rationale=assessment.gaps[0],
                    criteria=[self._gap_criterion(assessment.dimension, objective)],
                    evidence=[*assessment.gaps[:2], *assessment.evidence[:2]],
                    candidate_type="diagnosis_gap",
                    value=0.74 if assessment.dimension in {"functionality", "user_experience", "user_value"} else 0.6,
                    impact=1.0 - assessment.score,
                    difficulty=0.52,
                )
            )
        if not state.readme_summary.strip():
            candidates.append(
                self._candidate(
                    candidate_id="documentation_run_contract",
                    title="Clarify project setup, run path, and user contract",
                    dimension="strategy_design",
                    rationale="Project state has little README evidence for consumers.",
                    criteria=["README explains setup, run command, and the primary workflow."],
                    evidence=["README summary is empty."],
                    candidate_type="documentation",
                    value=0.55,
                    impact=0.5,
                    difficulty=0.25,
                )
            )
        return self._dedupe_candidates(candidates)

    def _repair_candidate(self, evaluation: EvaluationResult) -> ImprovementCandidateMetadata:
        issue = next(iter(evaluation.validation_issues), None)
        title = (
            getattr(issue, "recommended_action", "")
            or evaluation.next_iteration_goal
            or (evaluation.recommended_actions[0] if evaluation.recommended_actions else "")
            or "Repair the blocking validation issue."
        )
        criteria = [getattr(issue, "message", "")] if issue is not None else evaluation.validation_errors[:2]
        return self._candidate(
            candidate_id="blocking_validation_repair",
            title=title,
            dimension="reliability",
            rationale=evaluation.summary,
            criteria=[item for item in criteria if item] or ["Hard validation passes while project intent is preserved."],
            evidence=[*evaluation.validation_errors[:3], *evaluation.warnings[:2]],
            candidate_type="repair",
            value=1.0,
            impact=1.0,
            difficulty=0.5,
            risk=0.32,
        )

    def _rank_candidates(self, candidates: list[ImprovementCandidateMetadata]) -> list[ImprovementCandidateMetadata]:
        ranked: list[ImprovementCandidateMetadata] = []
        for candidate in self._dedupe_candidates(candidates):
            lowered = f"{candidate.title} {candidate.rationale}".lower()
            if any(direction in lowered for direction in self.disallowed_directions):
                continue
            priority = (
                candidate.value_score * 0.35
                + candidate.impact_score * 0.25
                + candidate.evidence_score * 0.2
                - candidate.difficulty_score * 0.1
                - candidate.risk_score * 0.1
            )
            if candidate.dimension.lower() in self.preferred_dimensions:
                priority += 0.1
            if candidate.candidate_type == "repair":
                priority += 0.25
            candidate.priority_score = self._bound(priority)
            ranked.append(candidate)
        return sorted(ranked, key=lambda item: item.priority_score, reverse=True)

    def _candidate(
        self,
        *,
        candidate_id: str,
        title: str,
        dimension: str,
        rationale: str,
        criteria: list[str],
        evidence: list[str],
        candidate_type: str,
        value: float,
        impact: float,
        difficulty: float,
        risk: float = 0.35,
    ) -> ImprovementCandidateMetadata:
        return ImprovementCandidateMetadata(
            candidate_id=candidate_id,
            title=title,
            dimension=dimension,
            rationale=rationale,
            acceptance_criteria=self._dedupe(criteria),
            target_metrics=[metric for metric in ("core_goal_delivery", "usable_delivery") if dimension in {"functionality", "user_value", "user_experience"}],
            evidence=self._dedupe(evidence),
            value_score=self._bound(value),
            impact_score=self._bound(impact),
            difficulty_score=self._bound(difficulty),
            risk_score=self._bound(risk),
            evidence_score=self._bound(0.4 + min(0.45, len([item for item in evidence if item]) * 0.12)),
            candidate_type=candidate_type,
        )

    def _local_reference_insights(self, state: ProjectStateSnapshot) -> list[ReferenceInsightMetadata]:
        insights = []
        for record in state.memory_records:
            tags = [str(item).lower() for item in record.get("tags") or []]
            record_type = str(record.get("type") or "").lower()
            if record_type != "reference" and "reference" not in tags and "best_practice" not in tags:
                continue
            content = str(record.get("content") or "").strip()
            if not content:
                continue
            insights.append(
                ReferenceInsightMetadata(
                    summary=content[:500],
                    best_practices=[content[:220]],
                    applicability="local_memory",
                    source_notes=[str(record.get("id") or "memory_reference")],
                    confidence=float(record.get("confidence") or 0.55),
                )
            )
        return insights[:3]

    def _build_dependency_strategy(
        self,
        state: ProjectStateSnapshot,
        objective: ProjectObjectiveMetadata,
    ) -> DependencyStrategyMetadata:
        if state.dependency_strategy is not None:
            return state.dependency_strategy
        preserve = []
        recommended = []
        rationale = []
        for dependency in state.dependencies:
            if dependency.role or dependency.import_names or "installed" in dependency.dependency_sources:
                preserve.append(dependency.package_name)
                role_text = f" ({dependency.role})" if dependency.role else ""
                rationale.append(f"Preserve {dependency.package_name}{role_text}; it is current project capability evidence.")
        if objective.project_type == "interactive_app" and not any(dep.role for dep in state.dependencies):
            recommended.append("pygame")
            rationale.append("Interactive projects benefit from a dedicated input/rendering/game-loop library when no equivalent dependency exists.")
        return DependencyStrategyMetadata(
            preserve_packages=self._dedupe(preserve),
            recommended_packages=self._dedupe(recommended),
            replaceable_packages=[],
            rejected_removals=[],
            rationale=self._dedupe(rationale),
            confidence=0.82 if preserve else 0.55,
        )

    def _enrich_dependency_strategy_with_references(
        self,
        strategy: DependencyStrategyMetadata,
        insights: list[ReferenceInsightMetadata],
    ) -> DependencyStrategyMetadata:
        queries = [insight.query for insight in insights if insight.query]
        if not queries:
            return strategy
        return strategy.model_copy(update={"reference_queries": self._dedupe([*strategy.reference_queries, *queries])})

    def _external_reference_insights(
        self,
        state: ProjectStateSnapshot,
        objective: ProjectObjectiveMetadata,
        dependency_strategy: DependencyStrategyMetadata | None = None,
    ) -> list[ReferenceInsightMetadata]:
        if self.reference_provider is None:
            return []
        packages = []
        if dependency_strategy is not None:
            packages = dependency_strategy.preserve_packages or dependency_strategy.recommended_packages
        dependency_hint = f" using {' '.join(packages[:4])}" if packages else ""
        query = f"{objective.project_type} best practices for {state.goal}{dependency_hint}".strip()
        try:
            raw_insights = self.reference_provider(query, state, objective)
        except Exception:
            return []
        insights = []
        for item in raw_insights or []:
            if isinstance(item, ReferenceInsightMetadata):
                insights.append(item)
            elif isinstance(item, dict):
                insights.append(ReferenceInsightMetadata.model_validate(item))
        return insights[:3]

    def _reference_candidates(self, insights: list[ReferenceInsightMetadata]) -> list[ImprovementCandidateMetadata]:
        candidates = []
        for index, insight in enumerate(insights[:2], 1):
            if not insight.best_practices:
                continue
            practice = insight.best_practices[0]
            candidates.append(
                self._candidate(
                    candidate_id=f"reference_{index}",
                    title=f"Apply relevant reference guidance: {practice[:140]}",
                    dimension="strategy_design",
                    rationale=insight.summary or "Reference insight suggests a useful gap.",
                    criteria=[f"Project visibly reflects the applicable practice: {practice[:180]}"],
                    evidence=[*insight.gap_evidence[:2], *insight.source_notes[:2]],
                    candidate_type="reference",
                    value=0.58,
                    impact=0.55,
                    difficulty=0.5,
                    risk=0.42,
                )
            )
        return candidates

    def _should_request_references(
        self,
        objective: ProjectObjectiveMetadata,
        candidates: list[ImprovementCandidateMetadata],
        state: ProjectStateSnapshot,
        dependency_strategy: DependencyStrategyMetadata | None = None,
    ) -> bool:
        candidate_titles = {candidate.title.lower() for candidate in candidates}
        memory_titles = {
            str(record.get("attributes", {}).get("selected_candidate") or "").lower()
            for record in state.memory_records
            if isinstance(record.get("attributes"), dict)
        }
        repeated = bool(candidate_titles & {item for item in memory_titles if item})
        dependency_needs_reference = bool(
            dependency_strategy
            and (
                dependency_strategy.recommended_packages
                or (state.dependencies and objective.project_type in {"interactive_app", "web_app"} and not dependency_strategy.reference_queries)
            )
        )
        return objective.confidence < 0.65 or len(candidates) < 2 or repeated or dependency_needs_reference

    def _gap_title(self, dimension: str, objective: ProjectObjectiveMetadata) -> str:
        labels = {
            "functionality": "Close the highest-value core behavior gap",
            "user_value": "Make the primary user value clearer and more complete",
            "user_experience": "Improve the primary workflow feedback and usability",
            "strategy_design": "Clarify product flow and run intent",
            "reliability": "Strengthen runtime robustness for the documented workflow",
            "technical_scalability": "Reduce the next-change maintenance bottleneck",
            "growth_impact": "Add one reusable or adoptable project affordance",
            "innovation_competitiveness": "Add one evidence-backed differentiating improvement",
        }
        return f"{labels.get(dimension, 'Improve the diagnosed project gap')} for {objective.project_type}"

    def _gap_criterion(self, dimension: str, objective: ProjectObjectiveMetadata) -> str:
        return f"The {dimension.replace('_', ' ')} gap is addressed with observable evidence for {objective.project_type}."

    def _dimension_for_text(self, text: str) -> str:
        lowered = text.lower()
        if self._has_any(lowered, ("error", "bug", "warning", "runtime", "failure", "robust")):
            return "reliability"
        if self._has_any(lowered, ("readme", "setup", "run command", "document", "install")):
            return "strategy_design"
        if self._has_any(lowered, ("ux", "user", "control", "feedback", "workflow", "screen", "view")):
            return "user_experience"
        if self._has_any(lowered, ("refactor", "module", "test", "maintain", "architecture")):
            return "technical_scalability"
        return "functionality"

    def _summary(
        self,
        objective: ProjectObjectiveMetadata,
        assessments: list[ProjectDimensionAssessmentMetadata],
        selected: ImprovementCandidateMetadata | None,
    ) -> str:
        weakest = sorted(assessments, key=lambda item: item.score)[:2]
        weak_text = ", ".join(item.dimension for item in weakest)
        if selected is None:
            return f"Diagnosis found no eligible next candidate for {objective.project_type}; weakest dimensions: {weak_text}."
        return f"Diagnosis selected '{selected.title}' for {objective.project_type}; weakest dimensions: {weak_text}."

    def _diagnosis_confidence(
        self,
        objective: ProjectObjectiveMetadata,
        metrics: list[SuccessMetricMetadata],
        candidates: list[ImprovementCandidateMetadata],
        references: list[ReferenceInsightMetadata],
    ) -> float:
        metric_confidence = sum(metric.confidence for metric in metrics) / max(1, len(metrics))
        evidence_boost = 0.08 if candidates else -0.12
        reference_boost = 0.05 if references else 0.0
        return self._bound(objective.confidence * 0.45 + metric_confidence * 0.45 + evidence_boost + reference_boost)

    def _project_text(self, state: ProjectStateSnapshot) -> str:
        chunks = [state.goal, state.readme_summary]
        chunks.extend(str(item.get("name") or "") + " " + str(item.get("preview") or "") for item in state.file_summaries[:4])
        chunks.extend(state.module_summaries[:4])
        chunks.extend(f"{dependency.package_name} {dependency.role}" for dependency in state.dependencies[:8])
        return "\n".join(chunks).lower()

    def _ui_surface_gap(self, state: ProjectStateSnapshot) -> str:
        preset = state.stack_preset
        if preset is None or not preset.ui_review_required:
            return ""
        file_text = "\n".join(
            f"{item.get('name', '')} {item.get('suffix', '')} {item.get('preview', '')}"
            for item in state.file_summaries
        ).lower()
        if preset.delivery_surface == "browser" and not self._has_any(
            file_text,
            (".html", ".css", ".js", ".jsx", ".ts", ".tsx", "<html", "react", "vue", "svelte"),
        ):
            return "The persisted browser UI preset has no frontend file evidence yet."
        if preset.delivery_surface == "interactive_runtime" and not self._has_any(
            file_text,
            ("pygame", "tkinter", "canvas", "window", "render", "draw"),
        ):
            return "The persisted interactive UI preset has no visible rendering or window evidence yet."
        return ""

    @staticmethod
    def _has_any(text: str, terms: tuple[str, ...]) -> bool:
        return any(term in text for term in terms)

    @staticmethod
    def _text_list(value: Any) -> list[str]:
        if isinstance(value, str):
            return [value] if value.strip() else []
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        return []

    def _dedupe_candidates(self, candidates: list[ImprovementCandidateMetadata]) -> list[ImprovementCandidateMetadata]:
        seen = set()
        result = []
        for candidate in candidates:
            key = candidate.title.strip().lower()
            if not key or key in seen:
                continue
            result.append(candidate)
            seen.add(key)
        return result

    @staticmethod
    def _dedupe(items: list[str]) -> list[str]:
        seen = set()
        result = []
        for item in items:
            text = str(item or "").strip()
            if text and text not in seen:
                result.append(text)
                seen.add(text)
        return result

    @staticmethod
    def _bound(value: float) -> float:
        return max(0.0, min(1.0, round(float(value), 4)))
