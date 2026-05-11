# Bug Fix: OpenPilot Autopilot Hanging and UI Display Issues

## Date
2026-05-12

## Issues Fixed

### Issue #1: Program Hanging After Task Decomposition
**Symptom:** After showing the task tree, the program appeared to hang with "Status: Autopilot Mode" displayed but no progress being made.

**Root Cause:** A blocking `time.sleep(2)` operation was freezing the execution thread for 2 seconds, making the program appear stuck.

**Fix Applied:**
- Reduced sleep time from 2 seconds to 0.5 seconds
- This provides enough time for users to see the task tree without creating the appearance of hanging
- The enhanced UI's Live display with 4 refreshes/second provides smooth visual feedback

**Files Modified:**
- `src/execution/intelligent_autopilot.py` (line 203)

### Issue #2: Task Tree Displayed Outside UI Frame
**Symptom:** The task decomposition tree appeared ABOVE the UI frame instead of inside it, breaking the visual layout.

**Root Cause:** The `_show_task_tree()` method used `self.console.print(tree)` which bypassed the enhanced UI's managed layout. Direct console prints break out of the `Live` display's managed `Layout` object.

**Fix Applied:**
1. Created new method `create_task_tree_panel()` in `EnhancedUI` class that returns a Panel containing the task tree
2. Updated `_execute_with_enhanced_ui_v2()` to use the new UI-aware method
3. Task tree is now displayed via `self.enhanced_ui.update_main_content()` which properly integrates with the managed layout

**Files Modified:**
- `src/ui/enhanced_ui.py` - Added `create_task_tree_panel()` method (lines 296-338)
- `src/execution/intelligent_autopilot.py` - Updated lines 199-203 to use UI-aware display

## Changes Summary

### src/ui/enhanced_ui.py - New Method Added

**Lines 296-338:** Added `create_task_tree_panel()` method

```python
def create_task_tree_panel(self, decomposition) -> Panel:
    """Create a panel containing the task decomposition tree."""
    tree = Tree(
        f"[bold]{decomposition.original_task.description}[/bold]",
        guide_style="dim"
    )
    
    for subtask in decomposition.subtasks:
        priority_color = {
            "critical": "red",
            "high": "yellow",
            "medium": "cyan",
            "low": "dim"
        }.get(subtask.priority.value, "white")
        
        effort_str = f"{subtask.estimated_effort:.1f}u" if subtask.estimated_effort else "?"
        
        branch = tree.add(
            f"[{priority_color}]●[/{priority_color}] "
            f"{subtask.description} "
            f"[dim]({effort_str})[/dim]"
        )
        
        if subtask.dependencies:
            branch.add(f"[dim]Depends on: {len(subtask.dependencies)} task(s)[/dim]")
    
    return Panel(
        tree,
        title="📋 Task Breakdown",
        border_style="cyan",
        padding=(1, 2)
    )
```

### src/execution/intelligent_autopilot.py - Updated Task Tree Display

**Lines 199-208:** Replaced console print with UI-aware display

**Before:**
```python
# Show task tree
self._show_task_tree(decomposition)

import time
time.sleep(2)  # Let user see the tree
```

**After:**
```python
# Show task tree in UI
task_tree_panel = self.enhanced_ui.create_task_tree_panel(decomposition)
self.enhanced_ui.update_main_content(task_tree_panel)

# Brief pause to let user see the tree
import time
time.sleep(0.5)  # Reduced from 2s to 0.5s
```

## Key Improvements

1. **No More Hanging**: Reduced sleep from 2s to 0.5s eliminates the appearance of the program being stuck
2. **Proper UI Layout**: Task tree now displays inside the UI frame in a formatted panel with title "📋 Task Breakdown"
3. **Consistent UI Experience**: All output stays within the managed layout
4. **Better Visual Design**: Task tree is displayed in a cyan-bordered panel with proper padding
5. **Preserved Standard Mode**: The `_show_task_tree()` method remains unchanged for standard console mode

## Testing

To test the fixes:

```bash
cd /mnt/c/Users/14235/Desktop/Projects/openPilot/Code
openpilot run
```

Then type:
```
/autopilot 帮我在'/mnt/c/Users/14235/Desktop/Projects/openPilot/TestDemo-Snake'中做一个贪吃蛇
```

**Expected Results:**
1. ✓ Task tree appears INSIDE the UI frame, not above it
2. ✓ Tree is displayed in a panel with title "📋 Task Breakdown"
3. ✓ Program doesn't hang - execution proceeds after 0.5s
4. ✓ Tasks begin executing immediately after the brief pause
5. ✓ All UI elements remain within the managed layout
6. ✓ Files are created in the target directory

## Technical Details

### Why Direct Console Prints Break the Layout

The enhanced UI uses Rich's `Live` display with a managed `Layout`:

```python
with Live(layout, refresh_per_second=4, screen=False) as live:
    # All updates go through layout.update()
```

When you call `console.print()` directly:
- It bypasses the `Live` display's rendering pipeline
- Output goes directly to the terminal, appearing above the managed layout
- The layout continues to render below, creating a broken visual experience

### Solution: UI-Aware Panel Creation

Instead of printing directly, we:
1. Create a `Panel` object containing the tree
2. Pass it to `update_main_content()` which updates the layout
3. The `Live` display automatically re-renders with the new content
4. Everything stays within the managed layout

## Verification Checklist

- [x] Added `create_task_tree_panel()` method to EnhancedUI
- [x] Updated enhanced UI execution to use new method
- [x] Reduced blocking sleep from 2s to 0.5s
- [x] Syntax check passed
- [x] Standard console mode still works (uses `_show_task_tree()`)
- [ ] Manual testing with actual autopilot execution (requires user testing)

## Notes

The `_show_task_tree()` method (lines 921-948) remains unchanged and is still used by the standard console mode (`_execute_standard()` method). Only the enhanced UI path now uses the new UI-aware method.

This fix ensures that all UI output in enhanced mode goes through the managed layout system, providing a consistent and professional user experience.
