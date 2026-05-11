#!/usr/bin/env python3
"""Test script for IntelligentAutopilot snake game creation."""

import os
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from execution.intelligent_autopilot import IntelligentAutopilot
from core.llm import LLMClient
from rich.console import Console

def main():
    """Test snake game creation."""
    console = Console()

    # Initialize LLM client
    llm_client = LLMClient()

    # Create autopilot (it creates its own tool registry, executor, etc.)
    print("[DEBUG] About to create IntelligentAutopilot...")
    sys.stdout.flush()
    autopilot = IntelligentAutopilot(
        llm_client=llm_client,
        console=console,
        auto_approve=True,  # Auto-approve for testing
        use_enhanced_ui=True  # Use enhanced UI with progress tracking
    )
    print("[DEBUG] IntelligentAutopilot created successfully")
    sys.stdout.flush()

    # Test goal
    goal = "Create a simple snake game in Python using pygame. Save it to ./output/snake_game.py"

    console.print(f"\n[bold cyan]Testing IntelligentAutopilot[/bold cyan]")
    console.print(f"[yellow]Goal:[/yellow] {goal}\n")
    sys.stdout.flush()

    # Execute
    try:
        print("[DEBUG] About to call autopilot.execute()...")
        sys.stdout.flush()
        result = autopilot.execute(goal)
        print("[DEBUG] autopilot.execute() returned")
        sys.stdout.flush()

        console.print(f"\n[bold green]✓ Execution completed[/bold green]")
        console.print(f"Success: {result.get('success', False)}")
        console.print(f"Message: {result.get('message', 'N/A')}")

        # Check if file was created
        output_file = Path("./output/snake_game.py")
        if output_file.exists():
            console.print(f"\n[bold green]✓ File created:[/bold green] {output_file}")
            console.print(f"File size: {output_file.stat().st_size} bytes")
        else:
            console.print(f"\n[bold red]✗ File not found:[/bold red] {output_file}")

    except Exception as e:
        console.print(f"\n[bold red]✗ Error:[/bold red] {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
