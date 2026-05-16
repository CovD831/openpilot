"""Context Manager agent facade.

User messages are preserved verbatim. Agent messages pass through a lightweight
compression path before being added to the underlying short-memory context.
"""

from __future__ import annotations

from typing import Any

from memory.short_memory import ContextManager


class ContextManagerAgent:
    """Store and output conversation context following Memory Module rules."""

    def __init__(
        self,
        context_manager: ContextManager | None = None,
        *,
        max_agent_chars: int = 1200,
    ) -> None:
        self.context_manager = context_manager or ContextManager()
        self.max_agent_chars = max_agent_chars

    def add_user_message(self, content: str, metadata: dict[str, Any] | None = None) -> None:
        """Store a user's words exactly as provided."""
        self.context_manager.add_message("user", content, metadata)

    def add_agent_message(self, content: str, metadata: dict[str, Any] | None = None) -> None:
        """Store compressed agent history."""
        compressed = self._compress_agent_history(content)
        agent_metadata = {"compressed": compressed != content, **(metadata or {})}
        self.context_manager.add_message("assistant", compressed, agent_metadata)

    def output_context(self, limit: int | None = None) -> dict[str, Any]:
        """Return stored context in structured and prompt-ready forms."""
        messages = self.context_manager.get_messages(limit)
        return {
            "messages": [
                {
                    "role": message.role,
                    "content": message.content,
                    "timestamp": str(message.timestamp),
                    "metadata": dict(message.metadata),
                }
                for message in messages
            ],
            "prompt_text": self.context_manager.to_prompt_text(limit),
        }

    def _compress_agent_history(self, content: str) -> str:
        if len(content) <= self.max_agent_chars:
            return content
        head = content[: self.max_agent_chars // 2].strip()
        tail = content[-self.max_agent_chars // 2 :].strip()
        return (
            "[COMPRESSED AGENT HISTORY]\n"
            f"{head}\n"
            "[...compressed...]\n"
            f"{tail}"
        )
