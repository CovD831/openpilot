"""Memory Vault agent facade."""

from __future__ import annotations

from typing import Any, Callable

from core.graph import GraphEdge
from memory.memory_models import MemoryRecord, MemoryType


class MemoryVaultAgent:
    """Expose basic memory graph operations, remind, and confidence evaluation."""

    def __init__(
        self,
        memory_vault: Any | None = None,
        memory_store: Any | None = None,
        logger: Any | None = None,
        session_id_getter: Callable[[], str | None] | None = None,
    ) -> None:
        self.memory_vault = memory_vault
        self.memory_store = memory_store
        self.logger = logger
        self.session_id_getter = session_id_getter or (lambda: None)

    def add_node(
        self,
        content: str,
        memory_type: MemoryType = MemoryType.PROJECT,
        tags: list[str] | None = None,
        confidence: float = 0.8,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        self._log_agent(
            "memory_node_add_started",
            input_summary={"memory_type": memory_type.value, "tags": tags or []},
            success=None,
        )
        if self.memory_vault is not None and hasattr(self.memory_vault, "add_memory"):
            memory_id = self.memory_vault.add_memory(content, memory_type, tags, confidence, metadata)
        else:
            if self.memory_store is None:
                self._log_agent("memory_node_add_failed", success=False, error="No memory vault or store is configured.")
                raise RuntimeError("No memory vault or store is configured.")
            record = self.memory_store.save(
                MemoryRecord(
                    id="",
                    memory_type=memory_type,
                    content=content,
                    tags=tags or [],
                    confidence=confidence,
                    metadata=metadata or {},
                )
            )
            memory_id = record.id
        self._log_agent(
            "memory_node_added",
            output_summary={"id": memory_id, "memory_type": memory_type.value},
            success=True,
        )
        return memory_id

    def add_edge(self, source_id: str, target_id: str, relevance: float = 1.0) -> bool:
        relevance = max(0.0, min(1.0, float(relevance)))
        if self.memory_vault is not None and hasattr(self.memory_vault, "graph"):
            graph = self.memory_vault.graph
            add_edge = getattr(graph, "add_edge", None)
            if callable(add_edge):
                if graph.has_edge(source_id, target_id, edge_type="relevance"):
                    self._log_agent(
                        "memory_edge_exists",
                        input_summary={"source_id": source_id, "target_id": target_id, "relevance": relevance},
                        success=True,
                    )
                    return True
                add_edge(
                    GraphEdge(
                        source_id=source_id,
                        target_id=target_id,
                        edge_type="relevance",
                        weight=relevance,
                        metadata={"relevance": relevance},
                    )
                )
                save = getattr(self.memory_vault, "_save_vault", None)
                if callable(save):
                    save()
                self._log_agent(
                    "memory_edge_added",
                    input_summary={"source_id": source_id, "target_id": target_id, "relevance": relevance},
                    success=True,
                )
                return True
        self._log_agent(
            "memory_edge_add_failed",
            input_summary={"source_id": source_id, "target_id": target_id, "relevance": relevance},
            success=False,
            error="No memory graph is configured.",
        )
        return False

    def remind(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        query = query.strip()
        if not query:
            return []
        if self.memory_vault is not None and hasattr(self.memory_vault, "recall"):
            reminders = [self._memory_payload(memory, score) for memory, score in self.memory_vault.recall(query, top_k=limit)]
            self._log_agent(
                "memory_reminded",
                input_summary={"query": query, "limit": limit, "source": "memory_vault"},
                output_summary={"count": len(reminders)},
                success=True,
            )
            return reminders
        if self.memory_store is None:
            self._log_agent(
                "memory_remind_skipped",
                input_summary={"query": query, "limit": limit},
                output_summary={"count": 0},
                success=True,
            )
            return []
        result = self.memory_store.query(query, limit=limit)
        reminders = [
            {
                "id": memory.id,
                "content": memory.content,
                "score": result.match_scores.get(memory.id, 0.0),
                "type": memory.memory_type.value,
                "tags": memory.tags,
                "confidence": memory.confidence,
                "metadata": memory.metadata,
            }
            for memory in result.memories
        ]
        self._log_agent(
            "memory_reminded",
            input_summary={"query": query, "limit": limit, "source": "memory_store"},
            output_summary={"count": len(reminders)},
            success=True,
        )
        return reminders

    def confidence_evaluate(self, query: str) -> tuple[float, str]:
        memories = self.remind(query, limit=3)
        if not memories:
            return 0.0, ""
        best = memories[0]
        score = float(best.get("score", 0.0))
        confidence = float(best.get("confidence", 0.5))
        final_confidence = max(0.0, min(1.0, (score * 0.7) + (confidence * 0.3)))
        self._log_agent(
            "memory_confidence_evaluated",
            input_summary={"query": query},
            output_summary={"confidence": final_confidence, "memory_id": best.get("id")},
            success=True,
        )
        return final_confidence, str(best.get("content", ""))

    def _memory_payload(self, memory: MemoryRecord, score: float) -> dict[str, Any]:
        return {
            "id": memory.id,
            "type": memory.memory_type.value,
            "content": memory.content,
            "score": score,
            "tags": memory.tags,
            "confidence": memory.confidence,
            "metadata": memory.metadata,
        }

    def _log_agent(
        self,
        event_type: str,
        *,
        success: bool | None,
        input_summary: Any | None = None,
        output_summary: Any | None = None,
        error: str | None = None,
    ) -> None:
        if not self.logger or not hasattr(self.logger, "log_structured_event"):
            return
        self.logger.log_structured_event(
            source_type="agent",
            source_name="memory.agents.memory_vault_agent",
            phase="memory_graph",
            event_type=event_type,
            session_id=self.session_id_getter() or "unknown",
            turn_id=1,
            success=success,
            input_summary=input_summary,
            output_summary=output_summary,
            error=error,
        )
