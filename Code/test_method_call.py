#!/usr/bin/env python3
"""Minimal test to isolate the method call issue."""

import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from execution.intelligent_autopilot import IntelligentAutopilot
from core.llm import LLMClient
from rich.console import Console

def main():
    """Minimal test."""
    print("[TEST] Creating components...")
    sys.stdout.flush()

    console = Console()
    llm_client = LLMClient()

    print("[TEST] Creating autopilot...")
    sys.stdout.flush()

    autopilot = IntelligentAutopilot(
        llm_client=llm_client,
        console=console,
        auto_approve=True,
        use_enhanced_ui=True
    )

    print("[TEST] Autopilot created")
    print(f"[TEST] Method exists: {hasattr(autopilot, '_execute_with_enhanced_ui')}")
    print(f"[TEST] Method type: {type(getattr(autopilot, '_execute_with_enhanced_ui', None))}")
    sys.stdout.flush()

    # Try to get the method
    method = autopilot._execute_with_enhanced_ui
    print(f"[TEST] Got method reference: {method}")
    sys.stdout.flush()

    # Try to call it
    print("[TEST] About to call method...")
    sys.stdout.flush()

    result = method("test goal", {})

    print(f"[TEST] Method returned: {result}")
    sys.stdout.flush()

if __name__ == "__main__":
    main()
