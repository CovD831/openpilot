"""Tool registry for managing and discovering tools."""

from __future__ import annotations

from typing import Callable, Optional

from openpilot.exceptions import OpenPilotError
from openpilot.tool_models import ToolCapability, ToolDefinition, PermissionLevel


class ToolRegistryError(OpenPilotError):
    """Tool registry related errors."""
    pass


class ToolRegistry:
    """Central registry for tool management."""

    def __init__(self):
        self._tools: dict[str, ToolDefinition] = {}
        self._executors: dict[str, Callable] = {}

    def register(
        self,
        definition: ToolDefinition,
        executor: Callable,
        allow_override: bool = False
    ) -> None:
        """
        Register a tool with its definition and executor function.

        Args:
            definition: Tool definition
            executor: Callable that executes the tool
            allow_override: Whether to allow overriding existing tool

        Raises:
            ToolRegistryError: If tool already exists and override not allowed
        """
        if definition.name in self._tools and not allow_override:
            raise ToolRegistryError(
                f"Tool '{definition.name}' already registered. "
                "Use allow_override=True to replace."
            )

        # Validate dependencies
        for dep in definition.dependencies:
            if dep.type == "tool" and dep.required:
                if dep.name not in self._tools:
                    raise ToolRegistryError(
                        f"Tool '{definition.name}' depends on '{dep.name}' "
                        "which is not registered."
                    )

        self._tools[definition.name] = definition
        self._executors[definition.name] = executor

    def unregister(self, tool_name: str) -> None:
        """
        Unregister a tool.

        Args:
            tool_name: Name of tool to unregister

        Raises:
            ToolRegistryError: If tool not found
        """
        if tool_name not in self._tools:
            raise ToolRegistryError(f"Tool '{tool_name}' not found.")

        # Check if other tools depend on this one
        dependents = []
        for name, tool in self._tools.items():
            if name == tool_name:
                continue
            for dep in tool.dependencies:
                if dep.type == "tool" and dep.name == tool_name and dep.required:
                    dependents.append(name)

        if dependents:
            raise ToolRegistryError(
                f"Cannot unregister '{tool_name}': "
                f"required by {', '.join(dependents)}"
            )

        del self._tools[tool_name]
        del self._executors[tool_name]

    def get(self, tool_name: str) -> Optional[ToolDefinition]:
        """
        Get tool definition by name.

        Args:
            tool_name: Name of tool

        Returns:
            Tool definition or None if not found
        """
        return self._tools.get(tool_name)

    def get_executor(self, tool_name: str) -> Optional[Callable]:
        """
        Get tool executor function.

        Args:
            tool_name: Name of tool

        Returns:
            Executor function or None if not found
        """
        return self._executors.get(tool_name)

    def list_all(self) -> list[ToolDefinition]:
        """
        List all registered tools.

        Returns:
            List of all tool definitions
        """
        return list(self._tools.values())

    def find_by_capability(
        self,
        capability: ToolCapability,
        max_permission: Optional[PermissionLevel] = None
    ) -> list[ToolDefinition]:
        """
        Find tools by capability.

        Args:
            capability: Required capability
            max_permission: Maximum permission level (e.g., only AUTO and LOW)

        Returns:
            List of matching tools
        """
        results = []
        for tool in self._tools.values():
            if capability not in tool.capabilities:
                continue

            if max_permission is not None:
                # Check permission level
                permission_order = [
                    PermissionLevel.AUTO,
                    PermissionLevel.LOW,
                    PermissionLevel.MEDIUM,
                    PermissionLevel.HIGH,
                    PermissionLevel.FORBIDDEN
                ]
                if permission_order.index(tool.permission_level) > permission_order.index(max_permission):
                    continue

            results.append(tool)

        return results

    def find_by_tags(self, tags: list[str], match_all: bool = False) -> list[ToolDefinition]:
        """
        Find tools by tags.

        Args:
            tags: List of tags to search for
            match_all: If True, tool must have all tags; if False, any tag matches

        Returns:
            List of matching tools
        """
        results = []
        for tool in self._tools.values():
            if match_all:
                if all(tag in tool.tags for tag in tags):
                    results.append(tool)
            else:
                if any(tag in tool.tags for tag in tags):
                    results.append(tool)

        return results

    def check_dependencies(self, tool_name: str) -> tuple[bool, list[str]]:
        """
        Check if all dependencies for a tool are satisfied.

        Args:
            tool_name: Name of tool to check

        Returns:
            Tuple of (all_satisfied, missing_dependencies)
        """
        tool = self.get(tool_name)
        if not tool:
            return False, [f"Tool '{tool_name}' not found"]

        missing = []
        for dep in tool.dependencies:
            if not dep.required:
                continue

            if dep.type == "tool":
                if dep.name not in self._tools:
                    missing.append(f"tool:{dep.name}")
            # For other dependency types (library, service, environment),
            # we would check them here in a real implementation

        return len(missing) == 0, missing

    def get_stats(self) -> dict:
        """
        Get registry statistics.

        Returns:
            Dictionary with registry stats
        """
        permission_counts = {}
        capability_counts = {}

        for tool in self._tools.values():
            # Count by permission level
            # Note: permission_level might already be a string due to use_enum_values
            perm = tool.permission_level if isinstance(tool.permission_level, str) else tool.permission_level.value
            permission_counts[perm] = permission_counts.get(perm, 0) + 1

            # Count by capability
            for cap in tool.capabilities:
                cap_name = cap if isinstance(cap, str) else cap.value
                capability_counts[cap_name] = capability_counts.get(cap_name, 0) + 1

        return {
            "total_tools": len(self._tools),
            "by_permission": permission_counts,
            "by_capability": capability_counts
        }


# Global registry instance
_global_registry: Optional[ToolRegistry] = None


def get_global_registry() -> ToolRegistry:
    """Get or create the global tool registry."""
    global _global_registry
    if _global_registry is None:
        _global_registry = ToolRegistry()
    return _global_registry


def reset_global_registry() -> None:
    """Reset the global registry (mainly for testing)."""
    global _global_registry
    _global_registry = None
