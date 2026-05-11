#!/usr/bin/env python3
"""Test tool registry."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from tools.tool_registry import ToolRegistry
from tools.builtin_tools import register_builtin_tools

def main():
    print("Testing tool registry...")

    registry = ToolRegistry()
    print(f"Tools before registration: {len(registry.list_all())}")

    register_builtin_tools(registry)
    print(f"Tools after registration: {len(registry.list_all())}")

    tools = registry.list_all()
    print("\nRegistered tools:")
    for tool in tools:
        print(f"  - {tool.name}: {tool.description}")

if __name__ == "__main__":
    main()
