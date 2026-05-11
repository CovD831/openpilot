#!/usr/bin/env python3
"""Test UI without LLM calls."""

import sys
sys.path.insert(0, 'src')

from ui.enhanced_ui import EnhancedUI
from ui.progress_tracker import ProgressTracker
from rich.console import Console
import time

console = Console()
ui = EnhancedUI(console)
tracker = ProgressTracker(ui)

print("[TEST] Starting UI test...")

# Start tracking
tracker.start_tracking()

# Update main content
ui.update_main_content(
    ui.create_status_panel("Testing", "This is a test of the UI system")
)

ui.log_activity("info", "Test started")
time.sleep(1)

ui.log_activity("success", "Test completed successfully")
time.sleep(1)

# Stop tracking
tracker.stop_tracking()

print("[TEST] UI test completed!")
