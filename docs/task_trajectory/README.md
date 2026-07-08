# Task Trajectory Documentation Index

## Purpose

This file organizes the current task-trajectory / real-task-diagnostics
documents so the repository does not become ambiguous as the design evolves.

---

## Active documents

### 1. Design overview

- `./TASK_TRAJECTORY_EVIDENCE.md`

Use this for the high-level purpose and principles of the task trajectory
evidence layer.

### 2. Architecture

- `./TASK_TRAJECTORY_EVIDENCE_ARCHITECTURE.md`

Use this for layers, record families, and how the evidence system fits the
OpenPilot runtime.

### 3. Staged plan

- `./TASK_TRAJECTORY_EVIDENCE_PLAN.md`

Use this for phase planning and implementation order.

### 4. Event / metadata alignment

- `./TASK_TRAJECTORY_EVENT_ALIGNMENT.md`

Use this when adding or changing trajectory events.

### 5. ID stratification

- `./TASK_TRAJECTORY_ID_STRATIFICATION.md`

Use this when changing root task id, subtask id, step id, call id, or session id
handling.

### 6. Implementation log

- `./IMPLEMENTATION_LOG.md`

Use this as the chronological problem / validation / resolution record. Update
it whenever a diagnosed problem is completed.

### 7. Latest real-task failure analysis

- `./failures/REAL_TASK_FAILURE_ANALYSIS_2026-07-04.md`

Use this for the current observed failure phenomena and suspected root problems
from the latest real-task run.

---

## Legacy compatibility pointers

These are no longer the active design docs:

- `./legacy/REAL_TASK_DIAGNOSTICS.md`
- `./legacy/REAL_TASK_DIAGNOSTICS_PLAN.md`

They remain only so older references do not break.

---

## Stable thought documents

Do not modify these unless the user explicitly asks:

- `/Users/abab/Documents/openpilot/THOUGHT_ARCHITECTURE.md`
- `/Users/abab/Documents/openpilot/Thought.md`

---

## Documentation update rule

If a change completes a diagnosed problem in any of these areas:

- trajectory evidence;
- real-task execution;
- tool planning;
- path grounding;
- timeout / retry behavior;
- read-only guardrails;
- runtime state and completion;

then update:

1. the relevant design or plan doc if the intended architecture changed;
2. `./IMPLEMENTATION_LOG.md` with
   the completed problem slice.

The user should not need to separately request that the implementation log be
updated.
