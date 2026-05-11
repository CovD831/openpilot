#!/usr/bin/env python3
"""Test without Rich console."""

import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

print("[TEST] Starting...")
sys.stdout.flush()

# Import step by step
print("[TEST] Importing LLMClient...")
sys.stdout.flush()
from core.llm import LLMClient

print("[TEST] Importing IntelligentAutopilot...")
sys.stdout.flush()
from execution.intelligent_autopilot import IntelligentAutopilot

print("[TEST] Creating LLMClient...")
sys.stdout.flush()
llm_client = LLMClient()

print("[TEST] Creating IntelligentAutopilot without console...")
sys.stdout.flush()
autopilot = IntelligentAutopilot(
    llm_client=llm_client,
    console=None,  # No console
    auto_approve=True,
    use_enhanced_ui=True
)

print("[TEST] Calling execute...")
sys.stdout.flush()
result = autopilot.execute("test goal")

print(f"[TEST] Result: {result}")
sys.stdout.flush()
