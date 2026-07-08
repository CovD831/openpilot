# OpenPilot Documentation Index

This directory contains topic-specific documentation that used to be spread
across the repository root.

## Root-level documents kept in place

These stay at the repository root because they are entry points or project-wide
contracts:

- `../README.md`
- `../INSTALL.md`
- `../API.md`
- `../AGENTS.md`
- `../THOUGHT_ARCHITECTURE.md`
- `../Thought.md`

## Topic documents

### Task trajectory / real-task diagnostics

- `./task_trajectory/README.md`

This is the active index for:

- task trajectory evidence design;
- trajectory architecture and implementation plan;
- event and id alignment;
- implementation log;
- real-task failure analyses;
- legacy diagnostics pointers.

### Testing

- `./testing/TEST_DESIGN_GUIDE.md`

Testing guidance aligned with the trajectory-evidence workflow.

## Documentation maintenance rule

If a completed implementation changes task trajectory, real-task diagnostics,
tool planning, path grounding, timeout/retry behavior, or read-only guardrails,
update:

- `./task_trajectory/IMPLEMENTATION_LOG.md`

in the same change set.
