"""Dashboard adapter for autonomous iteration progress."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable


class IterationDashboardAdapter:
    """Keep autonomous-iteration UI state outside the main executor."""

    def __init__(self, autopilot: Any, logger: Any | None = None, session_id_getter: Callable[[], str | None] | None = None) -> None:
        self.autopilot = autopilot
        self.logger = logger
        self.session_id_getter = session_id_getter

    @property
    def enhanced_ui(self) -> Any | None:
        return self.autopilot.enhanced_ui

    def finish_active_operations(self, reason: str) -> None:
        tracker = self.autopilot.tracker
        if tracker and hasattr(tracker, "finish_active_operations"):
            tracker.finish_active_operations(success=False, error=reason)
        elif self.enhanced_ui and hasattr(self.enhanced_ui, "set_active_operations"):
            self.enhanced_ui.set_active_operations([])
        self._log("finish_active_operations", {"reason": reason}, {"finished": True})

    def format_iteration_failure(self, improvement_result: dict[str, Any] | None) -> str:
        if not improvement_result:
            return "Autonomous iteration did not return a result."

        completed = improvement_result.get("completed_improvements", 0)
        required = improvement_result.get("required_improvements", self.autopilot.required_successful_improvements)
        failed_iteration = improvement_result.get("failed_iteration")
        stage = improvement_result.get("failure_stage") or "Autonomous Iteration"
        tool = improvement_result.get("failed_tool") or "unknown tool"
        reason = improvement_result.get("failure_reason") or "Project did not complete required improvements."
        remaining_goals = improvement_result.get("remaining_goals") or []

        where = f"Iteration {failed_iteration} · {stage}" if failed_iteration else stage
        message = f"{where} failed in {tool}: {reason} (improvements {completed}/{required})"
        if "retry_attempted" in improvement_result:
            message += f"; retry attempted: {'yes' if improvement_result.get('retry_attempted') else 'no'}"
        retry_history = improvement_result.get("retry_history") or []
        if retry_history:
            modes = [str(item.get("mode") or item.get("step_id") or item.get("attempt")) for item in retry_history]
            message += f"; attempts used: {len(retry_history)} ({', '.join(modes)})"
        if remaining_goals:
            message += f"; remaining goal: {remaining_goals[0]}"
        self._log("format_iteration_failure", {"stage": stage, "tool": tool}, {"message": message})
        return message

    def reset_iteration_dashboard(self, goal: str) -> None:
        self.autopilot._dashboard_iteration_counter = 0
        self.autopilot._dashboard_current_iteration_id = None
        if self.enhanced_ui:
            self.enhanced_ui.set_task_graph_state(goal=goal, tasks=[], current_task_id=None)
        self._log("reset_iteration_dashboard", {"goal": goal}, {"reset": True})

    def ensure_dashboard_iteration(self, iteration_number: int | None = None) -> str:
        current_id = getattr(self.autopilot, "_dashboard_current_iteration_id", None)
        if current_id and self._can_reuse_dashboard_iteration(current_id, iteration_number):
            return current_id

        counter = int(getattr(self.autopilot, "_dashboard_iteration_counter", 0) or 0)
        if iteration_number is not None and iteration_number > counter:
            counter = iteration_number
        else:
            counter += 1
        self.autopilot._dashboard_iteration_counter = counter

        iteration_id = f"iteration_{counter}"
        self.autopilot._dashboard_current_iteration_id = iteration_id
        self.append_dashboard_tasks(
            [
                {
                    "id": iteration_id,
                    "description": f"Iteration {counter}",
                    "status": "running",
                    "kind": "iteration",
                    "children": self.dashboard_iteration_stage_nodes(iteration_id),
                }
            ],
            current_task_id=iteration_id,
        )
        self._log("ensure_dashboard_iteration", {"iteration_number": iteration_number}, {"iteration_id": iteration_id})
        return iteration_id

    def _can_reuse_dashboard_iteration(self, iteration_id: str, iteration_number: int | None = None) -> bool:
        node = self.find_dashboard_node(iteration_id)
        if node and str(node.get("status") or "").lower() in {"completed", "failed", "error", "cancelled"}:
            return False
        if iteration_number is not None and self._iteration_number_from_id(iteration_id) != iteration_number:
            return False
        return True

    def _iteration_number_from_id(self, iteration_id: str | None) -> int | None:
        if not iteration_id:
            return None
        prefix = "iteration_"
        if not iteration_id.startswith(prefix):
            return None
        try:
            return int(iteration_id[len(prefix):].split("_", 1)[0])
        except ValueError:
            return None

    def dashboard_iteration_stage_nodes(self, iteration_id: str) -> list[dict[str, Any]]:
        return [
            {"id": f"{iteration_id}_environment", "description": "Environment Setup", "status": "pending", "kind": "agent"},
            {"id": f"{iteration_id}_project_state", "description": "Read Project State", "status": "pending", "kind": "agent"},
            {"id": f"{iteration_id}_context_loader", "description": "Context Loader", "status": "pending", "kind": "agent"},
            {"id": f"{iteration_id}_diagnosis", "description": "Project Diagnosis", "status": "pending", "kind": "agent"},
            {"id": f"{iteration_id}_goal_maker", "description": "Goal Maker", "status": "pending", "kind": "agent"},
            {"id": f"{iteration_id}_task_designer", "description": "Task Designer", "status": "pending", "kind": "agent"},
            {"id": f"{iteration_id}_decomposition", "description": "Task Decomposer", "status": "pending", "kind": "agent"},
            {"id": f"{iteration_id}_execution", "description": "Task Executor", "status": "pending", "kind": "agent"},
            {"id": f"{iteration_id}_evaluation", "description": "Modification Evaluator", "status": "pending", "kind": "agent"},
            {"id": f"{iteration_id}_mind_system", "description": "Mind System", "status": "pending", "kind": "agent"},
        ]

    def dashboard_stage_id(self, stage_key: str) -> str | None:
        iteration_id = getattr(self.autopilot, "_dashboard_current_iteration_id", None)
        if not iteration_id:
            return None
        return f"{iteration_id}_{stage_key}"

    def short_dashboard_text(self, value: Any, limit: int = 140) -> str:
        text = " ".join(str(value or "").split())
        if len(text) <= limit:
            return text
        return text[: limit - 3] + "..."

    def append_dashboard_stage_child(
        self,
        stage_key: str,
        *,
        child_id: str,
        description: str,
        kind: str,
        status: str = "completed",
        children: list[dict[str, Any]] | None = None,
    ) -> None:
        parent_id = self.dashboard_stage_id(stage_key)
        if not parent_id:
            return
        full_child_id = f"{parent_id}_{child_id}"
        self.append_dashboard_child(
            parent_id=parent_id,
            child={
                "id": full_child_id,
                "description": self.short_dashboard_text(description),
                "status": status,
                "kind": kind,
                **({"children": children} if children else {}),
            },
            current_task_id=full_child_id if status in {"running", "in_progress"} else parent_id,
        )

    def handle_iteration_progress(self, event: str, payload: dict[str, Any]) -> None:
        if not self.enhanced_ui:
            return
        self._log("handle_iteration_progress", {"event": event}, {"handled": True})

        started_stage = {
            "goal_maker_started": ("goal_maker", "Goal Maker", "Selecting improvement goal"),
            "task_designer_started": ("task_designer", "Task Designer", "Designing concrete implementation tasks"),
            "decomposition_started": ("decomposition", "Task Decomposer", "Breaking task into executable subtasks"),
        }.get(event)
        if started_stage is not None:
            stage_key, title, details = started_stage
            self.ensure_dashboard_iteration()
            self.set_dashboard_task_status(self.dashboard_stage_id(stage_key), "running")
            self.enhanced_ui.set_current_task_state(
                title=title,
                details=details,
                status="running",
            )
            return

        if event == "context_loader":
            self.ensure_dashboard_iteration()
            self.set_dashboard_task_status(self.dashboard_stage_id("context_loader"), "completed")
            context = payload.get("context") or payload.get("memory_context") or {}
            self.append_dashboard_stage_child(
                "context_loader",
                child_id=f"context_{payload.get('iteration', 0)}",
                description=(
                    f"memories: {len(context.get('related_memories', []))}; "
                    f"files: {len(context.get('related_files', []))}; "
                    f"environment: {len(context.get('environment_context', []))}"
                ),
                kind="context",
            )
            self.enhanced_ui.set_current_task_state(
                title="Context Loader",
                details="Loaded dialog, memory, project files, and environment context",
                status="completed",
            )
            return

        if event == "project_diagnosis":
            self.ensure_dashboard_iteration()
            self.set_dashboard_task_status(self.dashboard_stage_id("diagnosis"), "completed")
            diagnosis = payload.get("diagnosis")
            selected = payload.get("selected_candidate")
            description = getattr(selected, "title", "") or getattr(diagnosis, "summary", "") or "Diagnosis completed"
            self.append_dashboard_stage_child(
                "diagnosis",
                child_id=f"selected_{payload.get('completed_improvements', 0)}",
                description=description,
                kind="result",
            )
            self.enhanced_ui.set_current_task_state(
                title="Project Diagnosis",
                details=self.short_dashboard_text(description, 500),
                status="completed",
            )
            return

        if event == "project_state":
            self.ensure_dashboard_iteration()
            self.set_dashboard_task_status(self.dashboard_stage_id("project_state"), "completed")
            state = payload["state"]
            safe_targets = ", ".join(Path(path).name for path in state.safe_target_files[:3])
            self.append_dashboard_stage_child(
                "project_state",
                child_id="summary",
                description=(
                    f"Files: {len(state.written_files)}; safe targets: {len(state.safe_target_files)}"
                    + (f" ({safe_targets})" if safe_targets else "")
                    + f"; memories: {len(state.memory_records)}"
                ),
                kind="result",
            )
            self.enhanced_ui.set_current_task_state(
                title="Read Project State",
                details=(
                    f"Files: {len(state.written_files)}\n"
                    f"Safe targets: {len(state.safe_target_files)}\n"
                    f"Memories: {len(state.memory_records)}"
                ),
                status="completed",
            )
            return

        if event == "goal_maker":
            self.ensure_dashboard_iteration()
            self.set_dashboard_task_status(self.dashboard_stage_id("goal_maker"), "completed")
            goal = payload["selected_goal"]
            criteria_children = [
                {
                    "id": f"{self.dashboard_stage_id('goal_maker')}_goal_criteria_{index}",
                    "description": self.short_dashboard_text(criteria),
                    "status": "completed",
                    "kind": "result",
                }
                for index, criteria in enumerate(goal.acceptance_criteria[:4], 1)
            ]
            self.append_dashboard_stage_child(
                "goal_maker",
                child_id=f"selected_goal_{payload.get('iteration', 0)}",
                description=f"{goal.title} [{goal.category}]",
                kind="goal",
                children=criteria_children,
            )
            self.enhanced_ui.set_current_task_state(
                title="Goal Maker",
                details=f"Selected goal: {goal.title}\nCategory: {goal.category}\n" + "\n".join(goal.acceptance_criteria[:3]),
                status="completed",
            )
            return

        if event == "task_designer":
            self.ensure_dashboard_iteration()
            self.set_dashboard_task_status(self.dashboard_stage_id("task_designer"), "completed")
            tasks = payload.get("tasks") or []
            for index, task in enumerate(tasks[:4], 1):
                target_files = ", ".join(Path(path).name for path in task.target_files[:3])
                self.append_dashboard_stage_child(
                    "task_designer",
                    child_id=f"task_{index}",
                    description=task.description + (f" -> {target_files}" if target_files else ""),
                    kind="task",
                )
            details = "\n".join(task.description for task in tasks[:2])
            self.enhanced_ui.set_current_task_state(
                title="Task Designer",
                details=details or "No task details reported",
                status="completed",
            )
            return

        if event == "decomposition":
            self.ensure_dashboard_iteration()
            self.set_dashboard_task_status(self.dashboard_stage_id("decomposition"), "completed")
            tasks = payload.get("tasks") or payload.get("subtasks") or []
            difficulty = payload.get("difficulty") or {}
            for index, task in enumerate(tasks[:4], 1):
                description = getattr(task, "description", str(task))
                self.append_dashboard_stage_child(
                    "decomposition",
                    child_id=f"task_{index}",
                    description=description,
                    kind="task",
                )
            self.enhanced_ui.set_current_task_state(
                title="Task Decomposer",
                details=f"Prepared {len(tasks)} improvement task(s); difficulty: {difficulty.get('level', 'unknown')}",
                status="completed",
            )
            return

        if event == "iteration_started":
            iteration = payload["iteration"]
            iteration_id = self.ensure_dashboard_iteration(iteration)
            self.ensure_pre_execution_stages_completed()
            self.set_dashboard_task_status(iteration_id, "running")
            self.set_dashboard_task_status(self.dashboard_stage_id("execution"), "running")
            self.set_dashboard_task_status(self.dashboard_stage_id("evaluation"), "pending")
            for index, action in enumerate(payload.get("actions", [])[:4], 1):
                self.append_dashboard_stage_child(
                    "execution",
                    child_id=f"action_{index}",
                    description=action,
                    kind="task",
                    status="running",
                )
            self.enhanced_ui.set_current_task_state(
                title=f"Iteration {iteration}",
                details=(
                    f"Improvements applied: {payload.get('completed_improvements', 0)}/"
                    f"{payload.get('required_improvements', self.autopilot.required_successful_improvements)}\n"
                    + "\n".join(payload.get("actions", []))
                ),
                status="running",
            )
            return

        if event == "modification_evaluation_started":
            iteration = payload["iteration"]
            self.ensure_dashboard_iteration(iteration)
            self.set_dashboard_running_descendants_status(self.dashboard_stage_id("execution"), "completed")
            self.set_dashboard_task_status(self.dashboard_stage_id("execution"), "completed")
            self.set_dashboard_task_status(self.dashboard_stage_id("evaluation"), "running")
            self.enhanced_ui.set_current_task_state(
                title="Modification Evaluator",
                details="Running post-change validation and product-fit checks",
                status="running",
            )
            return

        if event == "modification_evaluation":
            self.ensure_dashboard_iteration(payload.get("iteration"))
            evaluation = payload.get("evaluation")
            result = payload.get("result")
            validation_passed = bool(getattr(evaluation, "validation_passed", False))
            completed_successfully = bool(getattr(result, "completed_successful_iteration", False))
            repair_completed = bool(getattr(result, "repair_completed", False))
            status = "completed" if validation_passed and (completed_successfully or repair_completed) else "failed"
            self.set_dashboard_task_status(self.dashboard_stage_id("evaluation"), status)
            summary = getattr(evaluation, "summary", "") or ("Validation passed" if validation_passed else "Validation did not pass")
            issue_summary = payload.get("validation_issue_summary") or self.evaluation_issue_summary(evaluation)
            description = summary
            if status == "failed" and issue_summary:
                description = f"{summary}: {issue_summary}" if issue_summary not in summary else issue_summary
            self.append_dashboard_stage_child(
                "evaluation",
                child_id=f"validation_{payload.get('iteration', 0)}",
                description=self.short_dashboard_text(description, 500),
                kind="result",
                status=status,
            )
            details = description
            if status == "failed":
                target_files = payload.get("target_files") or self.evaluation_target_files(evaluation)
                recommended_actions = payload.get("recommended_actions") or self.evaluation_recommended_actions(evaluation)
                if target_files:
                    details += "\nTarget files: " + ", ".join(str(path) for path in target_files[:3])
                if recommended_actions:
                    details += "\nRecommended action: " + str(recommended_actions[0])
            self.enhanced_ui.set_current_task_state(
                title="Modification Evaluator",
                details=self.short_dashboard_text(details, 800),
                status=status,
            )
            return

        if event == "iteration_failed":
            iteration = payload["iteration"]
            result = payload["result"]
            self.set_dashboard_running_descendants_status(self.dashboard_stage_id("execution"), "failed")
            self.set_dashboard_task_status(self.dashboard_stage_id("execution"), "failed")
            self.set_dashboard_task_status(self.dashboard_stage_id("evaluation"), "pending")
            stage = payload.get("failure_stage") or getattr(result, "failure_stage", None) or "Task Executor"
            tool = payload.get("failed_tool") or getattr(result, "failed_tool", None) or "unknown tool"
            reason = payload.get("failure_reason") or getattr(result, "failure_reason", None) or result.error or "Unknown improvement failure"
            retry_note = "yes" if getattr(result, "retry_attempted", False) else "no"
            self.finish_active_operations(reason)
            iteration_id = getattr(self.autopilot, "_dashboard_current_iteration_id", None)
            if iteration_id:
                self.append_dashboard_child(
                    parent_id=iteration_id,
                    child={
                        "id": f"{iteration_id}_failure",
                        "description": f"{stage} failed in {tool}: {reason}",
                        "status": "failed",
                        "kind": "result",
                    },
                    current_task_id=iteration_id,
                )
                self.set_dashboard_task_status(iteration_id, "failed")
                self.autopilot._dashboard_current_iteration_id = None
            self.enhanced_ui.set_current_task_state(
                title=f"Iteration {iteration} failed",
                details=(
                    f"Iteration: {iteration}\nStage: {stage}\nTool: {tool}\nReason: {reason}\n"
                    f"Retry attempted: {retry_note}\n"
                    f"Improvements applied: {payload.get('completed_improvements', 0)}/"
                    f"{payload.get('required_improvements', self.autopilot.required_successful_improvements)}\n"
                    f"Changed files: {len(result.changed_files)}"
                ),
                status="failed",
            )
            return

        if event == "iteration_completed":
            iteration = payload.get("iteration")
            iteration_id = getattr(self.autopilot, "_dashboard_current_iteration_id", None)
            if not iteration_id and iteration is not None:
                candidate_id = f"iteration_{iteration}"
                if self.find_dashboard_node(candidate_id):
                    iteration_id = candidate_id
            if not iteration_id:
                iteration_id = self.ensure_dashboard_iteration(iteration)
            result = payload.get("result")
            success = bool(getattr(result, "success", False))
            completed_successfully = bool(getattr(result, "completed_successful_iteration", False))
            repair_completed = bool(getattr(result, "repair_completed", False))
            status = "completed" if success and (completed_successfully or repair_completed) else "failed"
            self.set_dashboard_running_descendants_status(iteration_id, status)
            if status == "completed":
                for stage_key in ("execution", "evaluation", "mind_system"):
                    self.set_dashboard_task_status(f"{iteration_id}_{stage_key}", "completed")
            self.set_dashboard_task_status(iteration_id, status)
            self.autopilot._dashboard_current_iteration_id = None
            self.enhanced_ui.set_task_graph_state(
                tasks=self.enhanced_ui.task_graph_state.get("tasks") or [],
                current_task_id=None,
            )
            self.enhanced_ui.set_current_task_state(
                title=f"Iteration {iteration} {'completed' if status == 'completed' else 'stopped'}",
                details=(
                    "Repair completed; project validation passed"
                    if repair_completed
                    else "Iteration completed successfully"
                    if status == "completed"
                    else getattr(result, "failure_reason", None)
                    or self.evaluation_issue_summary(payload.get("evaluation"))
                    or "Iteration finished without satisfying the required improvement"
                ),
                status=status,
            )
            return

        self._handle_generic_event(event, payload)

    def evaluation_issue_summary(self, evaluation: Any) -> str:
        if evaluation is None:
            return ""
        issues = getattr(evaluation, "validation_issues", []) or []
        if issues:
            issue = issues[0]
            message = getattr(issue, "message", "")
            target_files = getattr(issue, "target_files", []) or []
            action = getattr(issue, "recommended_action", "")
            parts = [message]
            if target_files:
                parts.append("target=" + ", ".join(str(path).split("/")[-1] for path in target_files[:3]))
            if action:
                parts.append("action=" + str(action))
            return " | ".join(part for part in parts if part)
        errors = getattr(evaluation, "validation_errors", []) or []
        if errors:
            return str(errors[0])
        return ""

    def evaluation_target_files(self, evaluation: Any) -> list[str]:
        if evaluation is None:
            return []
        targets: list[str] = []
        for issue in getattr(evaluation, "validation_issues", []) or []:
            targets.extend(str(path) for path in (getattr(issue, "target_files", []) or []) if str(path))
        return list(dict.fromkeys(targets))

    def evaluation_recommended_actions(self, evaluation: Any) -> list[str]:
        if evaluation is None:
            return []
        actions = [str(action) for action in (getattr(evaluation, "recommended_actions", []) or []) if str(action)]
        if actions:
            return actions
        for issue in getattr(evaluation, "validation_issues", []) or []:
            action = getattr(issue, "recommended_action", "")
            if action:
                return [str(action)]
        return []

    def append_dashboard_tasks(self, new_tasks: list[dict[str, Any]], current_task_id: str | None = None) -> None:
        if not self.enhanced_ui:
            return
        existing = list(self.enhanced_ui.task_graph_state.get("tasks") or [])
        by_id = {task.get("id"): task for task in existing}
        for task in new_tasks:
            task_id = task.get("id")
            existing_task = by_id.get(task_id, {})
            merged_task = {**existing_task, **task}
            if "children" not in task and existing_task.get("children"):
                merged_task["children"] = existing_task["children"]
            by_id[task_id] = merged_task
        merged = []
        seen = set()
        for task in existing + new_tasks:
            task_id = task.get("id")
            if task_id in seen:
                continue
            merged.append(by_id[task_id])
            seen.add(task_id)
        self.enhanced_ui.set_task_graph_state(tasks=merged, current_task_id=current_task_id)

    def set_dashboard_task_status(self, task_id: str | None, status: str) -> None:
        if not self.enhanced_ui or not task_id:
            return
        tasks, found = self.update_dashboard_node(
            self.enhanced_ui.task_graph_state.get("tasks") or [],
            task_id,
            lambda node: {**node, "status": status},
        )
        if not found:
            return
        current_task_id = self.enhanced_ui.task_graph_state.get("current_task_id")
        if status in {"running", "in_progress", "failed", "error"}:
            current_task_id = task_id
        elif status == "pending" and current_task_id == task_id:
            current_task_id = None
        self.enhanced_ui.set_task_graph_state(tasks=tasks, current_task_id=current_task_id)

    def set_dashboard_running_descendants_status(self, parent_id: str | None, status: str) -> None:
        if not self.enhanced_ui or not parent_id:
            return

        def settle_running(node: dict[str, Any]) -> dict[str, Any]:
            updated = dict(node)
            if (updated.get("status") or "").lower() in {"running", "in_progress"}:
                updated["status"] = status
            children = updated.get("children") or []
            if children:
                updated["children"] = [settle_running(child) for child in children]
            return updated

        def settle_parent(node: dict[str, Any]) -> dict[str, Any]:
            children = node.get("children") or []
            if not children:
                return node
            return {**node, "children": [settle_running(child) for child in children]}

        tasks, found = self.update_dashboard_node(
            self.enhanced_ui.task_graph_state.get("tasks") or [],
            parent_id,
            settle_parent,
        )
        if found:
            self.enhanced_ui.set_task_graph_state(tasks=tasks, current_task_id=parent_id)

    def append_dashboard_child(
        self,
        *,
        parent_id: str,
        child: dict[str, Any],
        current_task_id: str | None = None,
    ) -> None:
        if not self.enhanced_ui or not parent_id:
            return

        def append_child(node: dict[str, Any]) -> dict[str, Any]:
            children = [dict(existing) for existing in node.get("children") or []]
            child_id = child.get("id")
            merged = False
            for index, existing in enumerate(children):
                if existing.get("id") == child_id:
                    merged_child = {**existing, **child}
                    if "children" not in child and existing.get("children"):
                        merged_child["children"] = existing["children"]
                    children[index] = merged_child
                    merged = True
                    break
            if not merged:
                children.append(dict(child))
            return {**node, "children": children}

        tasks, found = self.update_dashboard_node(
            self.enhanced_ui.task_graph_state.get("tasks") or [],
            parent_id,
            append_child,
        )
        if found:
            self.enhanced_ui.set_task_graph_state(tasks=tasks, current_task_id=current_task_id or parent_id)

    def set_dashboard_tool_status(
        self,
        *,
        parent_task_id: str | None,
        tool_id: str,
        tool_name: str,
        status: str,
    ) -> None:
        if not self.enhanced_ui or not parent_task_id:
            return
        self.append_dashboard_child(
            parent_id=parent_task_id,
            child={
                "id": tool_id,
                "description": tool_name,
                "status": status,
                "kind": "tool",
            },
            current_task_id=tool_id if status in {"running", "in_progress"} else parent_task_id,
        )

    def find_dashboard_node(self, node_id: str | None) -> dict[str, Any] | None:
        if not self.enhanced_ui or not node_id:
            return None

        def find(nodes: list[dict[str, Any]]) -> dict[str, Any] | None:
            for node in nodes:
                if node.get("id") == node_id:
                    return node
                child = find(node.get("children") or [])
                if child is not None:
                    return child
            return None

        return find(self.enhanced_ui.task_graph_state.get("tasks") or [])

    def ensure_pre_execution_stages_completed(self) -> None:
        for stage_key in ("goal_maker", "task_designer", "decomposition"):
            stage_id = self.dashboard_stage_id(stage_key)
            node = self.find_dashboard_node(stage_id)
            if not node or node.get("status") != "pending":
                continue
            self.append_dashboard_stage_child(
                stage_key,
                child_id="repair_path_prepared",
                description="Repair path prepared",
                kind="result",
            )
            self.set_dashboard_task_status(stage_id, "completed")

    def update_dashboard_node(
        self,
        nodes: list[dict[str, Any]],
        node_id: str,
        updater: Callable[[dict[str, Any]], dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], bool]:
        updated_nodes = []
        found = False
        for node in nodes:
            updated = dict(node)
            if updated.get("id") == node_id:
                updated = updater(updated)
                found = True
            else:
                children = updated.get("children") or []
                if children:
                    updated_children, child_found = self.update_dashboard_node(children, node_id, updater)
                    if child_found:
                        updated["children"] = updated_children
                        found = True
            updated_nodes.append(updated)
        return updated_nodes, found

    def _handle_generic_event(self, event: str, payload: dict[str, Any]) -> None:
        if event == "successful_improvement":
            self.append_dashboard_stage_child(
                "evaluation",
                child_id="accepted",
                description=f"Improvement accepted: {payload['completed_improvements']}/{payload['required_improvements']}",
                kind="result",
            )
            status = "completed"
            title = "Improvement applied"
        elif event == "repair_completed":
            self.set_dashboard_task_status(self.dashboard_stage_id("evaluation"), "completed")
            self.append_dashboard_stage_child(
                "evaluation",
                child_id=f"repair_completed_{payload.get('iteration', 0)}",
                description="Repair completed; project validation passed.",
                kind="result",
            )
            status = "completed"
            title = "Repair completed"
        elif event == "mind_system":
            self.set_dashboard_task_status(self.dashboard_stage_id("mind_system"), "completed")
            self.append_dashboard_stage_child(
                "mind_system",
                child_id=f"note_{payload.get('iteration', 0)}",
                description=payload.get("note") or "Iteration memory recorded",
                kind="note",
            )
            status = "completed"
            title = "Mind System"
        elif event == "max_attempts_reached":
            self.set_dashboard_running_descendants_status(self.dashboard_stage_id("execution"), "failed")
            status = "warning"
            title = "Max attempts reached"
        else:
            status = "completed"
            title = event.replace("_", " ").title()
        self.enhanced_ui.set_current_task_state(
            title=title,
            details=self.short_dashboard_text(payload.get("summary") or title, 500),
            status=status,
        )

    def _log(self, source_name: str, input_summary: Any, output_summary: Any) -> None:
        if not self.logger or not hasattr(self.logger, "log_structured_event"):
            return
        session_id = self.session_id_getter() if self.session_id_getter else "unknown"
        self.logger.log_structured_event(
            source_type="agent",
            source_name=f"ui.iteration_dashboard.{source_name}",
            phase="iteration_dashboard",
            event_type="agent_completed",
            session_id=session_id or "unknown",
            turn_id=1,
            success=True,
            input_summary=input_summary,
            output_summary=output_summary,
        )
