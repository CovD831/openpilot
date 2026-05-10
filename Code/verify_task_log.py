"""Simple verification script for task_log module without pytest."""

import sys
import tempfile
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from openpilot.task_log import (
    TaskLogEntry,
    TaskLogEventType,
    TaskLogStore,
    create_task_log_entry,
)


def test_basic_functionality():
    """Test basic task log functionality."""
    print("Testing task log module...")

    # Test 1: Create entry
    print("✓ Test 1: Creating task log entry...")
    entry = create_task_log_entry(
        task_id="test_task_1",
        event_type=TaskLogEventType.CREATED,
    )
    assert entry.task_id == "test_task_1"
    assert entry.event_type == TaskLogEventType.CREATED
    print("  ✓ Entry created successfully")

    # Test 2: Blocked event validation
    print("✓ Test 2: Testing blocked event validation...")
    try:
        entry = create_task_log_entry(
            task_id="test_task_2",
            event_type=TaskLogEventType.BLOCKED,
            blocked_reason="waiting for dependency",
        )
        assert entry.blocked_reason == "waiting for dependency"
        print("  ✓ Blocked event with reason works")
    except ValueError:
        print("  ✗ Failed: blocked event with reason should work")
        return False

    # Test 3: Store and retrieve
    print("✓ Test 3: Testing store and retrieve...")
    with tempfile.TemporaryDirectory() as tmpdir:
        store = TaskLogStore(tmpdir)

        entry1 = create_task_log_entry(
            task_id="task1",
            event_type=TaskLogEventType.CREATED,
        )
        store.append(entry1)

        entry2 = create_task_log_entry(
            task_id="task1",
            event_type=TaskLogEventType.STATUS_CHANGED,
            old_status="planned",
            new_status="in_progress",
        )
        store.append(entry2)

        entries = store.get_entries("task1")
        assert len(entries) == 2
        assert entries[0].event_type == TaskLogEventType.CREATED
        assert entries[1].event_type == TaskLogEventType.STATUS_CHANGED
        print("  ✓ Store and retrieve works")

    # Test 4: Filter by event type
    print("✓ Test 4: Testing filter by event type...")
    with tempfile.TemporaryDirectory() as tmpdir:
        store = TaskLogStore(tmpdir)

        store.append(create_task_log_entry(
            task_id="task1",
            event_type=TaskLogEventType.CREATED,
        ))
        store.append(create_task_log_entry(
            task_id="task1",
            event_type=TaskLogEventType.BLOCKED,
            blocked_reason="test reason",
        ))

        blocked_entries = store.get_entries(
            task_id="task1",
            event_type=TaskLogEventType.BLOCKED,
        )
        assert len(blocked_entries) == 1
        assert blocked_entries[0].blocked_reason == "test reason"
        print("  ✓ Filter by event type works")

    # Test 5: Status history
    print("✓ Test 5: Testing status history...")
    with tempfile.TemporaryDirectory() as tmpdir:
        store = TaskLogStore(tmpdir)

        store.append(create_task_log_entry(
            task_id="task1",
            event_type=TaskLogEventType.STATUS_CHANGED,
            old_status="planned",
            new_status="in_progress",
        ))
        store.append(create_task_log_entry(
            task_id="task1",
            event_type=TaskLogEventType.STATUS_CHANGED,
            old_status="in_progress",
            new_status="done",
        ))

        history = store.get_status_history("task1")
        assert len(history) == 2
        assert history[0].new_status == "in_progress"
        assert history[1].new_status == "done"
        print("  ✓ Status history works")

    print("\n✅ All tests passed!")
    return True


if __name__ == "__main__":
    try:
        success = test_basic_functionality()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"\n❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
