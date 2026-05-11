#!/usr/bin/env python
"""Test script for command autocomplete and auto-suggest features."""

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.history import InMemoryHistory

# Import command registry
import sys
sys.path.insert(0, 'src')

from ui.commands import get_all_command_names, get_command_registry

def main():
    print("OpenPilot Command Autocomplete Test")
    print("=" * 50)

    # Get all commands
    commands = get_all_command_names()
    print(f"\n✓ Loaded {len(commands)} commands from registry:")
    for cmd in sorted(commands):
        print(f"  - {cmd}")

    print("\n" + "=" * 50)
    print("Interactive Test Mode")
    print("=" * 50)
    print("\nFeatures to test:")
    print("  1. Type '/' and press TAB - should show dropdown menu")
    print("  2. Type '/au' and press TAB - should complete to '/autopilot'")
    print("  3. Type 'exit' - should show in dropdown")
    print("  4. After typing a command once, type it again - should see gray suggestion")
    print("  5. Press Ctrl+C to exit\n")

    # Setup completer
    completer = WordCompleter(
        commands,
        ignore_case=True,
        sentence=True,
        match_middle=True
    )

    # Setup history and auto-suggest
    history = InMemoryHistory()
    auto_suggest = AutoSuggestFromHistory()

    # Create session
    session = PromptSession(
        completer=completer,
        history=history,
        auto_suggest=auto_suggest,
        complete_while_typing=True,
        enable_history_search=True
    )

    try:
        while True:
            user_input = session.prompt("test> ")

            if user_input.strip() in ['exit', 'quit', '/exit', '/quit']:
                print("Goodbye!")
                break

            if user_input.strip() == '/help':
                registry = get_command_registry()
                print("\n" + registry.format_help())
                continue

            print(f"You entered: {user_input}")

    except (KeyboardInterrupt, EOFError):
        print("\nExiting...")

if __name__ == "__main__":
    main()
