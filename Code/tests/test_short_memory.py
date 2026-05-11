"""Unit tests for short memory module."""

import pytest
from pathlib import Path
import tempfile

from memory.short_memory import (
    GitInfo,
    GitInfoCollector,
    ContextManager,
    MemorySketchGenerator,
    ShortMemory,
    Message
)
from models.memory_models import MemoryRecord, MemoryType


class TestGitInfoCollector:
    """Tests for GitInfoCollector."""

    def test_collect_non_git_repo(self):
        """Test collecting info from non-git directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            collector = GitInfoCollector(tmpdir)
            git_info = collector.collect()

            assert not git_info.is_git_repo
            assert git_info.current_branch == ""
            assert git_info.commit_hash == ""

    def test_git_info_to_prompt_text(self):
        """Test converting GitInfo to prompt text."""
        git_info = GitInfo(
            current_branch="main",
            commit_hash="abc123def456",
            commit_message="Initial commit",
            uncommitted_changes=True,
            uncommitted_files=["file1.py", "file2.py"],
            recent_commits=[
                {"hash": "abc123", "message": "Commit 1", "author": "User", "date": "1 day ago"}
            ],
            remote_tracking="origin/main",
            is_git_repo=True
        )

        text = git_info.to_prompt_text()
        assert "Branch: main" in text
        assert "Commit: abc123de" in text
        assert "Uncommitted changes: 2 files" in text
        assert "Tracking: origin/main" in text


class TestContextManager:
    """Tests for ContextManager."""

    def test_add_message(self):
        """Test adding messages."""
        manager = ContextManager()
        manager.add_message("user", "Hello")
        manager.add_message("assistant", "Hi there")

        messages = manager.get_messages()
        assert len(messages) == 2
        assert messages[0].role == "user"
        assert messages[0].content == "Hello"
        assert messages[1].role == "assistant"

    def test_max_messages_limit(self):
        """Test max messages limit."""
        manager = ContextManager(max_messages=5)

        for i in range(10):
            manager.add_message("user", f"Message {i}")

        messages = manager.get_messages()
        assert len(messages) == 5
        assert messages[0].content == "Message 5"

    def test_get_recent_messages(self):
        """Test getting recent messages."""
        manager = ContextManager()

        for i in range(10):
            manager.add_message("user", f"Message {i}")

        recent = manager.get_recent_messages(3)
        assert len(recent) == 3
        assert recent[0].content == "Message 7"

    def test_clear(self):
        """Test clearing messages."""
        manager = ContextManager()
        manager.add_message("user", "Hello")
        manager.clear()

        assert len(manager.get_messages()) == 0

    def test_compression_boundary(self):
        """Test compression boundary marking."""
        manager = ContextManager()

        for i in range(5):
            manager.add_message("user", f"Message {i}")

        manager.mark_compression_boundary()

        for i in range(5, 10):
            manager.add_message("user", f"Message {i}")

        after_compression = manager.get_messages_after_compression()
        assert len(after_compression) == 5
        assert after_compression[0].content == "Message 5"

    def test_to_prompt_text(self):
        """Test converting to prompt text."""
        manager = ContextManager()
        manager.add_message("user", "Hello")
        manager.add_message("assistant", "Hi")

        text = manager.to_prompt_text()
        assert "USER: Hello" in text
        assert "ASSISTANT: Hi" in text


class TestMemorySketchGenerator:
    """Tests for MemorySketchGenerator."""

    def test_generate_empty(self):
        """Test generating sketch with no memories."""
        generator = MemorySketchGenerator()
        sketch = generator.generate([])

        assert "No memories stored yet" in sketch

    def test_generate_with_memories(self):
        """Test generating sketch with memories."""
        generator = MemorySketchGenerator()

        memories = [
            MemoryRecord(
                id="1",
                memory_type=MemoryType.USER,
                content="User prefers concise responses",
                recall_frequency=5.0
            ),
            MemoryRecord(
                id="2",
                memory_type=MemoryType.FEEDBACK,
                content="Use pytest for testing",
                recall_frequency=3.0
            ),
            MemoryRecord(
                id="3",
                memory_type=MemoryType.USER,
                content="User is a Python developer",
                recall_frequency=2.0
            )
        ]

        sketch = generator.generate(memories)

        assert "Memory Vault Summary" in sketch
        assert "USER (2)" in sketch
        assert "FEEDBACK (1)" in sketch
        assert "User prefers concise responses" in sketch

    def test_generate_truncates_long_content(self):
        """Test that long content is truncated."""
        generator = MemorySketchGenerator()

        long_content = "A" * 200
        memories = [
            MemoryRecord(
                id="1",
                memory_type=MemoryType.USER,
                content=long_content
            )
        ]

        sketch = generator.generate(memories)
        assert "..." in sketch
        assert len(sketch) < len(long_content)


class TestShortMemory:
    """Tests for ShortMemory."""

    def test_initialization(self):
        """Test short memory initialization."""
        with tempfile.TemporaryDirectory() as tmpdir:
            memory = ShortMemory(repo_path=tmpdir)

            assert memory.git_collector is not None
            assert memory.context_manager is not None
            assert memory.sketch_generator is not None

    def test_get_git_info(self):
        """Test getting git info."""
        with tempfile.TemporaryDirectory() as tmpdir:
            memory = ShortMemory(repo_path=tmpdir)
            git_info = memory.get_git_info()

            assert git_info is not None
            assert not git_info.is_git_repo

    def test_add_and_get_context(self):
        """Test adding and getting context."""
        with tempfile.TemporaryDirectory() as tmpdir:
            memory = ShortMemory(repo_path=tmpdir)

            memory.add_message("user", "Hello")
            memory.add_message("assistant", "Hi")

            messages = memory.get_context()
            assert len(messages) == 2

    def test_get_memory_sketch(self):
        """Test getting memory sketch."""
        with tempfile.TemporaryDirectory() as tmpdir:
            memory = ShortMemory(repo_path=tmpdir)

            memories = [
                MemoryRecord(
                    id="1",
                    memory_type=MemoryType.USER,
                    content="Test memory"
                )
            ]

            sketch = memory.get_memory_sketch(memories)
            assert "Memory Vault Summary" in sketch

    def test_update_memory_sketch(self):
        """Test updating memory sketch."""
        with tempfile.TemporaryDirectory() as tmpdir:
            memory = ShortMemory(repo_path=tmpdir)

            memories = [
                MemoryRecord(
                    id="1",
                    memory_type=MemoryType.USER,
                    content="Test memory"
                )
            ]

            memory.update_memory_sketch(memories)
            sketch = memory.get_memory_sketch()

            assert "Test memory" in sketch

    def test_to_prompt_context(self):
        """Test converting to prompt context."""
        with tempfile.TemporaryDirectory() as tmpdir:
            memory = ShortMemory(repo_path=tmpdir)

            memories = [
                MemoryRecord(
                    id="1",
                    memory_type=MemoryType.USER,
                    content="Test memory"
                )
            ]
            memory.update_memory_sketch(memories)

            context = memory.to_prompt_context()

            assert "## Git Repository" in context
            assert "## Memory Sketch" in context

    def test_clear_cache(self):
        """Test clearing cache."""
        with tempfile.TemporaryDirectory() as tmpdir:
            memory = ShortMemory(repo_path=tmpdir)

            # Cache git info
            memory.get_git_info()
            assert memory._cached_git_info is not None

            # Clear cache
            memory.clear_cache()
            assert memory._cached_git_info is None
