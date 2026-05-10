"""Example: OP-04 Preference Reuse Workflow

This example demonstrates how OpenPilot learns from user preferences
and automatically applies them in future tasks.
"""

from openpilot.memory_models import MemoryRecord, MemoryType
from openpilot.memory_store import MemoryStore

# Initialize memory store
memory_store = MemoryStore(data_dir="data/memory")

# Example 1: Save a user preference
print("=== Example 1: Saving User Preferences ===")
preference = MemoryRecord(
    id="pref-markdown-tables",
    memory_type=MemoryType.LONG_TERM,
    content="User prefers Markdown table format for reports",
    tags=["format", "report", "markdown", "table"],
    confidence=0.9,  # High confidence
    usage_count=5,
)
memory_store.save(preference)
print(f"Saved preference: {preference.content}")
print(f"Confidence: {preference.confidence}")
print()

# Example 2: Query relevant memories
print("=== Example 2: Retrieving Relevant Memories ===")
query_result = memory_store.query(
    query="create report with table",
    memory_types=[MemoryType.LONG_TERM],
    limit=5,
)
print(f"Query: 'create report with table'")
print(f"Found {len(query_result.memories)} relevant memories:")
for memory in query_result.memories:
    score = query_result.match_scores.get(memory.id, 0.0)
    print(f"  - {memory.content} (confidence: {memory.confidence}, match: {score:.2f})")
print()

# Example 3: High-confidence preferences are auto-applied
print("=== Example 3: Auto-Applied Preferences ===")
high_conf_memories = [m for m in query_result.memories if m.confidence >= 0.7]
print(f"High-confidence preferences (≥0.7): {len(high_conf_memories)}")
for memory in high_conf_memories:
    print(f"  ✓ Auto-applied: {memory.content}")
print()

# Example 4: Low-confidence preferences need confirmation
print("=== Example 4: Low-Confidence Preferences ===")
low_conf_pref = MemoryRecord(
    id="pref-blue-color",
    memory_type=MemoryType.LONG_TERM,
    content="User might prefer blue color scheme",
    tags=["color", "design", "ui"],
    confidence=0.4,  # Low confidence
    usage_count=1,
)
memory_store.save(low_conf_pref)
print(f"Saved low-confidence preference: {low_conf_pref.content}")
print(f"Confidence: {low_conf_pref.confidence}")
print("⚠ This preference will NOT be auto-applied (requires confirmation)")
print()

# Example 5: Usage tracking
print("=== Example 5: Usage Tracking ===")
print("When a preference is used, its usage_count increases and confidence improves:")
initial_usage = preference.usage_count
memory_store.update_usage(preference.id, MemoryType.LONG_TERM)
updated = memory_store.get_by_id(preference.id, MemoryType.LONG_TERM)
print(f"  Before: usage_count={initial_usage}, confidence={preference.confidence}")
print(f"  After:  usage_count={updated.usage_count}, confidence={updated.confidence:.2f}")
print()

# Example 6: CLI Usage
print("=== Example 6: CLI Usage ===")
print("Enable memory (default):")
print("  openpilot run --once 'Create a research report'")
print()
print("Disable memory for a specific run:")
print("  openpilot run --once 'Create a research report' --ignore-memory")
print()

print("=== Summary ===")
print("✓ High-confidence preferences (≥0.7) are automatically applied")
print("✓ Low-confidence preferences (<0.7) are retrieved but not auto-applied")
print("✓ Usage tracking improves confidence over time")
print("✓ Use --ignore-memory to disable preference retrieval")
