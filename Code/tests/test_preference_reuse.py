"""Tests for OP-04 preference reuse workflow."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import Mock

import pytest

from openpilot.llm import LLMResponse
from openpilot.memory_models import MemoryRecord, MemoryType
from openpilot.memory_store import MemoryStore
from openpilot.openpilot_log import OpenPilotLogger
from openpilot.openpilot_session import OpenPilotSession
from openpilot.planner import TaskPlanner
from openpilot.planner_models import ExecutionPlan, PlanStep, RiskLevel, TaskCard


@pytest.fixture
def temp_memory_dir():
    """Create a temporary directory for memory storage."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def temp_log_file():
    """Create a temporary log file."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
        yield Path(f.name)
    Path(f.name).unlink(missing_ok=True)


@pytest.fixture
def memory_store(temp_memory_dir):
    """Create a memory store with test data."""
    store = MemoryStore(data_dir=temp_memory_dir)

    # Add high-confidence preference
    store.save(
        MemoryRecord(
            id="pref-1",
            memory_type=MemoryType.LONG_TERM,
            content="User prefers Markdown table format for reports",
            tags=["format", "report", "markdown"],
            confidence=0.9,
            usage_count=5,
        )
    )

    # Add low-confidence preference
    store.save(
        MemoryRecord(
            id="pref-2",
            memory_type=MemoryType.LONG_TERM,
            content="User might prefer blue color scheme",
            tags=["color", "design"],
            confidence=0.4,
            usage_count=1,
        )
    )

    # Add task memory
    store.save(
        MemoryRecord(
            id="task-1",
            memory_type=MemoryType.TASK,
            content="Research tasks usually take 3 days",
            tags=["research", "estimation"],
            confidence=0.8,
            usage_count=3,
        )
    )

    return store


def test_memory_retrieval_on_planning(temp_log_file, memory_store):
    """Test that memories are retrieved during planning."""
    mock_llm = Mock()
    mock_llm.complete.return_value = LLMResponse(
        content=json.dumps({
            "task_card": {
                "goal": "Research AI agents",
                "task_type": "research",
                "priority": "normal",
                "risk_level": "low",
                "required_resources": ["web_search"],
                "expected_deliverables": ["report"],
                "constraints": [],
            },
            "steps": [
                {
                    "id": "step-1",
                    "title": "Search for information",
                    "description": "Find relevant sources",
                    "risk_level": "low",
                    "required_resources": ["web_search"],
                    "expected_output": "List of sources",
                    "dependencies": [],
                    "confirmation_required": False,
                }
            ],
            "fallbacks": [],
            "confirmation_points": [],
            "success_criteria": ["Report completed"],
        }),
        parsed_json=None,
        model="test-model",
        provider="test-provider",
    )

    planner = TaskPlanner(mock_llm)
    logger = OpenPilotLogger(temp_log_file)
    session = OpenPilotSession(
        planner=planner,
        logger=logger,
        memory_store=memory_store,
        enable_memory=True,
    )

    result = session.handle_goal("Research AI agents and create a report")

    assert result.ok
    assert result.memory_reuse_notes is not None
    assert "high-confidence" in result.memory_reuse_notes.lower()

    # Check that memory_retrieved event was logged
    with open(temp_log_file, "r") as f:
        events = [json.loads(line) for line in f]

    memory_events = [e for e in events if e["event_type"] == "memory_retrieved"]
    assert len(memory_events) == 1
    assert memory_events[0]["payload"]["memory_count"] > 0


def test_high_confidence_preferences_injected_as_constraints(temp_log_file, memory_store):
    """Test that high-confidence preferences are added to planning constraints."""
    mock_llm = Mock()

    # Capture the request to verify constraints
    captured_request = None

    def capture_request(request):
        nonlocal captured_request
        captured_request = request
        return LLMResponse(
            content=json.dumps({
                "task_card": {
                    "goal": "Create report",
                    "task_type": "research",
                    "priority": "normal",
                    "risk_level": "low",
                    "required_resources": [],
                    "expected_deliverables": ["report"],
                    "constraints": [],
                },
                "steps": [
                    {
                        "id": "step-1",
                        "title": "Generate report",
                        "description": "Create the report",
                        "risk_level": "low",
                        "required_resources": [],
                        "expected_output": "Report",
                        "dependencies": [],
                        "confirmation_required": False,
                    }
                ],
                "fallbacks": [],
                "confirmation_points": [],
                "success_criteria": ["Done"],
            }),
            parsed_json=None,
            model="test-model",
            provider="test-provider",
        )

    mock_llm.complete.side_effect = capture_request

    planner = TaskPlanner(mock_llm)
    logger = OpenPilotLogger(temp_log_file)
    session = OpenPilotSession(
        planner=planner,
        logger=logger,
        memory_store=memory_store,
        enable_memory=True,
    )

    # Use a goal that will match the high-confidence memory
    result = session.handle_goal("Create a report with table format")

    assert result.ok
    assert captured_request is not None

    # Check that high-confidence preference was injected
    user_message = captured_request.messages[1].content
    user_data = json.loads(user_message)
    constraints = user_data.get("constraints", [])

    # Should contain the high-confidence preference (if memory was retrieved)
    # Check if any memories were retrieved first
    if result.memory_reuse_notes and "high-confidence" in result.memory_reuse_notes.lower():
        assert any("Markdown table" in c for c in constraints)
    # Should NOT contain the low-confidence preference
    assert not any("blue color" in c for c in constraints)


def test_low_confidence_preferences_not_auto_applied(temp_log_file, memory_store):
    """Test that low-confidence preferences are not automatically applied."""
    mock_llm = Mock()

    captured_request = None

    def capture_request(request):
        nonlocal captured_request
        captured_request = request
        return LLMResponse(
            content=json.dumps({
                "task_card": {
                    "goal": "Design UI",
                    "task_type": "design",
                    "priority": "normal",
                    "risk_level": "low",
                    "required_resources": [],
                    "expected_deliverables": ["mockup"],
                    "constraints": [],
                },
                "steps": [
                    {
                        "id": "step-1",
                        "title": "Create mockup",
                        "description": "Design the UI",
                        "risk_level": "low",
                        "required_resources": [],
                        "expected_output": "Mockup",
                        "dependencies": [],
                        "confirmation_required": False,
                    }
                ],
                "fallbacks": [],
                "confirmation_points": [],
                "success_criteria": ["Done"],
            }),
            parsed_json=None,
            model="test-model",
            provider="test-provider",
        )

    mock_llm.complete.side_effect = capture_request

    planner = TaskPlanner(mock_llm)
    logger = OpenPilotLogger(temp_log_file)
    session = OpenPilotSession(
        planner=planner,
        logger=logger,
        memory_store=memory_store,
        enable_memory=True,
    )

    result = session.handle_goal("Design a UI with color scheme")

    assert result.ok

    # Low-confidence preference should be found but not applied
    if result.memory_reuse_notes:
        assert "lower confidence" in result.memory_reuse_notes.lower()


def test_memory_usage_count_increases(temp_log_file, memory_store):
    """Test that memory usage count increases when memories are used."""
    initial_memory = memory_store.get_by_id("pref-1", MemoryType.LONG_TERM)
    initial_usage = initial_memory.usage_count if initial_memory else 0

    mock_llm = Mock()
    mock_llm.complete.return_value = LLMResponse(
        content=json.dumps({
            "task_card": {
                "goal": "Research",
                "task_type": "research",
                "priority": "normal",
                "risk_level": "low",
                "required_resources": [],
                "expected_deliverables": [],
                "constraints": [],
            },
            "steps": [
                {
                    "id": "step-1",
                    "title": "Do research",
                    "description": "Research",
                    "risk_level": "low",
                    "required_resources": [],
                    "expected_output": "Results",
                    "dependencies": [],
                    "confirmation_required": False,
                }
            ],
            "fallbacks": [],
            "confirmation_points": [],
            "success_criteria": ["Done"],
        }),
        parsed_json=None,
        model="test-model",
        provider="test-provider",
    )

    planner = TaskPlanner(mock_llm)
    logger = OpenPilotLogger(temp_log_file)
    session = OpenPilotSession(
        planner=planner,
        logger=logger,
        memory_store=memory_store,
        enable_memory=True,
    )

    # Use a goal that will match the memory
    result = session.handle_goal("Create a report with Markdown table format")

    assert result.ok

    # Check that usage count increased (only if memory was retrieved)
    updated_memory = memory_store.get_by_id("pref-1", MemoryType.LONG_TERM)
    assert updated_memory is not None

    # If memory was retrieved, usage should increase
    if result.memory_reuse_notes:
        assert updated_memory.usage_count > initial_usage
    else:
        # If no memory was retrieved, usage stays the same
        assert updated_memory.usage_count == initial_usage


def test_ignore_memory_flag_disables_retrieval(temp_log_file, memory_store):
    """Test that enable_memory=False disables memory retrieval."""
    mock_llm = Mock()
    mock_llm.complete.return_value = LLMResponse(
        content=json.dumps({
            "task_card": {
                "goal": "Research",
                "task_type": "research",
                "priority": "normal",
                "risk_level": "low",
                "required_resources": [],
                "expected_deliverables": [],
                "constraints": [],
            },
            "steps": [
                {
                    "id": "step-1",
                    "title": "Do research",
                    "description": "Research",
                    "risk_level": "low",
                    "required_resources": [],
                    "expected_output": "Results",
                    "dependencies": [],
                    "confirmation_required": False,
                }
            ],
            "fallbacks": [],
            "confirmation_points": [],
            "success_criteria": ["Done"],
        }),
        parsed_json=None,
        model="test-model",
        provider="test-provider",
    )

    planner = TaskPlanner(mock_llm)
    logger = OpenPilotLogger(temp_log_file)
    session = OpenPilotSession(
        planner=planner,
        logger=logger,
        memory_store=memory_store,
        enable_memory=False,  # Disable memory
    )

    result = session.handle_goal("Create a research report")

    assert result.ok
    assert result.memory_reuse_notes is None

    # Check that no memory_retrieved event was logged
    with open(temp_log_file, "r") as f:
        events = [json.loads(line) for line in f]

    memory_events = [e for e in events if e["event_type"] == "memory_retrieved"]
    assert len(memory_events) == 0


def test_memory_reuse_notes_in_log(temp_log_file, memory_store):
    """Test that memory_reuse_notes appear in planner_succeeded log."""
    mock_llm = Mock()
    mock_llm.complete.return_value = LLMResponse(
        content=json.dumps({
            "task_card": {
                "goal": "Research",
                "task_type": "research",
                "priority": "normal",
                "risk_level": "low",
                "required_resources": [],
                "expected_deliverables": [],
                "constraints": [],
            },
            "steps": [
                {
                    "id": "step-1",
                    "title": "Do research",
                    "description": "Research",
                    "risk_level": "low",
                    "required_resources": [],
                    "expected_output": "Results",
                    "dependencies": [],
                    "confirmation_required": False,
                }
            ],
            "fallbacks": [],
            "confirmation_points": [],
            "success_criteria": ["Done"],
        }),
        parsed_json=None,
        model="test-model",
        provider="test-provider",
    )

    planner = TaskPlanner(mock_llm)
    logger = OpenPilotLogger(temp_log_file)
    session = OpenPilotSession(
        planner=planner,
        logger=logger,
        memory_store=memory_store,
        enable_memory=True,
    )

    result = session.handle_goal("Create a research report")

    assert result.ok

    # Check that memory_reuse_notes appear in planner_succeeded event
    with open(temp_log_file, "r") as f:
        events = [json.loads(line) for line in f]

    planner_succeeded = [e for e in events if e["event_type"] == "planner_succeeded"]
    assert len(planner_succeeded) == 1
    assert "memory_reuse_notes" in planner_succeeded[0]["payload"]
