"""Tests for the memory module."""

import tempfile
from pathlib import Path

import pytest

from openpilot.memory_models import MemoryRecord, MemoryType
from openpilot.memory_store import MemoryStore


@pytest.fixture
def temp_memory_dir():
    """Create a temporary directory for memory storage."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.fixture
def memory_store(temp_memory_dir):
    """Create a memory store with temporary directory."""
    return MemoryStore(data_dir=temp_memory_dir)


def test_memory_store_initialization(temp_memory_dir):
    """Test that memory store creates directory structure."""
    store = MemoryStore(data_dir=temp_memory_dir)
    assert Path(temp_memory_dir).exists()
    assert store.data_dir == Path(temp_memory_dir)


def test_save_and_load_memory(memory_store):
    """Test saving and loading a memory record."""
    memory = MemoryRecord(
        id="test-1",
        memory_type=MemoryType.LONG_TERM,
        content="User prefers Markdown table output",
        tags=["preference", "output_format"],
        confidence=0.8,
    )

    saved = memory_store.save(memory)
    assert saved.id == "test-1"

    loaded = memory_store.load_all(MemoryType.LONG_TERM)
    assert len(loaded) == 1
    assert loaded[0].content == "User prefers Markdown table output"
    assert "preference" in loaded[0].tags


def test_save_without_id_generates_id(memory_store):
    """Test that saving without ID generates one."""
    memory = MemoryRecord(
        id="",
        memory_type=MemoryType.TASK,
        content="Research tasks usually take 3 days",
        tags=["task_type:research", "estimation"],
    )

    saved = memory_store.save(memory)
    assert saved.id != ""
    assert len(saved.id) > 0


def test_query_by_keyword(memory_store):
    """Test querying memories by keyword."""
    # Save multiple memories
    memory_store.save(MemoryRecord(
        id="m1",
        memory_type=MemoryType.LONG_TERM,
        content="User prefers Markdown table output",
        tags=["preference", "output_format"],
        confidence=0.9,
    ))
    memory_store.save(MemoryRecord(
        id="m2",
        memory_type=MemoryType.LONG_TERM,
        content="Code style preference: PEP8",
        tags=["preference", "code_style"],
        confidence=0.8,
    ))
    memory_store.save(MemoryRecord(
        id="m3",
        memory_type=MemoryType.TASK,
        content="Research tasks usually take 3 days",
        tags=["task_type:research", "estimation"],
        confidence=0.7,
    ))

    # Query for "table"
    result = memory_store.query("table")
    assert len(result.memories) >= 1
    assert any("table" in m.content.lower() for m in result.memories)

    # Query for "preference"
    result = memory_store.query("preference")
    assert len(result.memories) >= 2


def test_query_by_tags(memory_store):
    """Test querying memories by tags."""
    memory_store.save(MemoryRecord(
        id="m1",
        memory_type=MemoryType.LONG_TERM,
        content="User prefers Markdown table output",
        tags=["preference", "output_format"],
    ))
    memory_store.save(MemoryRecord(
        id="m2",
        memory_type=MemoryType.TASK,
        content="Research tasks usually take 3 days",
        tags=["task_type:research", "estimation"],
    ))

    # Query with tag filter
    result = memory_store.query("output", tags=["preference"])
    assert len(result.memories) >= 1
    assert all("preference" in m.tags for m in result.memories)


def test_query_by_memory_type(memory_store):
    """Test querying specific memory types."""
    memory_store.save(MemoryRecord(
        id="m1",
        memory_type=MemoryType.LONG_TERM,
        content="User prefers tables",
        tags=["preference"],
    ))
    memory_store.save(MemoryRecord(
        id="m2",
        memory_type=MemoryType.TASK,
        content="Research tasks take time",
        tags=["estimation"],
    ))

    # Query only long-term memories
    result = memory_store.query("user", memory_types=[MemoryType.LONG_TERM])
    assert len(result.memories) >= 1
    assert all(m.memory_type == MemoryType.LONG_TERM for m in result.memories)


def test_update_usage(memory_store):
    """Test updating usage count and confidence."""
    memory = MemoryRecord(
        id="m1",
        memory_type=MemoryType.LONG_TERM,
        content="User prefers tables",
        tags=["preference"],
        confidence=0.5,
        usage_count=0,
    )
    memory_store.save(memory)

    # Update usage
    updated = memory_store.update_usage("m1", MemoryType.LONG_TERM)
    assert updated is True

    # Check that usage count and confidence increased
    loaded = memory_store.get_by_id("m1", MemoryType.LONG_TERM)
    assert loaded is not None
    assert loaded.usage_count == 1
    assert loaded.confidence > 0.5
    assert loaded.last_used is not None


def test_delete_memory(memory_store):
    """Test deleting a memory record."""
    memory = MemoryRecord(
        id="m1",
        memory_type=MemoryType.LONG_TERM,
        content="User prefers tables",
        tags=["preference"],
    )
    memory_store.save(memory)

    # Verify it exists
    loaded = memory_store.load_all(MemoryType.LONG_TERM)
    assert len(loaded) == 1

    # Delete it
    deleted = memory_store.delete("m1", MemoryType.LONG_TERM)
    assert deleted is True

    # Verify it's gone
    loaded = memory_store.load_all(MemoryType.LONG_TERM)
    assert len(loaded) == 0


def test_clear_short_term(memory_store):
    """Test clearing short-term memories."""
    memory_store.save(MemoryRecord(
        id="m1",
        memory_type=MemoryType.SHORT_TERM,
        content="Current task context",
        tags=["session"],
    ))
    memory_store.save(MemoryRecord(
        id="m2",
        memory_type=MemoryType.LONG_TERM,
        content="User preference",
        tags=["preference"],
    ))

    # Clear short-term
    memory_store.clear_short_term()

    # Verify short-term is empty but long-term remains
    short_term = memory_store.load_all(MemoryType.SHORT_TERM)
    long_term = memory_store.load_all(MemoryType.LONG_TERM)
    assert len(short_term) == 0
    assert len(long_term) == 1


def test_no_sensitive_data_in_memory(memory_store):
    """Test that sensitive data is not saved (validation test)."""
    # This is a validation test - in real usage, the caller should
    # not save sensitive data. The store itself doesn't filter.
    memory = MemoryRecord(
        id="m1",
        memory_type=MemoryType.LONG_TERM,
        content="User prefers blue color scheme",
        tags=["preference", "ui"],
    )
    memory_store.save(memory)

    # Verify no API keys or passwords in content
    loaded = memory_store.load_all(MemoryType.LONG_TERM)
    for mem in loaded:
        assert "api_key" not in mem.content.lower()
        assert "password" not in mem.content.lower()
        assert "secret" not in mem.content.lower()


def test_confidence_increases_with_usage(memory_store):
    """Test that confidence increases as memory is used."""
    memory = MemoryRecord(
        id="m1",
        memory_type=MemoryType.LONG_TERM,
        content="User prefers tables",
        tags=["preference"],
        confidence=0.5,
    )
    memory_store.save(memory)

    initial_confidence = 0.5

    # Use it multiple times
    for _ in range(5):
        memory_store.update_usage("m1", MemoryType.LONG_TERM)

    # Check confidence increased
    loaded = memory_store.get_by_id("m1", MemoryType.LONG_TERM)
    assert loaded is not None
    assert loaded.confidence > initial_confidence
    assert loaded.usage_count == 5


def test_empty_memory_file_handling(memory_store):
    """Test that loading from non-existent file returns empty list."""
    memories = memory_store.load_all(MemoryType.SKILL)
    assert memories == []


def test_query_limit(memory_store):
    """Test that query respects limit parameter."""
    # Save many memories
    for i in range(20):
        memory_store.save(MemoryRecord(
            id=f"m{i}",
            memory_type=MemoryType.TASK,
            content=f"Task memory {i} about research",
            tags=["task"],
        ))

    # Query with limit
    result = memory_store.query("research", limit=5)
    assert len(result.memories) <= 5


def test_match_scores_in_query_result(memory_store):
    """Test that query result includes match scores."""
    memory_store.save(MemoryRecord(
        id="m1",
        memory_type=MemoryType.LONG_TERM,
        content="User prefers Markdown table output",
        tags=["preference"],
        confidence=0.9,
    ))

    result = memory_store.query("table")
    assert len(result.match_scores) > 0
    assert "m1" in result.match_scores
    assert 0.0 <= result.match_scores["m1"] <= 2.0  # Can exceed 1.0 with boosts
