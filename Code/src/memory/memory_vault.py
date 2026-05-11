"""Memory vault with graph-based structure and semantic search.

This module provides the core memory vault functionality with:
- Graph-based memory storage
- Semantic search using embeddings
- Memory relationships and clustering
- Recall function with relevance scoring
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from core.embedding import EmbeddingService
from core.graph import Graph, GraphNode, GraphEdge, GraphType
from models.memory_models import MemoryRecord, MemoryType


class MemoryVault:
    """Graph-based memory vault with semantic search."""

    def __init__(
        self,
        embedding_service: EmbeddingService,
        storage_dir: str | Path = "data/memory_vault",
        auto_relate: bool = True,
        similarity_threshold: float = 0.7
    ):
        """Initialize memory vault.

        Args:
            embedding_service: Service for generating embeddings
            storage_dir: Directory for storing memory vault
            auto_relate: Automatically detect related memories
            similarity_threshold: Threshold for automatic relationship detection
        """
        self.embedding_service = embedding_service
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.auto_relate = auto_relate
        self.similarity_threshold = similarity_threshold

        # Graph for memory relationships
        self.graph = Graph(GraphType.DIRECTED)

        # Cache for quick lookup
        self._memory_cache: dict[str, MemoryRecord] = {}

        # Load existing vault
        self._load_vault()

    def add_memory(
        self,
        content: str,
        memory_type: MemoryType,
        tags: list[str] | None = None,
        confidence: float = 0.8,
        metadata: dict[str, Any] | None = None
    ) -> str:
        """Add a new memory to the vault.

        Args:
            content: Memory content
            memory_type: Type of memory
            tags: Optional tags
            confidence: Confidence score
            metadata: Optional metadata

        Returns:
            Memory ID
        """
        # Generate ID
        memory_id = str(uuid.uuid4())

        # Generate embedding
        embedding = self.embedding_service.embed_text(content)

        # Create memory record
        memory = MemoryRecord(
            id=memory_id,
            memory_type=memory_type,
            content=content,
            tags=tags or [],
            confidence=confidence,
            metadata=metadata or {},
            embedding=embedding,
            recall_frequency=0.0
        )

        # Add to graph
        node = GraphNode(
            id=memory_id,
            type=memory_type.value,
            data={
                "content": content,
                "tags": tags or [],
                "confidence": confidence,
                "embedding": embedding,
                "recall_frequency": 0.0,
                "usage_count": 0
            },
            metadata=metadata or {}
        )
        self.graph.add_node(node)

        # Cache memory
        self._memory_cache[memory_id] = memory

        # Auto-relate to similar memories
        if self.auto_relate:
            self._auto_relate_memory(memory_id, embedding)

        # Save vault
        self._save_vault()

        return memory_id

    def recall(
        self,
        query: str,
        top_k: int = 10,
        memory_types: list[MemoryType] | None = None,
        min_confidence: float = 0.0,
        boost_recent: bool = True,
        boost_frequent: bool = True
    ) -> list[tuple[MemoryRecord, float]]:
        """Recall memories relevant to query.

        Args:
            query: Search query
            top_k: Number of results to return
            memory_types: Filter by memory types
            min_confidence: Minimum confidence threshold
            boost_recent: Boost recently created memories
            boost_frequent: Boost frequently recalled memories

        Returns:
            List of (memory, score) tuples sorted by relevance
        """
        if not self._memory_cache:
            return []

        # Generate query embedding
        query_embedding = self.embedding_service.embed_text(query)

        # Get candidate memories
        candidates = list(self._memory_cache.values())

        # Filter by type
        if memory_types:
            candidates = [m for m in candidates if m.memory_type in memory_types]

        # Filter by confidence
        candidates = [m for m in candidates if m.confidence >= min_confidence]

        if not candidates:
            return []

        # Compute similarity scores
        results = []
        for memory in candidates:
            if memory.embedding is None:
                continue

            # Base similarity score
            similarity = self.embedding_service.compute_similarity(
                query_embedding,
                memory.embedding,
                method="cosine"
            )

            # Apply boosts
            score = similarity

            if boost_recent:
                # Boost recent memories (decay over time)
                age_days = self._get_memory_age_days(memory)
                recency_boost = 1.0 / (1.0 + age_days / 30.0)  # Decay over 30 days
                score *= (0.7 + 0.3 * recency_boost)

            if boost_frequent:
                # Boost frequently recalled memories
                frequency_boost = min(1.0, memory.recall_frequency / 10.0)
                score *= (0.8 + 0.2 * frequency_boost)

            # Confidence boost
            score *= (0.5 + 0.5 * memory.confidence)

            results.append((memory, score))

        # Sort by score
        results.sort(key=lambda x: x[1], reverse=True)

        # Update recall frequency for top results
        for memory, _ in results[:top_k]:
            memory.recall_frequency += 1.0
            memory.usage_count += 1
            memory.last_used = datetime.now(timezone.utc).isoformat()

            # Update in graph
            node = self.graph.get_node(memory.id)
            if node:
                node.data["recall_frequency"] = memory.recall_frequency
                node.data["usage_count"] = memory.usage_count

        # Save updates
        self._save_vault()

        return results[:top_k]

    def update_memory(
        self,
        memory_id: str,
        content: str | None = None,
        tags: list[str] | None = None,
        confidence: float | None = None,
        metadata: dict[str, Any] | None = None
    ) -> bool:
        """Update an existing memory.

        Args:
            memory_id: Memory ID
            content: New content (if provided)
            tags: New tags (if provided)
            confidence: New confidence (if provided)
            metadata: New metadata (if provided)

        Returns:
            True if updated successfully
        """
        memory = self._memory_cache.get(memory_id)
        if not memory:
            return False

        # Update fields
        if content is not None:
            memory.content = content
            # Regenerate embedding
            memory.embedding = self.embedding_service.embed_text(content)

        if tags is not None:
            memory.tags = tags

        if confidence is not None:
            memory.confidence = confidence

        if metadata is not None:
            memory.metadata.update(metadata)

        # Update timestamp
        memory.timestamp = datetime.now(timezone.utc).isoformat()

        # Update in graph
        node = self.graph.get_node(memory_id)
        if node:
            if content is not None:
                node.data["content"] = content
                node.data["embedding"] = memory.embedding
            if tags is not None:
                node.data["tags"] = tags
            if confidence is not None:
                node.data["confidence"] = confidence
            node.updated_at = memory.timestamp

        # Re-relate if content changed
        if content is not None and self.auto_relate and memory.embedding:
            self._auto_relate_memory(memory_id, memory.embedding)

        self._save_vault()
        return True

    def delete_memory(self, memory_id: str) -> bool:
        """Delete a memory.

        Args:
            memory_id: Memory ID

        Returns:
            True if deleted successfully
        """
        if memory_id not in self._memory_cache:
            return False

        # Remove from cache
        del self._memory_cache[memory_id]

        # Remove from graph
        self.graph.remove_node(memory_id)

        self._save_vault()
        return True

    def find_related(
        self,
        memory_id: str,
        max_depth: int = 2,
        relationship_types: list[str] | None = None
    ) -> list[MemoryRecord]:
        """Find memories related to a given memory.

        Args:
            memory_id: Memory ID
            max_depth: Maximum relationship depth
            relationship_types: Filter by relationship types

        Returns:
            List of related memories
        """
        if memory_id not in self._memory_cache:
            return []

        related_ids = set()

        # BFS to find related memories
        visited = {memory_id}
        queue = [(memory_id, 0)]

        while queue:
            current_id, depth = queue.pop(0)

            if depth >= max_depth:
                continue

            # Get neighbors
            neighbors = self.graph.get_neighbors(current_id)

            for neighbor in neighbors:
                if neighbor.id in visited:
                    continue

                # Check relationship type if specified
                if relationship_types:
                    edge = self.graph.get_edge(current_id, neighbor.id)
                    if edge and edge.edge_type not in relationship_types:
                        continue

                visited.add(neighbor.id)
                related_ids.add(neighbor.id)
                queue.append((neighbor.id, depth + 1))

        # Return memory records
        return [self._memory_cache[mid] for mid in related_ids if mid in self._memory_cache]

    def detect_contradictions(self, threshold: float = 0.8) -> list[tuple[MemoryRecord, MemoryRecord, float]]:
        """Detect potentially contradicting memories.

        Args:
            threshold: Similarity threshold for contradiction detection

        Returns:
            List of (memory1, memory2, similarity) tuples
        """
        contradictions = []
        memories = list(self._memory_cache.values())

        # Look for high similarity with different confidence or contradictory content
        for i, mem1 in enumerate(memories):
            if mem1.embedding is None:
                continue

            for mem2 in memories[i + 1:]:
                if mem2.embedding is None:
                    continue

                # Skip if same type
                if mem1.memory_type != mem2.memory_type:
                    continue

                similarity = self.embedding_service.compute_similarity(
                    mem1.embedding,
                    mem2.embedding,
                    method="cosine"
                )

                # High similarity but different confidence might indicate contradiction
                if similarity > threshold and abs(mem1.confidence - mem2.confidence) > 0.3:
                    contradictions.append((mem1, mem2, similarity))

        return contradictions

    def get_memory_sketch(self, max_items: int = 20) -> str:
        """Generate memory sketch for short memory.

        Args:
            max_items: Maximum items to include

        Returns:
            Memory sketch text
        """
        if not self._memory_cache:
            return "No memories stored yet."

        memories = list(self._memory_cache.values())

        # Group by type
        by_type: dict[str, list[MemoryRecord]] = {}
        for memory in memories:
            mem_type = memory.memory_type.value
            if mem_type not in by_type:
                by_type[mem_type] = []
            by_type[mem_type].append(memory)

        lines = [f"Memory Vault ({len(memories)} total):"]

        for mem_type, mems in sorted(by_type.items()):
            lines.append(f"\n{mem_type.upper()} ({len(mems)}):")

            # Sort by recall frequency
            sorted_mems = sorted(
                mems,
                key=lambda m: m.recall_frequency + m.usage_count * 0.1,
                reverse=True
            )

            # Show top items
            for mem in sorted_mems[:5]:
                content = mem.content
                if len(content) > 80:
                    content = content[:77] + "..."
                lines.append(f"  - {content}")

            if len(sorted_mems) > 5:
                lines.append(f"  ... and {len(sorted_mems) - 5} more")

        return "\n".join(lines)

    def get_statistics(self) -> dict[str, Any]:
        """Get memory vault statistics.

        Returns:
            Dictionary with statistics
        """
        memories = list(self._memory_cache.values())

        by_type = {}
        for memory in memories:
            mem_type = memory.memory_type.value
            by_type[mem_type] = by_type.get(mem_type, 0) + 1

        total_recall_frequency = sum(m.recall_frequency for m in memories)
        avg_recall_frequency = total_recall_frequency / len(memories) if memories else 0

        return {
            "total_memories": len(memories),
            "by_type": by_type,
            "total_relationships": self.graph.edge_count(),
            "avg_recall_frequency": avg_recall_frequency,
            "embedding_cache_size": self.embedding_service.get_cache_size()
        }

    def _auto_relate_memory(self, memory_id: str, embedding: list[float]) -> None:
        """Automatically detect and create relationships.

        Args:
            memory_id: Memory ID
            embedding: Memory embedding
        """
        # Find similar memories
        candidate_embeddings = []
        candidate_ids = []

        for mid, mem in self._memory_cache.items():
            if mid == memory_id or mem.embedding is None:
                continue
            candidate_embeddings.append(mem.embedding)
            candidate_ids.append(mid)

        if not candidate_embeddings:
            return

        # Find similar memories
        similar = self.embedding_service.find_similar(
            embedding,
            candidate_embeddings,
            top_k=5,
            threshold=self.similarity_threshold
        )

        # Create relationships
        for idx, similarity in similar:
            related_id = candidate_ids[idx]

            # Add edge if not exists
            if not self.graph.has_edge(memory_id, related_id):
                edge = GraphEdge(
                    source_id=memory_id,
                    target_id=related_id,
                    edge_type="relates_to",
                    weight=similarity
                )
                self.graph.add_edge(edge)

    def _get_memory_age_days(self, memory: MemoryRecord) -> float:
        """Get memory age in days.

        Args:
            memory: Memory record

        Returns:
            Age in days
        """
        try:
            created = datetime.fromisoformat(memory.timestamp.replace('Z', '+00:00'))
            now = datetime.now(timezone.utc)
            delta = now - created
            return delta.total_seconds() / 86400.0
        except Exception:
            return 0.0

    def _save_vault(self) -> None:
        """Save memory vault to disk."""
        # Save graph
        graph_path = self.storage_dir / "memory_graph.json"
        self.graph.save_json(graph_path)

    def _load_vault(self) -> None:
        """Load memory vault from disk."""
        graph_path = self.storage_dir / "memory_graph.json"

        if not graph_path.exists():
            return

        try:
            # Load graph
            self.graph = Graph.load_json(graph_path)

            # Rebuild memory cache from graph
            for node in self.graph.get_all_nodes():
                memory = MemoryRecord(
                    id=node.id,
                    memory_type=MemoryType(node.type),
                    content=node.data.get("content", ""),
                    tags=node.data.get("tags", []),
                    confidence=node.data.get("confidence", 0.5),
                    embedding=node.data.get("embedding"),
                    recall_frequency=node.data.get("recall_frequency", 0.0),
                    usage_count=node.data.get("usage_count", 0),
                    timestamp=node.created_at,
                    metadata=node.metadata
                )
                self._memory_cache[node.id] = memory

        except Exception as e:
            print(f"Warning: Failed to load memory vault: {e}")
