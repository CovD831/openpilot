"""Local JSONL-based memory storage for the four-layer memory system."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from openpilot.memory_models import MemoryRecord, MemoryQueryResult, MemoryType


class MemoryStore:
    """Local file-based memory storage using JSONL format."""

    def __init__(self, data_dir: str | Path = "data/memory"):
        """Initialize memory store.

        Args:
            data_dir: Directory to store memory files (one JSONL per memory type)
        """
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)

        # One file per memory type
        self.files = {
            MemoryType.SHORT_TERM: self.data_dir / "short_term.jsonl",
            MemoryType.LONG_TERM: self.data_dir / "long_term.jsonl",
            MemoryType.TASK: self.data_dir / "task.jsonl",
            MemoryType.SKILL: self.data_dir / "skill.jsonl",
        }

    def save(self, memory: MemoryRecord) -> MemoryRecord:
        """Save a memory record.

        Args:
            memory: Memory record to save

        Returns:
            The saved memory record (with ID if not provided)
        """
        # Generate ID if not provided
        if not memory.id:
            memory.id = str(uuid.uuid4())

        # Update timestamp
        memory.timestamp = datetime.now(timezone.utc).isoformat()

        # Append to appropriate file
        file_path = self.files[memory.memory_type]
        with open(file_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(memory.model_dump(), ensure_ascii=False) + "\n")

        return memory

    def load_all(self, memory_type: MemoryType) -> list[MemoryRecord]:
        """Load all memories of a specific type.

        Args:
            memory_type: Type of memory to load

        Returns:
            List of memory records
        """
        file_path = self.files[memory_type]
        if not file_path.exists():
            return []

        memories = []
        with open(file_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        data = json.loads(line)
                        memories.append(MemoryRecord(**data))
                    except (json.JSONDecodeError, ValueError):
                        # Skip invalid lines
                        continue

        return memories

    def query(
        self,
        query: str,
        memory_types: list[MemoryType] | None = None,
        tags: list[str] | None = None,
        limit: int = 10,
    ) -> MemoryQueryResult:
        """Query memories by keyword matching.

        Args:
            query: Search query string
            memory_types: Types of memory to search (default: all)
            tags: Filter by tags (default: no filter)
            limit: Maximum number of results

        Returns:
            Query result with matched memories and scores
        """
        if memory_types is None:
            memory_types = list(MemoryType)

        query_lower = query.lower()
        query_words = set(query_lower.split())

        all_matches = []

        for mem_type in memory_types:
            memories = self.load_all(mem_type)

            for memory in memories:
                # Filter by tags if specified
                if tags and not any(tag in memory.tags for tag in tags):
                    continue

                # Calculate match score based on keyword overlap
                content_lower = memory.content.lower()
                memory_words = set(content_lower.split())

                # Exact match in content
                if query_lower in content_lower:
                    score = 1.0
                # Tag match
                elif any(query_lower in tag.lower() for tag in memory.tags):
                    score = 0.9
                # Word overlap
                else:
                    overlap = len(query_words & memory_words)
                    if overlap > 0:
                        score = min(0.8, overlap / len(query_words))
                    else:
                        continue

                # Boost score by confidence and usage
                score *= (0.5 + 0.5 * memory.confidence)
                score *= min(1.0, 1.0 + 0.1 * memory.usage_count)

                all_matches.append((memory, score))

        # Sort by score and limit
        all_matches.sort(key=lambda x: x[1], reverse=True)
        all_matches = all_matches[:limit]

        memories = [m for m, _ in all_matches]
        match_scores = {m.id: score for m, score in all_matches}

        return MemoryQueryResult(
            query=query,
            memories=memories,
            match_scores=match_scores,
        )

    def update_usage(self, memory_id: str, memory_type: MemoryType) -> bool:
        """Update usage count and last_used timestamp for a memory.

        Args:
            memory_id: ID of the memory to update
            memory_type: Type of memory

        Returns:
            True if updated, False if not found
        """
        memories = self.load_all(memory_type)
        updated = False

        for memory in memories:
            if memory.id == memory_id:
                memory.usage_count += 1
                memory.last_used = datetime.utcnow().isoformat()
                # Increase confidence slightly with each use (cap at 1.0)
                memory.confidence = min(1.0, memory.confidence + 0.05)
                updated = True
                break

        if updated:
            # Rewrite the entire file
            self._rewrite_file(memory_type, memories)

        return updated

    def delete(self, memory_id: str, memory_type: MemoryType) -> bool:
        """Delete a memory record.

        Args:
            memory_id: ID of the memory to delete
            memory_type: Type of memory

        Returns:
            True if deleted, False if not found
        """
        memories = self.load_all(memory_type)
        original_count = len(memories)
        memories = [m for m in memories if m.id != memory_id]

        if len(memories) < original_count:
            self._rewrite_file(memory_type, memories)
            return True

        return False

    def clear_short_term(self) -> None:
        """Clear all short-term memories (e.g., at session end)."""
        file_path = self.files[MemoryType.SHORT_TERM]
        if file_path.exists():
            file_path.unlink()

    def _rewrite_file(self, memory_type: MemoryType, memories: list[MemoryRecord]) -> None:
        """Rewrite entire memory file with updated records.

        Args:
            memory_type: Type of memory
            memories: List of memory records to write
        """
        file_path = self.files[memory_type]
        with open(file_path, "w", encoding="utf-8") as f:
            for memory in memories:
                f.write(json.dumps(memory.model_dump(), ensure_ascii=False) + "\n")

    def get_by_id(self, memory_id: str, memory_type: MemoryType) -> MemoryRecord | None:
        """Get a specific memory by ID.

        Args:
            memory_id: ID of the memory
            memory_type: Type of memory

        Returns:
            Memory record if found, None otherwise
        """
        memories = self.load_all(memory_type)
        for memory in memories:
            if memory.id == memory_id:
                return memory
        return None
