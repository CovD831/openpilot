"""Task decomposition agent for breaking down complex tasks."""

from __future__ import annotations

import uuid
from typing import Any

from core.graph import Graph, GraphNode, GraphEdge, GraphType
from core.llm import LLMClient, LLMMessage, LLMRequest
from models.task_models import (
    Task,
    TaskStatus,
    TaskPriority,
    TaskDecompositionRequest,
    TaskDecompositionResult
)


class TaskDecomposer:
    """Agent for decomposing complex tasks into subtasks."""

    def __init__(
        self,
        llm_client: LLMClient,
        max_decomposition_depth: int = 3,
        min_subtask_complexity: float = 0.1
    ):
        """Initialize task decomposer.

        Args:
            llm_client: LLM client for task analysis
            max_decomposition_depth: Maximum decomposition depth
            min_subtask_complexity: Minimum complexity to decompose further
        """
        self.llm_client = llm_client
        self.max_decomposition_depth = max_decomposition_depth
        self.min_subtask_complexity = min_subtask_complexity

    def should_decompose(self, task: Task, current_depth: int = 0) -> bool:
        """Determine if a task should be decomposed.

        Args:
            task: Task to analyze
            current_depth: Current decomposition depth

        Returns:
            True if task should be decomposed
        """
        # Don't decompose if max depth reached
        if current_depth >= self.max_decomposition_depth:
            return False

        # Don't decompose if already has subtasks
        if task.metadata.get("has_subtasks"):
            return False

        # Use LLM to analyze task complexity
        complexity = self._estimate_complexity(task)

        return complexity > self.min_subtask_complexity

    def decompose(
        self,
        task_description: str,
        context: dict[str, Any] | None = None,
        parent_task_id: str | None = None
    ) -> TaskDecompositionResult:
        """Decompose a task into subtasks.

        Args:
            task_description: Description of the task
            context: Optional context information
            parent_task_id: Optional parent task ID

        Returns:
            TaskDecompositionResult with subtasks and task graph
        """
        context = context or {}

        # Create original task
        original_task = Task(
            id=str(uuid.uuid4()),
            description=task_description,
            parent_id=parent_task_id,
            metadata={"context": context}
        )

        # Analyze task and generate decomposition
        decomposition = self._generate_decomposition(original_task, context)

        # Create subtasks
        subtasks = []
        task_graph = Graph(GraphType.DIRECTED)

        # Add original task to graph
        task_graph.add_node(GraphNode(
            id=original_task.id,
            type="task",
            data={"description": original_task.description, "is_root": True}
        ))

        for subtask_desc in decomposition["subtasks"]:
            subtask = Task(
                id=str(uuid.uuid4()),
                description=subtask_desc["description"],
                parent_id=original_task.id,
                priority=TaskPriority(subtask_desc.get("priority", "medium")),
                estimated_effort=subtask_desc.get("estimated_effort"),
                dependencies=subtask_desc.get("dependencies", []),
                tags=subtask_desc.get("tags", [])
            )
            subtasks.append(subtask)

            # Add to graph
            task_graph.add_node(GraphNode(
                id=subtask.id,
                type="subtask",
                data={
                    "description": subtask.description,
                    "priority": subtask.priority.value,
                    "estimated_effort": subtask.estimated_effort
                }
            ))

            # Add edge from parent to subtask
            task_graph.add_edge(GraphEdge(
                source_id=original_task.id,
                target_id=subtask.id,
                edge_type="has_subtask"
            ))

        # Add dependency edges
        for subtask in subtasks:
            for dep_id in subtask.dependencies:
                # Find dependency by description (simplified)
                dep_task = next((t for t in subtasks if t.id == dep_id), None)
                if dep_task:
                    task_graph.add_edge(GraphEdge(
                        source_id=dep_task.id,
                        target_id=subtask.id,
                        edge_type="depends_on"
                    ))

        # Calculate total effort
        total_effort = sum(
            t.estimated_effort for t in subtasks
            if t.estimated_effort is not None
        )

        # Generate task graph summary
        graph_summary = self._generate_graph_summary(task_graph, subtasks)

        return TaskDecompositionResult(
            original_task=original_task,
            subtasks=subtasks,
            task_graph_summary=graph_summary,
            decomposition_rationale=decomposition.get("rationale", ""),
            estimated_total_effort=total_effort
        )

    def build_task_graph(self, tasks: list[Task]) -> Graph:
        """Build a task dependency graph.

        Args:
            tasks: List of tasks

        Returns:
            Graph representing task dependencies
        """
        graph = Graph(GraphType.DIRECTED)

        # Add all tasks as nodes
        for task in tasks:
            graph.add_node(GraphNode(
                id=task.id,
                type="task",
                data={
                    "description": task.description,
                    "status": task.status.value,
                    "priority": task.priority.value,
                    "estimated_effort": task.estimated_effort
                }
            ))

        # Add dependency edges
        for task in tasks:
            for dep_id in task.dependencies:
                if graph.has_node(dep_id):
                    graph.add_edge(GraphEdge(
                        source_id=dep_id,
                        target_id=task.id,
                        edge_type="blocks"
                    ))

        return graph

    def get_execution_order(self, task_graph: Graph) -> list[str]:
        """Get execution order for tasks using topological sort.

        Args:
            task_graph: Task dependency graph

        Returns:
            List of task IDs in execution order

        Raises:
            ValueError: If graph contains cycles
        """
        try:
            sorted_nodes = task_graph.topological_sort()
            return [node.id for node in sorted_nodes]
        except ValueError as e:
            raise ValueError(f"Cannot determine execution order: {e}") from e

    def get_ready_tasks(self, tasks: list[Task]) -> list[Task]:
        """Get tasks that are ready to execute.

        Args:
            tasks: List of tasks

        Returns:
            List of tasks with all dependencies completed
        """
        completed_ids = {t.id for t in tasks if t.status == TaskStatus.COMPLETED}

        ready_tasks = []
        for task in tasks:
            if task.is_ready(completed_ids):
                ready_tasks.append(task)

        return ready_tasks

    def assemble_results(self, parent_task: Task, subtasks: list[Task]) -> Any:
        """Assemble results from subtasks.

        Args:
            parent_task: Parent task
            subtasks: Completed subtasks

        Returns:
            Assembled result
        """
        # Check if all subtasks are completed
        if not all(t.status == TaskStatus.COMPLETED for t in subtasks):
            incomplete = [t for t in subtasks if t.status != TaskStatus.COMPLETED]
            raise ValueError(f"Cannot assemble: {len(incomplete)} subtasks incomplete")

        # Collect results
        results = {
            "parent_task_id": parent_task.id,
            "parent_description": parent_task.description,
            "subtask_results": [
                {
                    "task_id": t.id,
                    "description": t.description,
                    "result": t.result,
                    "duration": t.get_duration()
                }
                for t in subtasks
            ],
            "total_subtasks": len(subtasks),
            "successful_subtasks": len([t for t in subtasks if t.status == TaskStatus.COMPLETED])
        }

        return results

    def _estimate_complexity(self, task: Task) -> float:
        """Estimate task complexity using LLM.

        Args:
            task: Task to analyze

        Returns:
            Complexity score (0.0 to 1.0)
        """
        prompt = f"""Analyze the complexity of this task and rate it from 0.0 (trivial) to 1.0 (very complex).

Task: {task.description}

Consider:
- Number of steps required
- Technical difficulty
- Dependencies on other systems
- Potential for errors

Respond with just a number between 0.0 and 1.0."""

        try:
            request = LLMRequest(
                messages=[LLMMessage(role="user", content=prompt)],
                temperature=0.3,
                max_tokens=10
            )

            response = self.llm_client.complete(request)
            complexity_str = response.content.strip()

            # Parse complexity
            complexity = float(complexity_str)
            return max(0.0, min(1.0, complexity))

        except Exception:
            # Default to medium complexity if LLM fails
            return 0.5

    def _generate_decomposition(self, task: Task, context: dict[str, Any]) -> dict[str, Any]:
        """Generate task decomposition using LLM.

        Args:
            task: Task to decompose
            context: Context information

        Returns:
            Dictionary with subtasks and rationale
        """
        context_str = "\n".join(f"- {k}: {v}" for k, v in context.items()) if context else "None"

        prompt = f"""Decompose this task into subtasks.

Task: {task.description}

Context:
{context_str}

Provide a JSON response with:
{{
    "rationale": "Why this decomposition makes sense",
    "subtasks": [
        {{
            "description": "Subtask description",
            "priority": "low|medium|high|critical",
            "estimated_effort": 1.0,
            "dependencies": [],
            "tags": []
        }}
    ]
}}

Guidelines:
- Create 2-7 subtasks
- Each subtask should be independently executable
- Identify dependencies between subtasks
- Estimate effort (1.0 = 1 unit of work)
- Keep descriptions clear and actionable"""

        try:
            request = LLMRequest(
                messages=[LLMMessage(role="user", content=prompt)],
                response_format="json_object",
                temperature=0.5,
                max_tokens=2000
            )

            response = self.llm_client.complete(request)

            # Parse JSON response
            if response.parsed_json:
                return response.parsed_json

            # Fallback parsing
            import json
            return json.loads(response.content)

        except Exception as e:
            # Fallback to simple decomposition
            return self._fallback_decomposition(task)

    def _fallback_decomposition(self, task: Task) -> dict[str, Any]:
        """Generate simple fallback decomposition.

        Args:
            task: Task to decompose

        Returns:
            Simple decomposition
        """
        return {
            "rationale": "Automatic decomposition (LLM unavailable)",
            "subtasks": [
                {
                    "description": f"Analyze requirements for: {task.description}",
                    "priority": "high",
                    "estimated_effort": 1.0,
                    "dependencies": [],
                    "tags": ["analysis"]
                },
                {
                    "description": f"Implement: {task.description}",
                    "priority": "high",
                    "estimated_effort": 3.0,
                    "dependencies": [],
                    "tags": ["implementation"]
                },
                {
                    "description": f"Test: {task.description}",
                    "priority": "medium",
                    "estimated_effort": 1.0,
                    "dependencies": [],
                    "tags": ["testing"]
                }
            ]
        }

    def _generate_graph_summary(self, graph: Graph, tasks: list[Task]) -> str:
        """Generate summary of task graph.

        Args:
            graph: Task graph
            tasks: List of tasks

        Returns:
            Summary text
        """
        lines = [
            f"Task Graph Summary:",
            f"- Total tasks: {len(tasks)}",
            f"- Total nodes: {graph.node_count()}",
            f"- Total edges: {graph.edge_count()}",
        ]

        # Count by priority
        by_priority = {}
        for task in tasks:
            priority = task.priority.value
            by_priority[priority] = by_priority.get(priority, 0) + 1

        lines.append("\nBy Priority:")
        for priority, count in sorted(by_priority.items()):
            lines.append(f"  - {priority}: {count}")

        # Identify tasks with no dependencies (can start immediately)
        ready_tasks = [t for t in tasks if not t.dependencies]
        lines.append(f"\nReady to start: {len(ready_tasks)} tasks")

        return "\n".join(lines)
