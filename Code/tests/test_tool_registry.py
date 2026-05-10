"""Tests for tool registry and built-in tools."""

import pytest
from pathlib import Path
import tempfile

from openpilot.tool_models import (
    PermissionLevel,
    ToolCapability,
    ToolDefinition,
    ToolInputSchema,
    ToolOutputSchema,
)
from openpilot.tool_registry import ToolRegistry, ToolRegistryError
from openpilot.builtin_tools import (
    FILE_READER_DEFINITION,
    FILE_WRITER_DEFINITION,
    LLM_SUMMARIZER_DEFINITION,
    file_reader_executor,
    file_writer_executor,
    register_builtin_tools,
)


# ============================================================================
# Tool Registry Tests
# ============================================================================

def test_registry_register_and_get():
    """Test basic tool registration and retrieval."""
    registry = ToolRegistry()

    def dummy_executor(params):
        return {"result": "ok"}

    tool_def = ToolDefinition(
        name="test_tool",
        display_name="Test Tool",
        description="A test tool",
        capabilities=[ToolCapability.FILE_READ],
        permission_level=PermissionLevel.LOW,
        output_schema=ToolOutputSchema(type="object", description="Test output")
    )

    registry.register(tool_def, dummy_executor)

    # Get tool
    retrieved = registry.get("test_tool")
    assert retrieved is not None
    assert retrieved.name == "test_tool"
    assert retrieved.display_name == "Test Tool"

    # Get executor
    executor = registry.get_executor("test_tool")
    assert executor is not None
    assert executor({"test": "param"}) == {"result": "ok"}


def test_registry_duplicate_registration():
    """Test that duplicate registration fails without override."""
    registry = ToolRegistry()

    def dummy_executor(params):
        return {}

    tool_def = ToolDefinition(
        name="test_tool",
        display_name="Test Tool",
        description="A test tool",
        capabilities=[],
        output_schema=ToolOutputSchema(type="object", description="Test")
    )

    registry.register(tool_def, dummy_executor)

    # Try to register again without override
    with pytest.raises(ToolRegistryError, match="already registered"):
        registry.register(tool_def, dummy_executor)

    # Should work with override
    registry.register(tool_def, dummy_executor, allow_override=True)


def test_registry_list_all():
    """Test listing all tools."""
    registry = ToolRegistry()

    def dummy_executor(params):
        return {}

    for i in range(3):
        tool_def = ToolDefinition(
            name=f"tool_{i}",
            display_name=f"Tool {i}",
            description=f"Tool {i}",
            capabilities=[],
            output_schema=ToolOutputSchema(type="object", description="Test")
        )
        registry.register(tool_def, dummy_executor)

    tools = registry.list_all()
    assert len(tools) == 3
    assert {t.name for t in tools} == {"tool_0", "tool_1", "tool_2"}


def test_registry_find_by_capability():
    """Test finding tools by capability."""
    registry = ToolRegistry()

    def dummy_executor(params):
        return {}

    # Register tools with different capabilities
    tool1 = ToolDefinition(
        name="reader",
        display_name="Reader",
        description="Reads files",
        capabilities=[ToolCapability.FILE_READ],
        permission_level=PermissionLevel.LOW,
        output_schema=ToolOutputSchema(type="object", description="Test")
    )

    tool2 = ToolDefinition(
        name="writer",
        display_name="Writer",
        description="Writes files",
        capabilities=[ToolCapability.FILE_WRITE],
        permission_level=PermissionLevel.MEDIUM,
        output_schema=ToolOutputSchema(type="object", description="Test")
    )

    tool3 = ToolDefinition(
        name="rw",
        display_name="Read/Write",
        description="Reads and writes",
        capabilities=[ToolCapability.FILE_READ, ToolCapability.FILE_WRITE],
        permission_level=PermissionLevel.LOW,
        output_schema=ToolOutputSchema(type="object", description="Test")
    )

    registry.register(tool1, dummy_executor)
    registry.register(tool2, dummy_executor)
    registry.register(tool3, dummy_executor)

    # Find by FILE_READ capability
    readers = registry.find_by_capability(ToolCapability.FILE_READ)
    assert len(readers) == 2
    assert {t.name for t in readers} == {"reader", "rw"}

    # Find by FILE_WRITE capability with permission limit
    writers = registry.find_by_capability(
        ToolCapability.FILE_WRITE,
        max_permission=PermissionLevel.LOW
    )
    assert len(writers) == 1
    assert writers[0].name == "rw"


def test_registry_find_by_tags():
    """Test finding tools by tags."""
    registry = ToolRegistry()

    def dummy_executor(params):
        return {}

    tool1 = ToolDefinition(
        name="tool1",
        display_name="Tool 1",
        description="Tool 1",
        capabilities=[],
        tags=["file", "read"],
        output_schema=ToolOutputSchema(type="object", description="Test")
    )

    tool2 = ToolDefinition(
        name="tool2",
        display_name="Tool 2",
        description="Tool 2",
        capabilities=[],
        tags=["file", "write"],
        output_schema=ToolOutputSchema(type="object", description="Test")
    )

    tool3 = ToolDefinition(
        name="tool3",
        display_name="Tool 3",
        description="Tool 3",
        capabilities=[],
        tags=["network"],
        output_schema=ToolOutputSchema(type="object", description="Test")
    )

    registry.register(tool1, dummy_executor)
    registry.register(tool2, dummy_executor)
    registry.register(tool3, dummy_executor)

    # Find tools with "file" tag
    file_tools = registry.find_by_tags(["file"])
    assert len(file_tools) == 2
    assert {t.name for t in file_tools} == {"tool1", "tool2"}

    # Find tools with both "file" and "read" tags
    read_tools = registry.find_by_tags(["file", "read"], match_all=True)
    assert len(read_tools) == 1
    assert read_tools[0].name == "tool1"


def test_registry_unregister():
    """Test unregistering tools."""
    registry = ToolRegistry()

    def dummy_executor(params):
        return {}

    tool_def = ToolDefinition(
        name="test_tool",
        display_name="Test Tool",
        description="A test tool",
        capabilities=[],
        output_schema=ToolOutputSchema(type="object", description="Test")
    )

    registry.register(tool_def, dummy_executor)
    assert registry.get("test_tool") is not None

    registry.unregister("test_tool")
    assert registry.get("test_tool") is None

    # Unregistering non-existent tool should fail
    with pytest.raises(ToolRegistryError, match="not found"):
        registry.unregister("nonexistent")


def test_registry_stats():
    """Test registry statistics."""
    registry = ToolRegistry()
    register_builtin_tools(registry)

    stats = registry.get_stats()
    assert stats["total_tools"] == 3
    assert "by_permission" in stats
    assert "by_capability" in stats


# ============================================================================
# File Reader Tool Tests
# ============================================================================

def test_file_reader_success():
    """Test successful file reading."""
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt') as f:
        f.write("Hello, World!")
        temp_path = f.name

    try:
        result = file_reader_executor({"file_path": temp_path})
        assert result["content"] == "Hello, World!"
        assert result["size_bytes"] == 13
        assert result["encoding"] == "utf-8"
    finally:
        Path(temp_path).unlink()


def test_file_reader_not_found():
    """Test file reader with non-existent file."""
    with pytest.raises(FileNotFoundError):
        file_reader_executor({"file_path": "/nonexistent/file.txt"})


def test_file_reader_too_large():
    """Test file reader with file exceeding size limit."""
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt') as f:
        f.write("x" * 1024 * 1024)  # 1 MB
        temp_path = f.name

    try:
        # Set max size to 0.5 MB
        with pytest.raises(ValueError, match="File too large"):
            file_reader_executor({
                "file_path": temp_path,
                "max_size_mb": 0.5
            })
    finally:
        Path(temp_path).unlink()


# ============================================================================
# File Writer Tool Tests
# ============================================================================

def test_file_writer_success():
    """Test successful file writing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        file_path = Path(tmpdir) / "test.txt"

        result = file_writer_executor({
            "file_path": str(file_path),
            "content": "Test content"
        })

        assert result["created"] is True
        assert result["bytes_written"] > 0
        assert file_path.exists()
        assert file_path.read_text() == "Test content"


def test_file_writer_overwrite():
    """Test file writer overwrite behavior."""
    with tempfile.TemporaryDirectory() as tmpdir:
        file_path = Path(tmpdir) / "test.txt"
        file_path.write_text("Original")

        # Overwrite should succeed
        result = file_writer_executor({
            "file_path": str(file_path),
            "content": "New content",
            "overwrite": True
        })
        assert result["created"] is False
        assert file_path.read_text() == "New content"

        # No overwrite should fail
        with pytest.raises(FileExistsError):
            file_writer_executor({
                "file_path": str(file_path),
                "content": "Another content",
                "overwrite": False
            })


def test_file_writer_create_dirs():
    """Test file writer directory creation."""
    with tempfile.TemporaryDirectory() as tmpdir:
        file_path = Path(tmpdir) / "subdir" / "nested" / "test.txt"

        result = file_writer_executor({
            "file_path": str(file_path),
            "content": "Test",
            "create_dirs": True
        })

        assert result["created"] is True
        assert file_path.exists()
        assert file_path.read_text() == "Test"


# ============================================================================
# Built-in Tools Registration Tests
# ============================================================================

def test_register_builtin_tools():
    """Test registering all built-in tools."""
    registry = ToolRegistry()
    register_builtin_tools(registry)

    # Check all tools are registered
    assert registry.get("file_reader") is not None
    assert registry.get("file_writer") is not None
    assert registry.get("llm_summarizer") is not None

    # Check executors are registered
    assert registry.get_executor("file_reader") is not None
    assert registry.get_executor("file_writer") is not None
    assert registry.get_executor("llm_summarizer") is not None

    # Verify tool definitions
    file_reader = registry.get("file_reader")
    assert ToolCapability.FILE_READ in file_reader.capabilities
    assert file_reader.permission_level == PermissionLevel.LOW

    file_writer = registry.get("file_writer")
    assert ToolCapability.FILE_WRITE in file_writer.capabilities
    assert file_writer.permission_level == PermissionLevel.MEDIUM

    llm_summarizer = registry.get("llm_summarizer")
    assert ToolCapability.LLM_CALL in llm_summarizer.capabilities
    assert llm_summarizer.permission_level == PermissionLevel.LOW
