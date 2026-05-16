"""Build structured memory context for agents."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from memory.agents.memory_vault_agent import MemoryVaultAgent
from memory.memory_models import MemoryRecord, MemoryType
from memory.memory_store import MemoryStore
from memory.project_manager import ProjectManager
from memory.short_memory import ShortMemory


class MemoryContextBuilder:
    """Combine dialog, memory records, project files, and environment context."""

    DEFAULT_MEMORY_TYPES = [
        MemoryType.USER,
        MemoryType.FEEDBACK,
        MemoryType.PROJECT,
        MemoryType.REFERENCE,
        MemoryType.LONG_TERM,
        MemoryType.SHORT_TERM,
    ]

    def __init__(
        self,
        *,
        short_memory: ShortMemory | None = None,
        memory_store: MemoryStore | None = None,
        memory_vault_agent: MemoryVaultAgent | None = None,
        project_manager: ProjectManager | None = None,
    ) -> None:
        self.short_memory = short_memory or ShortMemory()
        self.memory_store = memory_store or MemoryStore()
        self.memory_vault_agent = memory_vault_agent
        self.project_manager = project_manager

    def build(
        self,
        query: str,
        *,
        project_path: str | Path | None = None,
        include_environment: bool = True,
        limit: int = 10,
        system_prompt: str = "",
    ) -> dict[str, Any]:
        """Build context for a query."""
        query = query.strip()
        system_prompt = system_prompt.strip()
        project_path_obj = Path(project_path).expanduser() if project_path else None
        project_manager = self.project_manager
        if project_manager is None and project_path_obj is not None:
            project_manager = ProjectManager(project_path_obj)

        related_files = []
        if project_manager is not None and project_path_obj is not None and project_path_obj.exists():
            project_manager.update(project_path_obj)
            related_files = project_manager.search(query or project_path_obj.name, limit=limit)

        related_memories = self._related_memories(query, limit)
        environment_context = (
            self._environment_context(project_path_obj)
            if include_environment
            else []
        )
        dialog_context = self._dialog_context(limit)

        payload = {
            "query": query,
            "project_path": str(project_path_obj) if project_path_obj else "",
            "system_prompt": system_prompt,
            "dialog_context": dialog_context,
            "related_memories": related_memories,
            "related_files": related_files,
            "environment_context": environment_context,
        }
        payload["prompt_text"] = self._prompt_text(payload)
        return payload

    def _dialog_context(self, limit: int) -> list[dict[str, Any]]:
        messages = self.short_memory.get_context(limit=limit)
        return [
            {
                "role": message.role,
                "content": message.content,
                "timestamp": str(message.timestamp),
                "metadata": dict(message.metadata),
            }
            for message in messages
        ]

    def _related_memories(self, query: str, limit: int) -> list[dict[str, Any]]:
        if not query:
            return []
        if self.memory_vault_agent is not None:
            try:
                reminders = self.memory_vault_agent.remind(query, limit=limit)
                if reminders:
                    return [self._vault_memory_payload(item) for item in reminders]
            except Exception:
                pass
        try:
            result = self.memory_store.query(
                query,
                memory_types=self.DEFAULT_MEMORY_TYPES,
                limit=limit,
            )
        except Exception:
            return []
        return [self._memory_record_payload(memory) for memory in result.memories]

    def _environment_context(self, project_path: Path | None) -> list[dict[str, Any]]:
        try:
            memories = self.memory_store.load_all(MemoryType.SHORT_TERM)
        except Exception:
            return []

        project_name = project_path.name if project_path else ""
        env_memories = [
            memory
            for memory in memories
            if "project_environment" in memory.tags
            and (not project_name or project_name in memory.tags)
        ][-3:]
        return [self._memory_record_payload(memory) for memory in env_memories]

    def _memory_record_payload(self, memory: MemoryRecord) -> dict[str, Any]:
        return {
            "id": memory.id,
            "type": memory.memory_type.value,
            "content": memory.content,
            "tags": memory.tags,
            "confidence": memory.confidence,
            "metadata": memory.metadata,
        }

    def _vault_memory_payload(self, memory: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": memory.get("id", ""),
            "type": memory.get("type", MemoryType.PROJECT.value),
            "content": memory.get("content", ""),
            "tags": list(memory.get("tags") or []),
            "confidence": float(memory.get("confidence", 0.5)),
            "metadata": dict(memory.get("metadata") or {}),
            "score": float(memory.get("score", 0.0)),
        }

    def _prompt_text(self, payload: dict[str, Any]) -> str:
        sections = []
        if payload.get("system_prompt"):
            sections.append("## System Prompt\n" + str(payload["system_prompt"]))

        if payload["dialog_context"]:
            lines = [
                f"{item['role'].upper()}: {item['content']}"
                for item in payload["dialog_context"]
            ]
            sections.append("## Dialog Context\n" + "\n\n".join(lines))

        if payload["related_files"]:
            lines = [
                f"- {item['path']}: {item['description']}"
                for item in payload["related_files"]
            ]
            sections.append("## Related Files\n" + "\n".join(lines))

        if payload["related_memories"]:
            lines = [
                f"- [{item['type']}] {item['content']}"
                for item in payload["related_memories"]
            ]
            sections.append("## Related Memories\n" + "\n".join(lines))

        if payload["environment_context"]:
            lines = [f"- {item['content']}" for item in payload["environment_context"]]
            sections.append("## Environment Context\n" + "\n".join(lines))

        return "\n\n".join(sections)
