"""Unit tests for agent orchestrator."""

import pytest
import asyncio
from unittest.mock import Mock

from agents.orchestrator import AgentOrchestrator
from models.task_models import (
    Task,
    TaskStatus,
    Agent,
    AgentCapability,
    TaskExecutionContext,
    TaskExecutionResult
)
from core.graph import Graph, GraphNode, GraphEdge, GraphType


class TestAgentOrchestrator:
    """Tests for AgentOrchestrator."""

    @pytest.fixture
    def orchestrator(self):
        """Create orchestrator instance."""
        return AgentOrchestrator(max_concurrent_tasks=3)

    @pytest.fixture
    def sample_agent(self):
        """Create sample agent."""
        return Agent(
            id="agent-1",
            name="Test Agent",
            capabilities=[AgentCapability.GENERAL],
            max_concurrent_tasks=2
        )

    @pytest.fixture
    def sample_task(self):
        """Create sample task."""
        return Task(
            id="task-1",
            description="Test task"
        )

    def test_initialization(self, orchestrator):
        """Test orchestrator initialization."""
        assert orchestrator.max_concurrent_tasks == 3
        assert len(orchestrator.agents) == 0
        assert len(orchestrator.tasks) == 0

    def test_register_agent(self, orchestrator, sample_agent):
        """Test registering an agent."""
        orchestrator.register_agent(sample_agent)

        assert sample_agent.id in orchestrator.agents
        assert orchestrator.agents[sample_agent.id] == sample_agent

    def test_unregister_agent(self, orchestrator, sample_agent):
        """Test unregistering an agent."""
        orchestrator.register_agent(sample_agent)
        assert sample_agent.id in orchestrator.agents

        success = orchestrator.unregister_agent(sample_agent.id)

        assert success
        assert sample_agent.id not in orchestrator.agents

    def test_assign_task(self, orchestrator, sample_agent, sample_task):
        """Test assigning a task to an agent."""
        orchestrator.register_agent(sample_agent)

        success = orchestrator.assign_task(sample_task, sample_agent.id)

        assert success
        assert sample_task.id in orchestrator.tasks
        assert sample_task.status == TaskStatus.IN_PROGRESS
        assert sample_task.assigned_agent == sample_agent.id
        assert sample_task.id in sample_agent.current_tasks

    def test_assign_task_auto_select_agent(self, orchestrator, sample_agent, sample_task):
        """Test auto-selecting agent for task."""
        orchestrator.register_agent(sample_agent)

        success = orchestrator.assign_task(sample_task)

        assert success
        assert sample_task.assigned_agent == sample_agent.id

    def test_assign_task_no_available_agent(self, orchestrator, sample_task):
        """Test assigning task with no available agents."""
        success = orchestrator.assign_task(sample_task)

        assert not success

    def test_set_task_executor(self, orchestrator):
        """Test setting task executor."""
        def executor(task, context):
            return "result"

        orchestrator.set_task_executor(executor)

        assert orchestrator.task_executor is not None

    def test_execute_task_graph(self, orchestrator):
        """Test executing a task graph."""
        # Create simple task graph
        graph = Graph(GraphType.DIRECTED)

        task1 = Task(id="1", description="Task 1")
        task2 = Task(id="2", description="Task 2", dependencies=["1"])

        graph.add_node(GraphNode(id="1", type="task", data={"description": "Task 1"}))
        graph.add_node(GraphNode(id="2", type="task", data={"description": "Task 2"}))
        graph.add_edge(GraphEdge(source_id="1", target_id="2", edge_type="depends_on"))

        # Set executor
        def executor(task, context):
            return f"Result for {task.id}"

        orchestrator.set_task_executor(executor)

        # Execute
        results = orchestrator.execute_task_graph(graph)

        assert len(results) == 2
        assert "1" in results
        assert "2" in results
        assert results["1"].status == TaskStatus.COMPLETED
        assert results["2"].status == TaskStatus.COMPLETED

    def test_execute_task_graph_with_failure(self, orchestrator):
        """Test executing task graph with failure."""
        graph = Graph(GraphType.DIRECTED)
        graph.add_node(GraphNode(id="1", type="task", data={"description": "Task 1"}))

        # Executor that fails
        def executor(task, context):
            raise Exception("Task failed")

        orchestrator.set_task_executor(executor)

        results = orchestrator.execute_task_graph(graph)

        assert len(results) == 1
        assert results["1"].status == TaskStatus.FAILED
        assert "Task failed" in results["1"].error

    def test_execute_task_graph_async(self, orchestrator):
        """Test async task graph execution."""
        graph = Graph(GraphType.DIRECTED)

        graph.add_node(GraphNode(id="1", type="task", data={"description": "Task 1"}))
        graph.add_node(GraphNode(id="2", type="task", data={"description": "Task 2"}))
        graph.add_node(GraphNode(id="3", type="task", data={"description": "Task 3"}))

        # No dependencies - all can run in parallel
        def executor(task, context):
            return f"Result for {task.id}"

        orchestrator.set_task_executor(executor)

        # Run async function in event loop
        results = asyncio.run(orchestrator.execute_task_graph_async(graph))

        assert len(results) == 3
        assert all(r.status == TaskStatus.COMPLETED for r in results.values())

    def test_monitor_progress(self, orchestrator, sample_agent):
        """Test monitoring progress."""
        orchestrator.register_agent(sample_agent)

        task1 = Task(id="1", description="Task 1", status=TaskStatus.COMPLETED)
        task2 = Task(id="2", description="Task 2", status=TaskStatus.IN_PROGRESS)
        task3 = Task(id="3", description="Task 3", status=TaskStatus.PENDING)

        orchestrator.tasks = {"1": task1, "2": task2, "3": task3}

        progress = orchestrator.monitor_progress()

        assert progress["total_tasks"] == 3
        assert progress["completed"] == 1
        assert progress["in_progress"] == 1
        assert progress["pending"] == 1
        assert progress["completion_rate"] == 1/3

    def test_handle_task_failure(self, orchestrator, sample_agent, sample_task):
        """Test handling task failure."""
        orchestrator.register_agent(sample_agent)
        sample_agent.assign_task(sample_task.id)
        sample_task.assigned_agent = sample_agent.id

        error = Exception("Test error")
        orchestrator.handle_task_failure(sample_task, error)

        assert sample_task.status == TaskStatus.FAILED
        assert sample_task.error == "Test error"
        assert sample_task.id not in sample_agent.current_tasks

    def test_get_task_result(self, orchestrator):
        """Test getting task result."""
        result = TaskExecutionResult(
            task_id="1",
            status=TaskStatus.COMPLETED,
            result="test result"
        )

        orchestrator.task_results["1"] = result

        retrieved = orchestrator.get_task_result("1")

        assert retrieved is not None
        assert retrieved.task_id == "1"
        assert retrieved.result == "test result"

    def test_get_all_results(self, orchestrator):
        """Test getting all results."""
        result1 = TaskExecutionResult(task_id="1", status=TaskStatus.COMPLETED)
        result2 = TaskExecutionResult(task_id="2", status=TaskStatus.COMPLETED)

        orchestrator.task_results = {"1": result1, "2": result2}

        all_results = orchestrator.get_all_results()

        assert len(all_results) == 2
        assert "1" in all_results
        assert "2" in all_results

    def test_clear_completed_tasks(self, orchestrator):
        """Test clearing completed tasks."""
        task1 = Task(id="1", description="Task 1", status=TaskStatus.COMPLETED)
        task2 = Task(id="2", description="Task 2", status=TaskStatus.IN_PROGRESS)
        task3 = Task(id="3", description="Task 3", status=TaskStatus.FAILED)

        orchestrator.tasks = {"1": task1, "2": task2, "3": task3}

        cleared = orchestrator.clear_completed_tasks()

        assert cleared == 2
        assert "1" not in orchestrator.tasks
        assert "2" in orchestrator.tasks
        assert "3" not in orchestrator.tasks

    def test_find_suitable_agent_by_capability(self, orchestrator):
        """Test finding agent by capability."""
        agent1 = Agent(
            id="agent-1",
            name="General Agent",
            capabilities=[AgentCapability.GENERAL]
        )
        agent2 = Agent(
            id="agent-2",
            name="Code Agent",
            capabilities=[AgentCapability.CODE_GENERATION]
        )

        orchestrator.register_agent(agent1)
        orchestrator.register_agent(agent2)

        # Task requiring code generation
        task = Task(
            id="1",
            description="Generate code",
            metadata={"required_capabilities": [AgentCapability.CODE_GENERATION]}
        )

        agent = orchestrator._find_suitable_agent(task)

        assert agent is not None
        assert AgentCapability.CODE_GENERATION in agent.capabilities

    def test_find_suitable_agent_prefers_less_busy(self, orchestrator):
        """Test that less busy agents are preferred."""
        agent1 = Agent(id="agent-1", name="Busy Agent", max_concurrent_tasks=5)
        agent1.current_tasks = ["task-1", "task-2", "task-3"]

        agent2 = Agent(id="agent-2", name="Free Agent", max_concurrent_tasks=5)
        agent2.current_tasks = []

        orchestrator.register_agent(agent1)
        orchestrator.register_agent(agent2)

        task = Task(id="new-task", description="New task")

        agent = orchestrator._find_suitable_agent(task)

        assert agent.id == "agent-2"
