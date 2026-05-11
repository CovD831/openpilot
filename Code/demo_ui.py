"""Demo script to showcase the enhanced UI features."""

import time
from rich.console import Console

from ui.enhanced_ui import EnhancedUI
from ui.progress_tracker import ProgressTracker


def demo_enhanced_ui():
    """Demonstrate the enhanced UI capabilities."""
    console = Console()
    ui = EnhancedUI(console)
    tracker = ProgressTracker(ui)

    # Show banner
    ui.show_banner()
    time.sleep(1)

    # Demo 1: Menu
    console.print("\n[bold cyan]Demo 1: Interactive Menu[/bold cyan]\n")
    menu = ui.show_menu(
        "Main Menu",
        [
            ("/plan", "Plan a new goal"),
            ("/execute", "Execute a goal"),
            ("/task", "Manage tasks"),
            ("/exit", "Exit OpenPilot"),
        ],
        selected=0
    )
    console.print(menu)
    time.sleep(2)

    # Demo 2: Live session with tool calls
    console.print("\n[bold cyan]Demo 2: Live Session with Tool Calls[/bold cyan]\n")
    time.sleep(1)

    with ui.live_session("OpenPilot Demo - Tool Execution"):
        tracker.start_tracking()

        # Simulate tool call 1
        with tracker.track_tool_call("file_reader", {"file_path": "/path/to/file.txt", "encoding": "utf-8"}):
            time.sleep(2)

        # Simulate tool call 2
        with tracker.track_tool_call("code_generator", {"task": "Create a Python function", "language": "python"}):
            time.sleep(2)

        # Simulate LLM call
        with tracker.track_llm_call("gpt-4", "Analyze the following code and suggest improvements..."):
            time.sleep(3)

        # Simulate another tool call
        with tracker.track_tool_call("file_writer", {"file_path": "/output/result.py", "content": "def hello()..."}):
            time.sleep(1.5)

        tracker.stop_tracking()

    # Demo 3: Success message
    console.print("\n[bold cyan]Demo 3: Status Messages[/bold cyan]\n")
    time.sleep(1)

    ui.show_success(
        "Task completed successfully!",
        "Generated 3 files, executed 5 tools, made 2 LLM calls"
    )
    time.sleep(2)

    # Demo 4: Error message
    ui.show_error(
        "Failed to execute task",
        "FileNotFoundError: The file '/path/to/missing.txt' does not exist"
    )
    time.sleep(2)

    # Demo 5: Task tree
    console.print("\n[bold cyan]Demo 4: Task Decomposition Tree[/bold cyan]\n")
    time.sleep(1)

    task_graph = {
        "tasks": [
            {
                "name": "Analyze requirements",
                "status": "completed",
                "subtasks": [
                    {"name": "Read specification", "status": "completed"},
                    {"name": "Identify dependencies", "status": "completed"},
                ]
            },
            {
                "name": "Implement features",
                "status": "in_progress",
                "subtasks": [
                    {"name": "Create data models", "status": "completed"},
                    {"name": "Implement business logic", "status": "in_progress"},
                    {"name": "Write tests", "status": "pending"},
                ]
            },
            {
                "name": "Deploy to production",
                "status": "pending",
                "subtasks": [
                    {"name": "Run CI/CD pipeline", "status": "pending"},
                    {"name": "Update documentation", "status": "pending"},
                ]
            }
        ]
    }

    tree_panel = ui.show_task_tree(task_graph)
    console.print(tree_panel)
    time.sleep(3)

    # Demo 6: Choice prompt
    console.print("\n[bold cyan]Demo 5: Interactive Choice[/bold cyan]\n")
    time.sleep(1)

    choice = ui.prompt_choice(
        "How would you like to proceed?",
        [
            "Continue with current plan",
            "Modify the plan",
            "Cancel and start over",
        ],
        default=0
    )
    console.print(f"\n[green]You selected option {choice + 1}[/green]\n")

    # Final message
    console.print("\n[bold green]✨ Demo completed! ✨[/bold green]\n")
    console.print("[dim]Run 'openpilot ui' to use the enhanced interface[/dim]\n")


if __name__ == "__main__":
    demo_enhanced_ui()
