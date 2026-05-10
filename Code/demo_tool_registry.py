"""Demo script for tool registry functionality."""

from openpilot.tool_registry import ToolRegistry
from openpilot.builtin_tools import register_builtin_tools
from openpilot.tool_models import ToolCapability, PermissionLevel
import tempfile
from pathlib import Path


def main():
    print("=" * 70)
    print("OpenPilot Phase 2 - Tool Registry Demo")
    print("=" * 70)
    print()

    # Create registry and register built-in tools
    registry = ToolRegistry()
    register_builtin_tools(registry)

    # Show registry stats
    print("📊 Registry Statistics:")
    stats = registry.get_stats()
    print(f"  Total tools: {stats['total_tools']}")
    print(f"  By permission: {stats['by_permission']}")
    print(f"  By capability: {stats['by_capability']}")
    print()

    # List all tools
    print("🔧 Registered Tools:")
    for tool in registry.list_all():
        print(f"  • {tool.display_name} ({tool.name})")
        print(f"    Permission: {tool.permission_level}")
        print(f"    Capabilities: {', '.join(tool.capabilities)}")
        print(f"    Timeout: {tool.timeout_seconds}s")
        print()

    # Find tools by capability
    print("🔍 Finding tools by capability:")
    file_readers = registry.find_by_capability(ToolCapability.FILE_READ)
    print(f"  FILE_READ tools: {[t.name for t in file_readers]}")

    file_writers = registry.find_by_capability(ToolCapability.FILE_WRITE)
    print(f"  FILE_WRITE tools: {[t.name for t in file_writers]}")

    llm_tools = registry.find_by_capability(ToolCapability.LLM_CALL)
    print(f"  LLM_CALL tools: {[t.name for t in llm_tools]}")
    print()

    # Demo: File operations
    print("📝 Demo: File Operations")
    with tempfile.TemporaryDirectory() as tmpdir:
        test_file = Path(tmpdir) / "demo.txt"

        # Write file
        print(f"  Writing to {test_file.name}...")
        writer = registry.get_executor("file_writer")
        write_result = writer({
            "file_path": str(test_file),
            "content": "Hello from OpenPilot Phase 2!\nTool registry is working!"
        })
        print(f"  ✓ Written {write_result['bytes_written']} bytes")

        # Read file
        print(f"  Reading from {test_file.name}...")
        reader = registry.get_executor("file_reader")
        read_result = reader({"file_path": str(test_file)})
        print(f"  ✓ Read {read_result['size_bytes']} bytes")
        print(f"  Content preview: {read_result['content'][:50]}...")
        print()

    # Demo: Tool metadata
    print("📋 Demo: Tool Metadata")
    file_reader_def = registry.get("file_reader")
    print(f"  Tool: {file_reader_def.display_name}")
    print(f"  Description: {file_reader_def.description}")
    print(f"  Input parameters:")
    for param in file_reader_def.input_schema:
        required = "required" if param.required else "optional"
        print(f"    - {param.name} ({param.type}, {required}): {param.description}")
    print(f"  Failure modes:")
    for failure in file_reader_def.failure_modes:
        print(f"    - {failure.error_type}: {failure.description}")
    print()

    print("=" * 70)
    print("✅ OP-20 工具注册表增强 - 完成！")
    print("=" * 70)
    print()
    print("下一步：OP-21 智能工具选择与编排")


if __name__ == "__main__":
    main()
