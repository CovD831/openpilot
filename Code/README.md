# OpenPilot (package)

## Pi Harness rollout

The public `openpilot` CLI now uses a proposal-first Pi route for admitted
read-only work and explicitly approved mutations. It does not construct
`IntelligentAutopilot` or the legacy runtime controller on any public CLI
path, including an omitted-controller fallback. Pi built-in read/write/command
tools remain disabled; the fixed OpenPilot extensions cross Action Gateway.

Before dispatch, the task designer can only suggest scope. Deterministic task
admission produces the immutable `TaskAdmissionGrant`; the terminal renders a
derived proposal rather than treating task prose or UI state as authority.
`--once` mutations remain **proposal-only**: it returns an approval-required
exit without running Pi patch or command tools. In interactive mode,
`/approve PROPOSAL_ID` starts only a matching admitted mutation. Every write
target must still match its admission snapshot; patching uses no-follow file
descriptors; validation uses a ready project virtualenv and the exact declared
command; consent is rechecked immediately before each side effect. The terminal
prints a second-terminal `openpilot revoke ...` command when the consent becomes
active.

Run credentialed rollout checks without passing a key on the command line:

```bash
python -m autonomous_iteration.engines.pi_canary \
  --provider deepseek --model deepseek-v4-flash --mode readonly
python -m autonomous_iteration.engines.pi_canary \
  --provider deepseek --model deepseek-v4-flash --mode mutation
python -m autonomous_iteration.engines.pi_canary \
  --provider deepseek --model deepseek-v4-flash --mode recovery
```

The runner uses temporary fixtures and reads credentials only from the process
environment.

This directory is the `openpilot` Python package. For the full project overview,
architecture, setup, and handover notes, see the **[top-level README](../README.md)**.

```bash
pip install -r requirements.txt
pip install -e .
openpilot
openpilot --once "Inspect the project structure and explain the entry points"
# Safe standalone coding-agent smoke test
coding-agent --demo --show-events
# Evidence Core trajectory inspection
evidence list
```

The standalone `coding-agent` command runs the evidence-first fixture loop
without requiring an LLM. `--demo` uses a temporary workspace; for a real
workspace, pass `--workspace`, `--file`, one of `--draft`/`--patch` (or their
file variants), and an optional `--validate "..."` command. It prints the run
status and the persisted trajectory directory. Use `--show-events` to print
the replayable timeline.

The `evidence` command provides the trajectory MVP:

```bash
evidence --data-dir ./data/evidence_core list
evidence --data-dir ./data/evidence_core show RUN_ID
evidence --data-dir ./data/evidence_core timeline RUN_ID
evidence --data-dir ./data/evidence_core export RUN_ID --output ./bundles
evidence --data-dir ./data/runtime_diagnostics serve --port 8765
```

`list`, `show`, and `timeline` are read-only. Export refuses to replace an
existing bundle unless `--force` is supplied.

`serve` starts a local read-only Evidence Viewer with run search and typed
status/verification filters, a run overview, Trace tree, Trajectory ledger,
Raw Events view, selected-event inspector, artifact inventory, and JSON export
links. It reads the same Evidence Core store and never mutates trajectories.

- `src/` — source code (`ui`, `autonomous_iteration`, `agent_generator`, `tools`,
  `metadata`, `core`, `memory`, `utils`).
- `tests/` — pytest suite (`pytest`).
- `pyproject.toml` — package metadata and the `openpilot` CLI entry point.

Pi recovery is a separate, exact-validation-only protocol. If a mutation has a
durable receipt but Pi stops before validation, the same Evidence Run becomes
`indeterminate` without a synthetic success or terminal result. Use the new
command to inspect its derived recovery proposal, then explicitly confirm it:

```bash
openpilot recover --project-path /path/to/project --run-id RUN_ID
openpilot recover --project-path /path/to/project --run-id RUN_ID --confirm
```

The confirmation creates a fresh, run-bound approval and can run only the
original admitted validation command through Action Gateway. It reloads the
persisted admission/proposal identity, checks project and conversation identity,
acquires a Supervisor lease, and never restarts Pi or replays a patch. The old
`--checkpointing`, `--resume-run-id`, `--resume-checkpoint-id`, `--log-file`,
`--constraint`, `--ignore-memory`, and `--improvement-iterations` flags remain
rejected; there is no legacy Harness adapter fallback.

Project-scoped Python validation is gated by a read-only `.venv` preflight.
Existing ready environments attach without install/network writes; setup or
resync follows the root permission policy. Failure blocks validation instead of
falling back to host Python, and resume reattaches and verifies the checkpointed
environment identity before continuing.

Project improvement runs after a verified core project result. The automatic
default is an optional enhancement; `--improvement-iterations N` with `N > 0`
is an explicit required quality gate, while `0` disables improvement. Optional
failure is reported as a warning without changing completed core task evidence.
If an optional improvement mutates files and then fails, its explicit changed
files are restored from the pre-iteration Git safety snapshot before the run
returns; rollback failure remains a visible enhancement failure.

LLM reasoning is controlled through a provider-neutral typed policy. A
versioned capability resolver renders provider payloads at the transport
boundary. Only typed routine tool decisions may use the configured economical
mode (disabled by default); ambiguous, general, and multi-file decisions retain
the provider default. Recovery-cache identity binds provider, model, sanitized
endpoint (including a non-default port), capability profile, and resolved
reasoning semantics.

### Public CLI lifecycle

Launching `openpilot` is local-only: it renders the shell but does not probe a
Provider, create a Run, create evidence directories, or clear a shared log.
The first normal-language task triggers body-free candidate discovery and task
design. A read-only admission then runs through `PiTaskRunner`; its evidence is
stored under `<project>/.openpilot/evidence_core` only after task submission.

Set `OPENPILOT_PI_PROVIDER` and `OPENPILOT_PI_MODEL` for that Pi route and keep
the provider credential in the invoking shell. The current public route is not
yet a complete Claude Code-equivalent workflow: live transcript/diff UX,
interactive `/runs`/`/diff`/`/resume` views, and real PTY/provider mutation
canaries remain. Pi recovery is available through the explicit standalone
command above; `LegacyEngineAdapter` and its Harness route have been removed.
