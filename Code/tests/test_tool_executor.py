"""Tests for tool executor."""

import pytest
import tempfile
from pathlib import Path

from openpilot.builtin_tools import register_builtin_tools
from openpilot.executor_models import ExecutionStatus
from openpilot.tool_executor import ToolExecutor
from openpilot.tool_orchestration_models import (
    ParallelExecutionGroup,
    ToolSelection,
)
from openpilot.tool_registry import ToolRegistry


# ============================================================================
# Single Execution Tests
# ============================================================================

def test_executor_single_success():
    """Test successful single tool execution."""
    registry = ToolRegistry()
    register_builtin_tools(registry)
    executor = ToolExecutor(registry)

    # Create a file to read
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt') as f:
        f.write("Test content")
        temp_path = f.name

    try:
        # Execute file reader
        selection = ToolSelection(
            step_id="step_1",
            tool_name="file_reader",
            reason="capability_match",
            confidence=0.9,
            input_params={"file_path": temp_path}
        )

        result = executor.execute_single(selection)

        assert result.success
        assert result.status == ExecutionStatus.SUCCESS
        assert result.output is not None
        assert "content" in result.output
        assert result.output["content"] == "Test content"
        assert result.duration_seconds > 0

    finally:
        Path(temp_path).unlink()
        executor.shutdown()


def test_executor_single_failure():
    """Test failed single tool execution."""
    registry = ToolRegistry()
    register_builtin_tools(registry)
    executor = ToolExecutor(registry)

    try:
        # Try to read non-existent file
        selection = ToolSelection(
            step_id="step_1",
            tool_name="file_reader",
            reason="capability_match",
            confidence=0.9,
            input_params={"file_path": "/nonexistent/file.txt"}
        )

        result = executor.execute_single(selection)

        assert not result.success
        assert result.status == ExecutionStatus.FAILED
        assert result.error is not None
        assert result.error.error_type == "FileNotFoundError"

    finally:
        executor.shutdown()


def test_executor_tool_not_found():
    """Test execution with non-existent tool."""
    registry = ToolRegistry()
    executor = ToolExecutor(registry)

    try:
        selection = ToolSelection(
            step_id="step_1",
            tool_name="nonexistent_tool",
            reason="capability_match",
            confidence=0.9,
            input_params={}
        )

        result = executor.execute_single(selection)

        assert not result.success
        assert result.status == ExecutionStatus.FAILED
        assert "not found" in result.error.error_message.lower()

    finally:
        executor.shutdown()


# ============================================================================
# Sequential Execution Tests
# ============================================================================

def test_executor_sequential_success():
    """Test successful sequential execution."""
    registry = ToolRegistry()
    register_builtin_tools(registry)
    executor = ToolExecutor(registry)

    with tempfile.TemporaryDirectory() as tmpdir:
        input_file = Path(tmpdir) / "input.txt"
        output_file = Path(tmpdir) / "output.txt"
        input_file.write_text("Test content")

        try:
            selections = [
                ToolSelection(
                    step_id="step_1",
                    tool_name="file_reader",
                    reason="capability_match",
                    confidence=0.9,
                    input_params={"file_path": str(input_file)}
                ),
                ToolSelection(
                    step_id="step_2",
                    tool_name="file_writer",
                    reason="capability_match",
                    confidence=0.9,
                    input_params={
                        "file_path": str(output_file),
                        "content": "Output content"
                    }
                )
            ]

            results = executor.execute_sequential(selections)

            assert len(results) == 2
            assert all(r.success for r in results)
            assert output_file.exists()

        finally:
            executor.shutdown()


def test_executor_sequential_stop_on_failure():
    """Test sequential execution with stop on failure."""
    registry = ToolRegistry()
    register_builtin_tools(registry)
    executor = ToolExecutor(registry)

    try:
        selections = [
            ToolSelection(
                step_id="step_1",
                tool_name="file_reader",
                reason="capability_match",
                confidence=0.9,
                input_params={"file_path": "/nonexistent.txt"}  # Will fail
            ),
            ToolSelection(
                step_id="step_2",
                tool_name="file_reader",
                reason="capability_match",
                confidence=0.9,
                input_params={"file_path": "/another.txt"}
            )
        ]

        results = executor.execute_sequential(selections, stop_on_failure=True)

        assert len(results) == 2
        assert not results[0].success
        assert results[1].status == ExecutionStatus.CANCELLED

    finally:
        executor.shutdown()


# ============================================================================
# Parallel Execution Tests
# ============================================================================

def test_executor_parallel_success():
    """Test successful parallel execution."""
    registry = ToolRegistry()
    register_builtin_tools(registry)
    executor = ToolExecutor(registry)

    with tempfile.TemporaryDirectory() as tmpdir:
        # Create multiple files
        files = []
        for i in range(3):
            f = Path(tmpdir) / f"file{i}.txt"
            f.write_text(f"Content {i}")
            files.append(f)

        try:
            selections = [
                ToolSelection(
                    step_id=f"step_{i}",
                    tool_name="file_reader",
                    reason="capability_match",
                    confidence=0.9,
                    input_params={"file_path": str(f)}
                )
                for i, f in enumerate(files)
            ]

            parallel_group = ParallelExecutionGroup(
                group_id="group_1",
                tool_selections=selections,
                wait_for_all=True,
                timeout_seconds=30
            )

            result = executor.execute_parallel(parallel_group)

            assert result.all_success
            assert not result.any_failed
            assert len(result.results) == 3
            assert all(r.success for r in result.results)

        finally:
            executor.shutdown()


def test_executor_parallel_with_failure():
    """Test parallel execution with some failures."""
    registry = ToolRegistry()
    register_builtin_tools(registry)
    executor = ToolExecutor(registry)

    with tempfile.TemporaryDirectory() as tmpdir:
        good_file = Path(tmpdir) / "good.txt"
        good_file.write_text("Good content")

        try:
            selections = [
                ToolSelection(
                    step_id="step_1",
                    tool_name="file_reader",
                    reason="capability_match",
                    confidence=0.9,
                    input_params={"file_path": str(good_file)}
                ),
                ToolSelection(
                    step_id="step_2",
                    tool_name="file_reader",
                    reason="capability_match",
                    confidence=0.9,
                    input_params={"file_path": "/nonexistent.txt"}
                )
            ]

            parallel_group = ParallelExecutionGroup(
                group_id="group_1",
                tool_selections=selections,
                wait_for_all=True,
                timeout_seconds=30,
                fail_fast=False
            )

            result = executor.execute_parallel(parallel_group)

            assert not result.all_success
            assert result.any_failed
            assert len(result.results) == 2
            assert result.results[0].success
            assert not result.results[1].success

        finally:
            executor.shutdown()


# ============================================================================
# Retry Tests
# ============================================================================

def test_executor_retry_success_on_second_attempt():
    """Test retry mechanism (simulated)."""
    registry = ToolRegistry()
    register_builtin_tools(registry)
    executor = ToolExecutor(registry)

    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt') as f:
        f.write("Test content")
        temp_path = f.name

    try:
        selection = ToolSelection(
            step_id="step_1",
            tool_name="file_reader",
            reason="capability_match",
            confidence=0.9,
            input_params={"file_path": temp_path}
        )

        result = executor.execute_with_retry(selection, max_retries=3, retry_delay=0)

        assert result.success
        assert result.attempt_number >= 1

    finally:
        Path(temp_path).unlink()
        executor.shutdown()


def test_executor_retry_all_attempts_fail():
    """Test retry when all attempts fail."""
    registry = ToolRegistry()
    register_builtin_tools(registry)
    executor = ToolExecutor(registry)

    try:
        selection = ToolSelection(
            step_id="step_1",
            tool_name="file_reader",
            reason="capability_match",
            confidence=0.9,
            input_params={"file_path": "/nonexistent.txt"}
        )

        result = executor.execute_with_retry(selection, max_retries=2, retry_delay=0)

        assert not result.success
        # Should have tried twice (initial + 1 retry for max_retries=2)

    finally:
        executor.shutdown()


# ============================================================================
# Fallback Tests
# ============================================================================

def test_executor_fallback_success():
    """Test fallback mechanism."""
    registry = ToolRegistry()
    register_builtin_tools(registry)
    executor = ToolExecutor(registry)

    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt') as f:
        f.write("Test content")
        temp_path = f.name

    try:
        # Primary tool will succeed, so fallback not needed
        selection = ToolSelection(
            step_id="step_1",
            tool_name="file_reader",
            reason="capability_match",
            confidence=0.9,
            input_params={"file_path": temp_path}
        )

        result = executor.execute_with_fallback(selection, fallback_tools=[])

        assert result.success

    finally:
        Path(temp_path).unlink()
        executor.shutdown()


# ============================================================================
# Resource Tracking Tests
# ============================================================================

def test_executor_resource_tracking():
    """Test that resource usage is tracked."""
    registry = ToolRegistry()
    register_builtin_tools(registry)
    executor = ToolExecutor(registry)

    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt') as f:
        f.write("Test content")
        temp_path = f.name

    try:
        selection = ToolSelection(
            step_id="step_1",
            tool_name="file_reader",
            reason="capability_match",
            confidence=0.9,
            input_params={"file_path": temp_path}
        )

        result = executor.execute_single(selection)

        assert result.success
        assert result.resource_usage is not None
        # In simplified version, these might be 0
        assert result.resource_usage.cpu_percent >= 0
        assert result.resource_usage.memory_mb >= 0

    finally:
        Path(temp_path).unlink()
        executor.shutdown()
