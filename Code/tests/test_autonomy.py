"""Tests for OP-19 autonomy controller."""

from datetime import datetime, timedelta, timezone

import pytest

from openpilot.autonomy_controller import AutonomyController
from openpilot.autonomy_models import (
    AutonomyLevel,
    AutonomyProfile,
    UserFeedback,
)
from openpilot.memory_models import MemoryRecord, MemoryType
from openpilot.memory_store import MemoryStore
from openpilot.planner_models import PlanStep, RiskLevel, TaskCard, TaskType


@pytest.fixture
def memory_store():
    """Create a memory store for testing."""
    return MemoryStore()


@pytest.fixture
def autonomy_controller(memory_store):
    """Create an autonomy controller with memory store."""
    return AutonomyController(memory_store=memory_store)


@pytest.fixture
def sample_task_card():
    """Create a sample task card."""
    return TaskCard(
        id="task-1",
        title="Research Python best practices",
        description="Find and summarize Python coding standards",
        task_type=TaskType.RESEARCH,
        risk_level=RiskLevel.LOW,
        required_resources=["llm", "web_search"],
        goal="Research Python best practices",
    )


@pytest.fixture
def sample_step():
    """Create a sample plan step."""
    return PlanStep(
        id="step-1",
        title="Search for Python PEP 8",
        description="Search for Python PEP 8 documentation",
        risk_level=RiskLevel.LOW,
        confirmation_required=False,
        estimated_duration_minutes=5,
        expected_output="Python PEP 8 documentation summary",
    )


def test_default_autonomy_profile():
    """Test that default profile has conservative settings."""
    controller = AutonomyController()
    profile = controller.profile

    # Communication should require manual approval
    assert profile.task_type_autonomy[TaskType.COMMUNICATION.value] == AutonomyLevel.MANUAL_REQUIRED.value

    # High risk should require confirmation
    assert profile.risk_level_autonomy[RiskLevel.HIGH.value] == AutonomyLevel.CONFIRM_EACH_TIME.value

    # Low risk can auto-run
    assert profile.risk_level_autonomy[RiskLevel.LOW.value] == AutonomyLevel.AUTO_RUN_LOW_RISK.value


def test_low_risk_research_auto_runs(autonomy_controller, sample_task_card, sample_step):
    """Test that low-risk research tasks can auto-run with high confidence."""
    # Add positive historical memory
    memory = MemoryRecord(
        id="mem-1",
        memory_type=MemoryType.TASK,
        content="Successfully completed research task",
        tags=["research", "low"],
        confidence=0.9,
        usage_count=5,
    )
    autonomy_controller.memory_store.save(memory)

    decision = autonomy_controller.decide_autonomy(
        step=sample_step,
        task_card=sample_task_card,
        goal="Research Python best practices",
    )

    # Should have high confidence due to historical success
    assert decision.confidence >= 0.7
    # Low risk + high confidence = auto-run
    assert decision.autonomy_level in [AutonomyLevel.AUTO_RUN_LOW_RISK, AutonomyLevel.NOTIFY_THEN_RUN]
    assert not decision.should_ask_user


def test_high_risk_always_requires_confirmation(autonomy_controller, sample_task_card):
    """Test that high-risk tasks always require confirmation."""
    high_risk_step = PlanStep(
        id="step-1",
        title="Send email to all users",
        description="Send email to all users",
        risk_level=RiskLevel.HIGH,
        confirmation_required=True,
        estimated_duration_minutes=5,
        expected_output="Email sent confirmation",
    )

    high_risk_card = TaskCard(
        id="task-1",
        title="Send mass email",
        description="Email all users about update",
        task_type=TaskType.COMMUNICATION,
        risk_level=RiskLevel.HIGH,
        required_resources=["email"],
        goal="Send email to all users",
    )

    decision = autonomy_controller.decide_autonomy(
        step=high_risk_step,
        task_card=high_risk_card,
        goal="Send email to all users",
    )

    # High risk always requires confirmation
    assert decision.should_ask_user
    assert decision.autonomy_level in [AutonomyLevel.CONFIRM_EACH_TIME, AutonomyLevel.MANUAL_REQUIRED]
    assert decision.intervention_reason is not None


def test_forbidden_risk_requires_manual(autonomy_controller, sample_task_card):
    """Test that forbidden tasks require manual intervention."""
    forbidden_step = PlanStep(
        id="step-1",
        title="Delete production database",
        description="Delete production database",
        risk_level=RiskLevel.FORBIDDEN,
        confirmation_required=True,
        estimated_duration_minutes=1,
        expected_output="Database deleted",
    )

    forbidden_card = TaskCard(
        id="task-1",
        title="Delete database",
        description="Remove all data",
        task_type=TaskType.CODING,
        risk_level=RiskLevel.FORBIDDEN,
        required_resources=["python_runtime"],
        goal="Delete production database",
    )

    decision = autonomy_controller.decide_autonomy(
        step=forbidden_step,
        task_card=forbidden_card,
        goal="Delete production database",
    )

    # Forbidden always requires manual
    assert decision.should_ask_user
    assert decision.autonomy_level == AutonomyLevel.MANUAL_REQUIRED
    assert decision.intervention_reason is not None


def test_low_confidence_downgrades_autonomy(autonomy_controller, sample_task_card, sample_step):
    """Test that low confidence downgrades autonomy level."""
    # Test the downgrade logic by using a medium-risk step with low historical success
    # This ensures the base level starts higher and can be downgraded
    medium_risk_step = PlanStep(
        id="step-1",
        title="Modify configuration file",
        description="Modify configuration file",
        risk_level=RiskLevel.MEDIUM,
        confirmation_required=False,
        expected_output="Configuration updated",
    )

    medium_risk_card = TaskCard(
        id="task-1",
        title="Update config",
        description="Update configuration",
        task_type=TaskType.FILE_WORKFLOW,
        risk_level=RiskLevel.MEDIUM,
        required_resources=["local_file"],
        goal="Update configuration",
    )

    # Add negative memories for file workflow tasks
    for i in range(5):
        memory = MemoryRecord(
            id=f"mem-{i}",
            memory_type=MemoryType.TASK,
            content=f"Failed file_workflow task {i}",
            tags=["file_workflow", "medium"],
            confidence=0.1,
            usage_count=1,
        )
        autonomy_controller.memory_store.save(memory)

    decision = autonomy_controller.decide_autonomy(
        step=medium_risk_step,
        task_card=medium_risk_card,
        goal="Update configuration",
    )

    # With low historical success, confidence should be lower
    # and autonomy should require confirmation
    assert decision.confidence < 0.6
    assert decision.should_ask_user or decision.autonomy_level in [
        AutonomyLevel.CONFIRM_EACH_TIME,
        AutonomyLevel.NOTIFY_THEN_RUN
    ]


def test_preference_match_increases_confidence(autonomy_controller, sample_task_card, sample_step):
    """Test that matching preferences increase confidence."""
    # Add high-confidence preference
    preference = MemoryRecord(
        id="pref-1",
        memory_type=MemoryType.LONG_TERM,
        content="User prefers detailed research with multiple sources",
        tags=["research", "preference"],
        confidence=0.9,
        usage_count=10,
    )
    autonomy_controller.memory_store.save(preference)

    decision = autonomy_controller.decide_autonomy(
        step=sample_step,
        task_card=sample_task_card,
        goal="Research Python best practices with multiple sources",
    )

    # Preference match should boost confidence
    assert decision.confidence >= 0.6


def test_recency_bonus_for_recent_successes(autonomy_controller, sample_task_card, sample_step):
    """Test that recent successes provide confidence bonus."""
    # Add recent successful memory
    recent_time = datetime.now(timezone.utc) - timedelta(days=2)
    memory = MemoryRecord(
        id="mem-1",
        memory_type=MemoryType.TASK,
        content="Successfully completed research task",
        tags=["research", "low"],
        confidence=0.8,
        usage_count=3,
        last_used=recent_time.isoformat(),
    )
    autonomy_controller.memory_store.save(memory)

    decision = autonomy_controller.decide_autonomy(
        step=sample_step,
        task_card=sample_task_card,
        goal="Research Python best practices",
    )

    # Recent success should boost confidence
    assert decision.confidence >= 0.6


def test_frequency_bonus_for_common_patterns(autonomy_controller, sample_task_card, sample_step):
    """Test that frequently used patterns get confidence bonus."""
    # Add multiple high-usage memories
    for i in range(3):
        memory = MemoryRecord(
            id=f"mem-{i}",
            memory_type=MemoryType.TASK,
            content=f"Research task {i}",
            tags=["research", "low"],
            confidence=0.7,
            usage_count=20,  # High usage count
        )
        autonomy_controller.memory_store.save(memory)

    decision = autonomy_controller.decide_autonomy(
        step=sample_step,
        task_card=sample_task_card,
        goal="Research Python best practices",
    )

    # Frequent usage should boost confidence
    assert decision.confidence >= 0.6


def test_feedback_recording_updates_memory(autonomy_controller, sample_task_card, sample_step):
    """Test that user feedback is recorded in memory."""
    feedback = UserFeedback(
        step_id="step-1",
        feedback_type="accepted",
        timestamp=datetime.now(timezone.utc).isoformat(),
    )

    autonomy_controller.record_feedback(
        feedback=feedback,
        step=sample_step,
        task_card=sample_task_card,
    )

    # Query memory to verify feedback was recorded
    result = autonomy_controller.memory_store.query(
        query="research low",
        memory_types=[MemoryType.TASK],
        limit=5,
    )

    assert len(result.memories) > 0
    # Positive feedback should have high confidence
    assert any(m.confidence >= 0.7 for m in result.memories)


def test_negative_feedback_lowers_confidence(autonomy_controller, sample_task_card, sample_step):
    """Test that negative feedback lowers confidence."""
    feedback = UserFeedback(
        step_id="step-1",
        feedback_type="rejected",
        timestamp=datetime.now(timezone.utc).isoformat(),
        user_comment="Not what I wanted",
    )

    autonomy_controller.record_feedback(
        feedback=feedback,
        step=sample_step,
        task_card=sample_task_card,
    )

    # Query memory to verify feedback was recorded
    result = autonomy_controller.memory_store.query(
        query="research low rejected",
        memory_types=[MemoryType.TASK],
        limit=5,
    )

    assert len(result.memories) > 0
    # Negative feedback should have low confidence
    assert any(m.confidence <= 0.3 for m in result.memories)


def test_custom_autonomy_profile():
    """Test that custom autonomy profile can be provided."""
    custom_profile = AutonomyProfile(
        task_type_autonomy={
            TaskType.RESEARCH.value: AutonomyLevel.AUTO_RUN_LOW_RISK.value,
        },
        risk_level_autonomy={
            RiskLevel.LOW.value: AutonomyLevel.AUTO_RUN_LOW_RISK.value,
        },
        global_confidence_threshold=0.8,  # Higher threshold
    )

    controller = AutonomyController(autonomy_profile=custom_profile)
    assert controller.profile.global_confidence_threshold == 0.8


def test_no_memory_store_uses_defaults(sample_task_card, sample_step):
    """Test that controller works without memory store."""
    controller = AutonomyController(memory_store=None)

    decision = controller.decide_autonomy(
        step=sample_step,
        task_card=sample_task_card,
        goal="Research Python best practices",
    )

    # Should use default neutral confidence
    assert 0.4 <= decision.confidence <= 0.6
    assert decision.autonomy_level is not None


def test_decision_reason_is_human_readable(autonomy_controller, sample_task_card, sample_step):
    """Test that decision reasons are human-readable."""
    decision = autonomy_controller.decide_autonomy(
        step=sample_step,
        task_card=sample_task_card,
        goal="Research Python best practices",
    )

    assert decision.decision_reason is not None
    assert len(decision.decision_reason) > 0
    # Should mention confidence
    assert "confidence" in decision.decision_reason.lower()
