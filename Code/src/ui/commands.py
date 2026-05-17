"""Unified command registry for OpenPilot CLI."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Callable


class CommandCategory(str, Enum):
    """Command categories for organization."""
    EXECUTION = "execution"
    SYSTEM = "system"


@dataclass
class Command:
    """A CLI command definition."""
    name: str
    aliases: list[str]
    description: str
    usage: str
    category: CommandCategory
    handler: Callable | None = None
    requires_args: bool = False


class CommandRegistry:
    """Central registry for all OpenPilot commands."""

    def __init__(self):
        self._commands: dict[str, Command] = {}
        self._aliases: dict[str, str] = {}
        self._initialize_commands()

    def _initialize_commands(self):
        """Initialize all available commands."""
        commands = [
            # Execution
            Command(
                name="/autopilot",
                aliases=[],
                description="AGI mode: Fully autonomous execution with intelligent task decomposition",
                usage="/autopilot <goal>",
                category=CommandCategory.EXECUTION,
                requires_args=True
            ),
            Command(
                name="/agent",
                aliases=[],
                description="Generate a reusable Python agent from an interactive pipeline",
                usage="/agent <task>",
                category=CommandCategory.EXECUTION,
                requires_args=True
            ),

            # System
            Command(
                name="/config",
                aliases=[],
                description="Show current LLM configuration",
                usage="/config",
                category=CommandCategory.SYSTEM,
                requires_args=False
            ),
            Command(
                name="/clear",
                aliases=[],
                description="Clear the screen",
                usage="/clear",
                category=CommandCategory.SYSTEM,
                requires_args=False
            ),
            Command(
                name="/help",
                aliases=["/?"],
                description="Show help information",
                usage="/help",
                category=CommandCategory.SYSTEM,
                requires_args=False
            ),
            Command(
                name="/exit",
                aliases=["/quit", "exit", "quit", ":q"],
                description="Exit OpenPilot",
                usage="/exit",
                category=CommandCategory.SYSTEM,
                requires_args=False
            ),
        ]

        for cmd in commands:
            self.register(cmd)

    def register(self, command: Command):
        """Register a command and its aliases."""
        self._commands[command.name] = command

        # Register aliases
        for alias in command.aliases:
            self._aliases[alias] = command.name

    def get(self, name: str) -> Command | None:
        """Get a command by name or alias."""
        # Check if it's an alias first
        if name in self._aliases:
            name = self._aliases[name]

        return self._commands.get(name)

    def get_all_names(self) -> list[str]:
        """Get all command names (including aliases) for autocomplete."""
        names = list(self._commands.keys())
        names.extend(self._aliases.keys())
        return sorted(names)

    def get_commands_by_category(self, category: CommandCategory) -> list[Command]:
        """Get all commands in a category."""
        return [
            cmd for cmd in self._commands.values()
            if cmd.category == category
        ]

    def get_all_commands(self) -> list[Command]:
        """Get all registered commands."""
        return list(self._commands.values())

    def is_valid_command(self, name: str) -> bool:
        """Check if a command name is valid."""
        return name in self._commands or name in self._aliases

    def format_help(self) -> str:
        """Format help text for all commands."""
        lines = ["[bold cyan]OpenPilot System Commands[/bold cyan]\n"]

        # Group by category
        categories = {
            CommandCategory.EXECUTION: "[bold]Execution:[/bold]",
            CommandCategory.SYSTEM: "[bold]System:[/bold]",
        }

        for category, header in categories.items():
            commands = self.get_commands_by_category(category)
            if commands:
                lines.append(header)
                for cmd in commands:
                    # Format aliases
                    aliases_str = ""
                    if cmd.aliases:
                        aliases_str = f" (aliases: {', '.join(cmd.aliases)})"

                    lines.append(f"  {cmd.name:<20} {cmd.description}{aliases_str}")
                lines.append("")

        lines.append("[bold]Tips:[/bold]")
        lines.append("  - Type '/' to see command suggestions")
        lines.append("  - Use arrow keys to navigate command history")
        lines.append("  - Press Tab for command completion")
        lines.append("  - Use /agent <task> to build a reusable generated agent")
        lines.append("  - Type any text without '/' to run modern autopilot")

        return "\n".join(lines)


# Global registry instance
_registry = CommandRegistry()


def get_command_registry() -> CommandRegistry:
    """Get the global command registry."""
    return _registry


def get_all_command_names() -> list[str]:
    """Get all command names for autocomplete."""
    return _registry.get_all_names()


def is_valid_command(name: str) -> bool:
    """Check if a command is valid."""
    return _registry.is_valid_command(name)


def get_command(name: str) -> Command | None:
    """Get a command by name or alias."""
    return _registry.get(name)
