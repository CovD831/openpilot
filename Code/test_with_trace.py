#!/usr/bin/env python3
"""Test with trace to see where it hangs."""

import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from core.llm import LLMClient
from execution.intelligent_autopilot import IntelligentAutopilot

print("[TEST] Creating autopilot...")
sys.stdout.flush()

llm_client = LLMClient()
autopilot = IntelligentAutopilot(
    llm_client=llm_client,
    console=None,
    auto_approve=True,
    use_enhanced_ui=True
)

print("[TEST] About to call execute with trace...")
sys.stdout.flush()

# Enable tracing
import trace
tracer = trace.Trace(count=False, trace=True)

print("[TEST] Starting trace...")
sys.stdout.flush()

tracer.run('autopilot.execute("test")')
