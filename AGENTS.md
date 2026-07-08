# AGENTS.md

## Purpose
This file defines the development rules for OpenPilot Personal Agent.
When architecture, tool routing, metadata contracts, or permission boundaries change,
update this file together with `API.md`.

## Development principles
- Find the problem first; solve it second.
- Add a module, abstraction, or dependency only when there is a real need.
- Prefer the smallest change that fixes the current bug, gap, or boundary issue.
- Keep the project restrained; avoid speculative generalization.
- Preserve the existing style: explicit fields, strict contracts, narrow scope, and clear state transitions.

## Design priorities
- The project’s main strength is its LLM-oriented data modeling.
- Protect metadata shapes, field semantics, and state boundaries.
- Prefer extending existing contracts over inventing new layers.
- For cross-module communication, use the strict models under `Code/src/metadata/`.

## Module boundaries
- `ui/`: user interaction, display, and CLI entry points only.
- `autonomous_iteration/`: orchestration, state machine, task execution, and iteration control only.
- `tools/`: executable capabilities, tool contracts, and tool implementations only.
- `core/`: configuration, LLM access, risk policy, logging, and shared infrastructure only.
- `memory/`: context assembly, memory storage, project indexing, and persistence only.
- `metadata/`: typed contracts only; no business execution logic.
- `utils/`: stateless helper functions only.

## Tooling and permissions
- Tool use must remain controlled; do not open up command execution, file writes, or network access by default.
- Any action that mutates files, runs commands, or changes project state must be justified by a concrete need.
- High-risk actions need clear inputs, scope, and a verification or rollback path.
- Do not bypass existing approval, routing, or verification mechanisms for convenience.

## Testing policy
- Follow test-driven development: add or update tests before changing behavior.
- Prefer deterministic, offline, repeatable tests.
- Every behavior change should have a corresponding test update.
- Focus coverage on:
  - metadata and serialization contracts
  - tool side effects
  - runtime state machine and routing
  - memory/context assembly
  - boundary conditions and failure paths

## Change discipline
- Make small, localized changes.
- Do not refactor multiple core modules in one pass.
- Do not introduce new frameworks, layers, or abstractions unrelated to the current problem.
- If you change API fields, tool behavior, or permission boundaries, update the documentation too.

## Documentation sync
If any of the following changes, review and update them:
- `AGENTS.md`
- `API.md`
- `README.md`
- `Code/README.md`
- `Code/.env.example`
- `AGENT_LOOP_PROTOCOL.md`
- `AGENT_LOOP_SUPERVISOR.md`
- `AGENT_LOOP_GOAL.md`
- `AGENT_LOOP_TUI_OUTPUT_GUIDE.md`

For task-trajectory / real-task-diagnostics work, also review:
- `docs/task_trajectory/README.md`
- `docs/task_trajectory/TASK_TRAJECTORY_EVIDENCE.md`
- `docs/task_trajectory/TASK_TRAJECTORY_EVIDENCE_ARCHITECTURE.md`
- `docs/task_trajectory/TASK_TRAJECTORY_EVIDENCE_PLAN.md`
- `docs/task_trajectory/TASK_TRAJECTORY_EVENT_ALIGNMENT.md`
- `docs/task_trajectory/TASK_TRAJECTORY_ID_STRATIFICATION.md`
- `docs/task_trajectory/IMPLEMENTATION_LOG.md`

When a diagnosed problem is fully handled, update
`docs/task_trajectory/IMPLEMENTATION_LOG.md` in the same change set with:
- observed failure
- validation evidence
- implemented fix
- remaining limitations

Do not wait for the user to ask for this log update separately.

## Default workflow
1. Read the relevant code and tests first.
2. Identify the current design and the actual problem.
3. Fix it with the smallest viable change.
4. Add or adjust tests.
5. Only then consider refactoring or adding new abstractions.

## Loop coordination
- Codex-facing iteration rules live in `AGENT_LOOP_PROTOCOL.md`.
- External scheduling, checkpointing, retry, and resume semantics live in `AGENT_LOOP_SUPERVISOR.md`.
- The loop’s acceptance criteria and stop conditions live in `AGENT_LOOP_GOAL.md`.
- Session recovery rules live in `AGENT_LOOP_SESSION_RESUME.md`.
- If these documents change, review whether `docs/testing/TEST_DESIGN_GUIDE.md` needs a matching update.
