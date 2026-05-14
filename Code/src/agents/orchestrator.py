"""Agent orchestrator for coordinating multiple agents."""

from __future__ import annotations

import asyncio
import time
from typing import Any, Callable

from core.graph import Graph
from agents.task_models import (
    Task,
    TaskStatus,
    Agent,
    AgentCapability,
    TaskExecutionContext,
    TaskExecutionResult
)


class AgentOrchestrator:
    """Orchestrates multiple agents working on tasks."""

    def __init__(
        self,
        max_concurrent_tasks: int = 5,
        task_timeout: float = 300.0  # 5 minutes default
    ):
        """Initialize orchestrator.

        Args:
            max_concurrent_tasks: Maximum concurrent tasks across all agents
            task_timeout: Task execution timeout in seconds
        """
        self.max_concurrent_tasks = max_concurrent_tasks
        self.task_timeout = task_timeout

        # Agent pool
        self.agents: dict[str, Agent] = {}

        # Task tracking
        self.tasks: dict[str, Task] = {}
        self.task_results: dict[str, TaskExecutionResult] = {}

        # Execution callbacks
        self.task_executor: Callable[[Task, TaskExecutionContext], Any] | None = None

    def register_agent(self, agent: Agent) -> None:
        """Register an agent.

        Args:
            agent: Agent to register
        """
        self.agents[agent.id] = agent

    def unregister_agent(self, agent_id: str) -> bool:
        """Unregister an agent.

        Args:
            agent_id: Agent ID

        Returns:
            True if agent was unregistered
        """
        if agent_id in self.agents:
            del self.agents[agent_id]
            return True
        return False

    def set_task_executor(self, executor: Callable[[Task, TaskExecutionContext], Any]) -> None:
        """Set task executor function.

        Args:
            executor: Function that executes a task
        """
        self.task_executor = executor

    def assign_task(self, task: Task, agent_id: str | None = None) -> bool:
        """Assign a task to an agent.

        Args:
            task: Task to assign
            agent_id: Optional specific agent ID

        Returns:
            True if task was assigned
        """
        # Store task
        self.tasks[task.id] = task

        # Find suitable agent
        if agent_id:
            agent = self.agents.get(agent_id)
            if not agent or not agent.is_available():
                return False
        else:
            agent = self._find_suitable_agent(task)
            if not agent:
                return False

        # Assign task
        agent.assign_task(task.id)
        task.mark_started(agent.id)

        return True

    def execute_task_graph(
        self,
        task_graph: Graph,
        context: dict[str, Any] | None = None
    ) -> dict[str, TaskExecutionResult]:
        """Execute tasks in a task graph.

        Args:
            task_graph: Task dependency graph
            context: Optional execution context

        Returns:
            Dictionary of task results
        """
        context = context or {}

        # Get execution order
        try:
            execution_order = task_graph.topological_sort()
        except ValueError as e:
            raise ValueError(f"Cannot execute task graph with cycles: {e}") from e

        # Execute tasks in order
        results = {}
        for node in execution_order:
            task_id = node.id

            # Get or create task
            if task_id not in self.tasks:
                task = Task(
                    id=task_id,
                    description=node.data.get("description", ""),
                    priority=node.data.get("priority", "medium"),
                    estimated_effort=node.data.get("estimated_effort")
                )
                self.tasks[task_id] = task
            else:
                task = self.tasks[task_id]

            # Execute task
            result = self._execute_task_sync(task, context)
            results[task_id] = result

            # Update task status
            if result.status == TaskStatus.COMPLETED:
                task.mark_completed(result.result)
            elif result.status == TaskStatus.FAILED:
                task.mark_failed(result.error or "Unknown error")

        return results

    async def execute_task_graph_async(
        self,
        task_graph: Graph,
        context: dict[str, Any] | None = None
    ) -> dict[str, TaskExecutionResult]:
        """Execute tasks in a task graph asynchronously.

        Args:
            task_graph: Task dependency graph
            context: Optional execution context

        Returns:
            Dictionary of task results
        """
        context = context or {}

        # Get all tasks
        task_nodes = task_graph.get_all_nodes()
        tasks_by_id = {}

        for node in task_nodes:
            if node.id not in self.tasks:
                task = Task(
                    id=node.id,
                    description=node.data.get("description", ""),
                    priority=node.data.get("priority", "medium"),
                    estimated_effort=node.data.get("estimated_effort")
                )
                self.tasks[node.id] = task
                tasks_by_id[node.id] = task
            else:
                tasks_by_id[node.id] = self.tasks[node.id]

        # Build dependency map
        dependencies = {}
        for node in task_nodes:
            deps = task_graph.get_predecessors(node.id)
            dependencies[node.id] = [d.id for d in deps]

        # Execute tasks respecting dependencies
        results = {}
        completed = set()
        in_progress = set()

        while len(completed) < len(tasks_by_id):
            # Find ready tasks
            ready_tasks = []
            for task_id, task in tasks_by_id.items():
                if task_id in completed or task_id in in_progress:
                    continue

                # Check if all dependencies are completed
                deps = dependencies.get(task_id, [])
                if all(dep_id in completed for dep_id in deps):
                    ready_tasks.append(task)

            if not ready_tasks:
                # Wait for in-progress tasks
                if in_progress:
                    await asyncio.sleep(0.1)
                    continue
                else:
                    break

            # Execute ready tasks concurrently (up to limit)
            tasks_to_execute = ready_tasks[:self.max_concurrent_tasks - len(in_progress)]

            async_tasks = []
            for task in tasks_to_execute:
                in_progress.add(task.id)
                async_tasks.append(self._execute_task_async(task, context))

            # Wait for tasks to complete
            task_results = await asyncio.gather(*async_tasks, return_exceptions=True)

            # Process results
            for task, result in zip(tasks_to_execute, task_results):
                in_progress.remove(task.id)
                completed.add(task.id)

                if isinstance(result, Exception):
                    result = TaskExecutionResult(
                        task_id=task.id,
                        status=TaskStatus.FAILED,
                        error=str(result)
                    )

                results[task.id] = result

                # Update task status
                if result.status == TaskStatus.COMPLETED:
                    task.mark_completed(result.result)
                elif result.status == TaskStatus.FAILED:
                    task.mark_failed(result.error or "Unknown error")

        return results

    def monitor_progress(self) -> dict[str, Any]:
        """Monitor execution progress.

        Returns:
            Dictionary with progress information
        """
        total_tasks = len(self.tasks)
        completed = sum(1 for t in self.tasks.values() if t.status == TaskStatus.COMPLETED)
        failed = sum(1 for t in self.tasks.values() if t.status == TaskStatus.FAILED)
        in_progress = sum(1 for t in self.tasks.values() if t.status == TaskStatus.IN_PROGRESS)
        pending = sum(1 for t in self.tasks.values() if t.status == TaskStatus.PENDING)

        # Agent status
        agent_status = {}
        for agent_id, agent in self.agents.items():
            agent_status[agent_id] = {
                "status": agent.status,
                "current_tasks": len(agent.current_tasks),
                "completed_tasks": agent.completed_tasks,
                "failed_tasks": agent.failed_tasks
            }

        return {
            "total_tasks": total_tasks,
            "completed": completed,
            "failed": failed,
            "in_progress": in_progress,
            "pending": pending,
            "completion_rate": completed / total_tasks if total_tasks > 0 else 0,
            "agents": agent_status
        }

    def handle_task_failure(self, task: Task, error: Exception) -> None:
        """Handle task failure.

        Args:
            task: Failed task
            error: Error that occurred
        """
        task.mark_failed(str(error))

        # Release agent
        if task.assigned_agent:
            agent = self.agents.get(task.assigned_agent)
            if agent:
                agent.complete_task(task.id, success=False)

        # Store result
        self.task_results[task.id] = TaskExecutionResult(
            task_id=task.id,
            status=TaskStatus.FAILED,
            error=str(error)
        )

    def get_task_result(self, task_id: str) -> TaskExecutionResult | None:
        """Get result for a task.

        Args:
            task_id: Task ID

        Returns:
            Task result or None
        """
        return self.task_results.get(task_id)

    def get_all_results(self) -> dict[str, TaskExecutionResult]:
        """Get all task results.

        Returns:
            Dictionary of all results
        """
        return self.task_results.copy()

    def clear_completed_tasks(self) -> int:
        """Clear completed tasks from memory.

        Returns:
            Number of tasks cleared
        """
        completed_ids = [
            task_id for task_id, task in self.tasks.items()
            if task.status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED)
        ]

        for task_id in completed_ids:
            del self.tasks[task_id]

        return len(completed_ids)

    def _find_suitable_agent(self, task: Task) -> Agent | None:
        """Find a suitable agent for a task.

        Args:
            task: Task to assign

        Returns:
            Suitable agent or None
        """
        # Find available agents that can handle the task
        suitable_agents = [
            agent for agent in self.agents.values()
            if agent.is_available() and agent.can_handle(task)
        ]

        if not suitable_agents:
            return None

        # Prefer agents with fewer current tasks
        suitable_agents.sort(key=lambda a: len(a.current_tasks))

        return suitable_agents[0]

    def _execute_task_sync(self, task: Task, context: dict[str, Any]) -> TaskExecutionResult:
        """Execute a task synchronously.

        Args:
            task: Task to execute
            context: Execution context

        Returns:
            Task execution result
        """
        if not self.task_executor:
            return TaskExecutionResult(
                task_id=task.id,
                status=TaskStatus.FAILED,
                error="No task executor configured"
            )

        start_time = time.time()

        try:
            # Create execution context
            exec_context = TaskExecutionContext(
                task=task,
                parent_context=context,
                shared_state={}
            )

            # Execute task
            result = self.task_executor(task, exec_context)

            duration = time.time() - start_time

            return TaskExecutionResult(
                task_id=task.id,
                status=TaskStatus.COMPLETED,
                result=result,
                duration=duration
            )

        except Exception as e:
            duration = time.time() - start_time

            return TaskExecutionResult(
                task_id=task.id,
                status=TaskStatus.FAILED,
                error=str(e),
                duration=duration
            )

    async def _execute_task_async(
        self,
        task: Task,
        context: dict[str, Any]
    ) -> TaskExecutionResult:
        """Execute a task asynchronously.

        Args:
            task: Task to execute
            context: Execution context

        Returns:
            Task execution result
        """
        if not self.task_executor:
            return TaskExecutionResult(
                task_id=task.id,
                status=TaskStatus.FAILED,
                error="No task executor configured"
            )

        start_time = time.time()

        try:
            # Create execution context
            exec_context = TaskExecutionContext(
                task=task,
                parent_context=context,
                shared_state={}
            )

            # Execute task (run in thread pool if synchronous)
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                self.task_executor,
                task,
                exec_context
            )

            duration = time.time() - start_time

            return TaskExecutionResult(
                task_id=task.id,
                status=TaskStatus.COMPLETED,
                result=result,
                duration=duration
            )

        except Exception as e:
            duration = time.time() - start_time

            return TaskExecutionResult(
                task_id=task.id,
                status=TaskStatus.FAILED,
                error=str(e),
                duration=duration
            )
