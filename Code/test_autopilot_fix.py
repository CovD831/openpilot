#!/usr/bin/env python
"""Test script to verify autopilot bug fixes."""

import sys
sys.path.insert(0, 'src')

from rich.console import Console
from core.llm import LLMClient
from core.config import LLMSettings
from execution.intelligent_autopilot import IntelligentAutopilot

def test_basic_execution():
    """Test basic autopilot execution."""
    console = Console()

    # Initialize settings
    settings = LLMSettings()

    # Create LLM client
    llm_client = LLMClient(settings)

    # Create autopilot with enhanced UI
    autopilot = IntelligentAutopilot(
        llm_client=llm_client,
        console=console,
        auto_approve=True,
        use_enhanced_ui=True
    )

    # Test with a simple goal
    goal = "创建一个简单的Python文件，内容是打印Hello World"

    console.print("\n[bold cyan]Testing Autopilot with Enhanced UI[/bold cyan]")
    console.print(f"Goal: {goal}\n")

    try:
        result = autopilot.execute(goal)

        console.print("\n[bold green]✓ Test completed![/bold green]")
        console.print(f"Success: {result.get('success', False)}")
        console.print(f"Tasks completed: {result.get('stats', {}).get('tasks_completed', 0)}")
        console.print(f"Tasks failed: {result.get('stats', {}).get('tasks_failed', 0)}")

        return result.get('success', False)

    except Exception as e:
        console.print(f"\n[bold red]✗ Test failed with exception:[/bold red]")
        console.print(f"Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = test_basic_execution()
    sys.exit(0 if success else 1)
