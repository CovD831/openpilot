# Bug Fix: TaskExecutionContext Missing Required Field

## Problem
When running `/autopilot`, the system crashed with:
```
ValidationError: 1 validation error for TaskExecutionContext
task
  Field required
```

## Root Cause
In `intelligent_autopilot.py` line 389-394, the code was creating `TaskExecutionContext` with wrong parameters:

```python
# ❌ Wrong - using old parameter names
context = TaskExecutionContext(
    task_id=task.id,
    agent_id="autopilot",
    start_time=datetime.now(),
    metadata=task.metadata
)
```

But `TaskExecutionContext` is defined as:
```python
class TaskExecutionContext(BaseModel):
    task: Task  # ← Required field!
    parent_context: dict[str, Any] = Field(default_factory=dict)
    shared_state: dict[str, Any] = Field(default_factory=dict)
    execution_history: list[dict[str, Any]] = Field(default_factory=list)
```

## Solution
Fixed the context creation to match the actual model definition:

```python
# ✅ Correct - using actual Task object
context = TaskExecutionContext(
    task=task,
    parent_context={"goal": context.get("goal", ""), "session_id": self.session_id},
    shared_state={},
    execution_history=[]
)
```

## Files Changed
- `src/execution/intelligent_autopilot.py` (line 389-394)

## Status
✅ Fixed - autopilot should now work correctly
