"""Unit tests for task decomposer."""

import pytest
from unittest.mock import Mock

from agents.task_decomposer import TaskDecomposer
from models.task_models import Task, TaskStatus, TaskPriority
from core.llm import LLMClient, LLMResponse
from core.graph import GraphType


class TestTaskDecomposer:
    """Tests for TaskDecomposer."""

    @pytest.fixture
    def mock_llm_client(self):
        """Mock LLM client."""
        client = Mock(spec=LLMClient)

        # Mock decomposition response
        decomposition_response = LLMResponse(
            content='{"rationale": "Test decomposition", "subtasks": [{"description": "Subtask 1", "priority": "high", "estimated_effort": 1.0, "dependencies": [], "tags": []}]}',
            model="test-model",
            provider="openai",
            usage={},
            parsed_json={
                "rationale": "Test decomposition",
                "subtasks": [
                    {
                        "description": "Subtask 1",
                        "priority": "high",
                        "estimated_effort": 1.0,
                        "dependencies": [],
                        "tags": []
                    }
                ]
            }
        )

        client.complete.return_value = decomposition_response
        return client

    def test_initialization(self, mock_llm_client):
        """Test decomposer initialization."""
        decomposer = TaskDecomposer(
            llm_client=mock_llm_client,
            max_decomposition_depth=3
        )

        assert decomposer.max_decomposition_depth == 3
        assert decomposer.llm_client is not None

    def test_should_decompose_max_depth(self, mock_llm_client):
        """Test should_decompose at max depth."""
        decomposer = TaskDecomposer(mock_llm_client, max_decomposition_depth=2)

        task = Task(id="1", description="Test task")

        # Should not decompose at max depth
        assert not decomposer.should_decompose(task, current_depth=2)

    def test_should_decompose_with_subtasks(self, mock_llm_client):
        """Test should_decompose with existing subtasks."""
        decomposer = TaskDecomposer(mock_llm_client)

        task = Task(
            id="1",
            description="Test task",
            metadata={"has_subtasks": True}
        )

        assert not decomposer.should_decompose(task)

    def test_decompose_task(self, mock_llm_client):
        """Test task decomposition."""
        decomposer = TaskDecomposer(mock_llm_client)

        result = decomposer.decompose(
            task_description="Build a web application",
            context={"framework": "React"}
        )

        assert result.original_task is not None
        assert len(result.subtasks) > 0
        assert result.decomposition_rationale != ""
        assert result.estimated_total_effort >= 0

    def test_build_task_graph(self, mock_llm_client):
        """Test building task graph."""
        decomposer = TaskDecomposer(mock_llm_client)

        task1 = Task(id="1", description="Task 1")
        task2 = Task(id="2", description="Task 2", dependencies=["1"])
        task3 = Task(id="3", description="Task 3", dependencies=["1", "2"])

        tasks = [task1, task2, task3]
        graph = decomposer.build_task_graph(tasks)

        assert graph.node_count() == 3
        assert graph.edge_count() == 3
        assert graph.graph_type == GraphType.DIRECTED

    def test_get_execution_order(self, mock_llm_client):
        """Test getting execution order."""
        decomposer = TaskDecomposer(mock_llm_client)

        task1 = Task(id="1", description="Task 1")
        task2 = Task(id="2", description="Task 2", dependencies=["1"])
        task3 = Task(id="3", description="Task 3", dependencies=["2"])

        tasks = [task1, task2, task3]
        graph = decomposer.build_task_graph(tasks)

        execution_order = decomposer.get_execution_order(graph)

        assert len(execution_order) == 3
        assert execution_order[0] == "1"
        assert execution_order[1] == "2"
        assert execution_order[2] == "3"

    def test_get_execution_order_with_cycle(self, mock_llm_client):
        """Test execution order with circular dependencies."""
        decomposer = TaskDecomposer(mock_llm_client)

        task1 = Task(id="1", description="Task 1", dependencies=["3"])
        task2 = Task(id="2", description="Task 2", dependencies=["1"])
        task3 = Task(id="3", description="Task 3", dependencies=["2"])

        tasks = [task1, task2, task3]
        graph = decomposer.build_task_graph(tasks)

        with pytest.raises(ValueError, match="Cannot determine execution order"):
            decomposer.get_execution_order(graph)

    def test_get_ready_tasks(self, mock_llm_client):
        """Test getting ready tasks."""
        decomposer = TaskDecomposer(mock_llm_client)

        task1 = Task(id="1", description="Task 1", status=TaskStatus.COMPLETED)
        task2 = Task(id="2", description="Task 2", dependencies=["1"])
        task3 = Task(id="3", description="Task 3", dependencies=["1", "2"])

        tasks = [task1, task2, task3]
        ready = decomposer.get_ready_tasks(tasks)

        # Only task2 should be ready (task1 is completed, task3 depends on task2)
        assert len(ready) == 1
        assert ready[0].id == "2"

    def test_assemble_results(self, mock_llm_client):
        """Test assembling results from subtasks."""
        decomposer = TaskDecomposer(mock_llm_client)

        parent = Task(id="parent", description="Parent task")

        subtask1 = Task(
            id="1",
            description="Subtask 1",
            status=TaskStatus.COMPLETED,
            result="Result 1"
        )
        subtask2 = Task(
            id="2",
            description="Subtask 2",
            status=TaskStatus.COMPLETED,
            result="Result 2"
        )

        result = decomposer.assemble_results(parent, [subtask1, subtask2])

        assert result["parent_task_id"] == "parent"
        assert result["total_subtasks"] == 2
        assert result["successful_subtasks"] == 2
        assert len(result["subtask_results"]) == 2

    def test_assemble_results_incomplete(self, mock_llm_client):
        """Test assembling with incomplete subtasks."""
        decomposer = TaskDecomposer(mock_llm_client)

        parent = Task(id="parent", description="Parent task")

        subtask1 = Task(id="1", description="Subtask 1", status=TaskStatus.COMPLETED)
        subtask2 = Task(id="2", description="Subtask 2", status=TaskStatus.PENDING)

        with pytest.raises(ValueError, match="Cannot assemble"):
            decomposer.assemble_results(parent, [subtask1, subtask2])

    def test_fallback_decomposition(self, mock_llm_client):
        """Test fallback decomposition when LLM fails."""
        # Make LLM fail
        mock_llm_client.complete.side_effect = Exception("LLM error")

        decomposer = TaskDecomposer(mock_llm_client)

        result = decomposer.decompose("Test task")

        # Should still produce subtasks using fallback
        assert len(result.subtasks) > 0
        assert "Automatic decomposition" in result.decomposition_rationale
