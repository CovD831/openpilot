"""Short memory module for OpenPilot.

This module provides short-term memory management including:
- Git information collection
- Context management
- Memory sketch generation
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel


@dataclass
class GitInfo:
    """Git repository information."""

    current_branch: str
    commit_hash: str
    commit_message: str
    uncommitted_changes: bool
    uncommitted_files: list[str]
    recent_commits: list[dict[str, str]]
    remote_tracking: str | None
    is_git_repo: bool

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "current_branch": self.current_branch,
            "commit_hash": self.commit_hash,
            "commit_message": self.commit_message,
            "uncommitted_changes": self.uncommitted_changes,
            "uncommitted_files": self.uncommitted_files,
            "recent_commits": self.recent_commits,
            "remote_tracking": self.remote_tracking,
            "is_git_repo": self.is_git_repo
        }

    def to_prompt_text(self) -> str:
        """Convert to human-readable prompt text."""
        if not self.is_git_repo:
            return "Not a git repository"

        lines = [
            f"Branch: {self.current_branch}",
            f"Commit: {self.commit_hash[:8]} - {self.commit_message}",
        ]

        if self.remote_tracking:
            lines.append(f"Tracking: {self.remote_tracking}")

        if self.uncommitted_changes:
            lines.append(f"Uncommitted changes: {len(self.uncommitted_files)} files")
            if self.uncommitted_files:
                lines.append("  " + ", ".join(self.uncommitted_files[:5]))
                if len(self.uncommitted_files) > 5:
                    lines.append(f"  ... and {len(self.uncommitted_files) - 5} more")

        if self.recent_commits:
            lines.append(f"\nRecent commits ({len(self.recent_commits)}):")
            for commit in self.recent_commits[:3]:
                lines.append(f"  {commit['hash'][:8]} - {commit['message']}")

        return "\n".join(lines)


class GitInfoCollector:
    """Collects git repository information."""

    def __init__(self, repo_path: str | Path = "."):
        """Initialize collector.

        Args:
            repo_path: Path to git repository
        """
        self.repo_path = Path(repo_path)

    def _run_git_command(self, *args: str) -> str | None:
        """Run a git command and return output.

        Args:
            *args: Git command arguments

        Returns:
            Command output or None if failed
        """
        try:
            result = subprocess.run(
                ["git", "-C", str(self.repo_path)] + list(args),
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                return result.stdout.strip()
            return None
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return None

    def collect(self) -> GitInfo:
        """Collect git information.

        Returns:
            GitInfo object with repository information
        """
        # Check if it's a git repo
        is_git_repo = self._run_git_command("rev-parse", "--git-dir") is not None

        if not is_git_repo:
            return GitInfo(
                current_branch="",
                commit_hash="",
                commit_message="",
                uncommitted_changes=False,
                uncommitted_files=[],
                recent_commits=[],
                remote_tracking=None,
                is_git_repo=False
            )

        # Get current branch
        current_branch = self._run_git_command("rev-parse", "--abbrev-ref", "HEAD") or "unknown"

        # Get current commit
        commit_hash = self._run_git_command("rev-parse", "HEAD") or ""
        commit_message = self._run_git_command("log", "-1", "--pretty=%s") or ""

        # Check for uncommitted changes
        status_output = self._run_git_command("status", "--porcelain") or ""
        uncommitted_changes = bool(status_output)
        uncommitted_files = []

        if uncommitted_changes:
            for line in status_output.split("\n"):
                if line.strip():
                    # Extract filename from status line
                    parts = line.strip().split(maxsplit=1)
                    if len(parts) == 2:
                        uncommitted_files.append(parts[1])

        # Get recent commits
        recent_commits = []
        log_output = self._run_git_command(
            "log", "-10", "--pretty=format:%H|%s|%an|%ar"
        )

        if log_output:
            for line in log_output.split("\n"):
                parts = line.split("|")
                if len(parts) == 4:
                    recent_commits.append({
                        "hash": parts[0],
                        "message": parts[1],
                        "author": parts[2],
                        "date": parts[3]
                    })

        # Get remote tracking
        remote_tracking = self._run_git_command(
            "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"
        )

        return GitInfo(
            current_branch=current_branch,
            commit_hash=commit_hash,
            commit_message=commit_message,
            uncommitted_changes=uncommitted_changes,
            uncommitted_files=uncommitted_files,
            recent_commits=recent_commits,
            remote_tracking=remote_tracking,
            is_git_repo=True
        )


class Message(BaseModel):
    """A message in the conversation context."""
    role: str  # "user", "assistant", "system"
    content: str
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    attributes: dict[str, Any] = field(default_factory=dict)


class ContextManager:
    """Manages conversation context."""

    def __init__(self, max_messages: int = 100):
        """Initialize context manager.

        Args:
            max_messages: Maximum number of messages to keep
        """
        self.max_messages = max_messages
        self.messages: list[Message] = []
        self._compression_boundary: int | None = None

    def add_message(self, role: str, content: str, attributes: dict[str, Any] | None = None) -> None:
        """Add a message to context.

        Args:
            role: Message role (user, assistant, system)
            content: Message content
            attributes: Optional attributes
        """
        message = Message(
            role=role,
            content=content,
            attributes=attributes or {}
        )
        self.messages.append(message)

        # Trim if exceeds max
        if len(self.messages) > self.max_messages:
            self.messages = self.messages[-self.max_messages:]

    def get_messages(self, limit: int | None = None) -> list[Message]:
        """Get messages from context.

        Args:
            limit: Optional limit on number of messages

        Returns:
            List of messages
        """
        if limit:
            return self.messages[-limit:]
        return self.messages.copy()

    def get_recent_messages(self, count: int = 10) -> list[Message]:
        """Get recent messages.

        Args:
            count: Number of recent messages

        Returns:
            List of recent messages
        """
        return self.messages[-count:]

    def clear(self) -> None:
        """Clear all messages."""
        self.messages.clear()
        self._compression_boundary = None

    def mark_compression_boundary(self) -> None:
        """Mark current position as compression boundary."""
        self._compression_boundary = len(self.messages)

    def get_messages_after_compression(self) -> list[Message]:
        """Get messages after last compression boundary.

        Returns:
            Messages after compression boundary
        """
        if self._compression_boundary is None:
            return self.messages.copy()
        return self.messages[self._compression_boundary:]

    def to_prompt_text(self, limit: int | None = None) -> str:
        """Convert context to prompt text.

        Args:
            limit: Optional limit on number of messages

        Returns:
            Formatted context text
        """
        messages = self.get_messages(limit)
        lines = []

        for msg in messages:
            lines.append(f"{msg.role.upper()}: {msg.content}")

        return "\n\n".join(lines)


class MemorySketchGenerator:
    """Generates memory sketch from memory vault."""

    def __init__(self, max_items: int = 20):
        """Initialize generator.

        Args:
            max_items: Maximum number of items in sketch
        """
        self.max_items = max_items

    def generate(self, memories: list[Any]) -> str:
        """Generate memory sketch.

        Args:
            memories: List of memory records

        Returns:
            Memory sketch text
        """
        if not memories:
            return "No memories stored yet."

        # Group by type
        by_type: dict[str, list[Any]] = {}
        for memory in memories:
            mem_type = memory.memory_type if hasattr(memory, 'memory_type') else 'unknown'
            if mem_type not in by_type:
                by_type[mem_type] = []
            by_type[mem_type].append(memory)

        lines = [f"Memory Vault Summary ({len(memories)} total):"]

        for mem_type, mems in sorted(by_type.items()):
            lines.append(f"\n{mem_type.upper()} ({len(mems)}):")

            # Sort by recall frequency or usage count
            sorted_mems = sorted(
                mems,
                key=lambda m: (
                    getattr(m, 'recall_frequency', 0) +
                    getattr(m, 'usage_count', 0) * 0.1
                ),
                reverse=True
            )

            # Show top items
            for mem in sorted_mems[:5]:
                content = mem.content if hasattr(mem, 'content') else str(mem)
                # Truncate long content
                if len(content) > 100:
                    content = content[:97] + "..."
                lines.append(f"  - {content}")

            if len(sorted_mems) > 5:
                lines.append(f"  ... and {len(sorted_mems) - 5} more")

        return "\n".join(lines)


class ShortMemory:
    """Short-term memory management."""

    def __init__(
        self,
        repo_path: str | Path = ".",
        max_context_messages: int = 100
    ):
        """Initialize short memory.

        Args:
            repo_path: Path to git repository
            max_context_messages: Maximum context messages
        """
        self.git_collector = GitInfoCollector(repo_path)
        self.context_manager = ContextManager(max_context_messages)
        self.sketch_generator = MemorySketchGenerator()
        self._cached_git_info: GitInfo | None = None
        self._cached_memory_sketch: str | None = None

    def get_git_info(self, use_cache: bool = True) -> GitInfo:
        """Get git repository information.

        Args:
            use_cache: Whether to use cached info

        Returns:
            GitInfo object
        """
        if use_cache and self._cached_git_info:
            return self._cached_git_info

        git_info = self.git_collector.collect()
        self._cached_git_info = git_info
        return git_info

    def get_context(self, limit: int | None = None) -> list[Message]:
        """Get conversation context.

        Args:
            limit: Optional limit on messages

        Returns:
            List of messages
        """
        return self.context_manager.get_messages(limit)

    def add_message(self, role: str, content: str, attributes: dict[str, Any] | None = None) -> None:
        """Add message to context.

        Args:
            role: Message role
            content: Message content
            attributes: Optional attributes
        """
        self.context_manager.add_message(role, content, attributes)

    def get_memory_sketch(self, memories: list[Any] | None = None) -> str:
        """Get memory sketch.

        Args:
            memories: Optional list of memories (if None, uses cached)

        Returns:
            Memory sketch text
        """
        if memories is None and self._cached_memory_sketch:
            return self._cached_memory_sketch

        if memories is not None:
            sketch = self.sketch_generator.generate(memories)
            self._cached_memory_sketch = sketch
            return sketch

        return self._cached_memory_sketch or "No memory sketch available."

    def update_memory_sketch(self, memories: list[Any]) -> None:
        """Update cached memory sketch.

        Args:
            memories: List of memory records
        """
        self._cached_memory_sketch = self.sketch_generator.generate(memories)

    def to_prompt_context(self, include_git: bool = True, include_sketch: bool = True) -> str:
        """Convert short memory to prompt context.

        Args:
            include_git: Include git information
            include_sketch: Include memory sketch

        Returns:
            Formatted prompt context
        """
        sections = []

        if include_git:
            git_info = self.get_git_info()
            sections.append("## Git Repository\n" + git_info.to_prompt_text())

        if include_sketch:
            sketch = self.get_memory_sketch()
            sections.append("## Memory Sketch\n" + sketch)

        return "\n\n".join(sections)

    def clear_cache(self) -> None:
        """Clear cached information."""
        self._cached_git_info = None
        self._cached_memory_sketch = None
