# OpenPilot (package)

This directory is the `openpilot` Python package. For the full project overview,
architecture, setup, and handover notes, see the **[top-level README](../README.md)**.

```bash
pip install -r requirements.txt
pip install -e .
openpilot run
```

- `src/` — source code (`ui`, `autonomous_iteration`, `agent_generator`, `tools`,
  `metadata`, `core`, `memory`, `utils`).
- `tests/` — pytest suite (`pytest`).
- `pyproject.toml` — package metadata and the `openpilot` CLI entry point.

Durable recovery is implemented by strict contracts in `src/metadata/`, the
atomic `src/autonomous_iteration/checkpoint_store.py`, and explicit controller
preflight/reconciliation. Enable it with `openpilot run --checkpointing`; resume
requires explicit run ID, checkpoint ID, and project path. File mutations are
hash-reconciled, while commands without a registered probe fail closed.

The unified autonomous pre-task entry and governed decomposition admission are
enabled by default after the CRU-7 usability gate. Recognized runtime facts use
zero Provider/tool calls; fully grounded bounded responses use at most one
repair and commit the real assistant turn before display. Project/current
claims remain undisplayed evidence obligations and execute only through the
existing read-only tool loop and durable checkpoints. Set both
`OPENPILOT_UNIFIED_AUTONOMOUS_ENTRY_ENABLED=false` and
`OPENPILOT_GOVERNED_DECOMPOSITION=false` for the bounded legacy rollback lane.
An evidence-path failure stops without legacy fallback. Agent Generator routing
is unchanged.

Before the bounded response step, a strict pre-task admission positively
recognizes lightweight conversation/knowledge and current-external questions.
Development, artifact creation, mutation, execution, and validation requests
enter project execution directly; ambiguous inputs fail safe to that path.
This does not grant mutation authority or change the public
`agent_generator | autonomous_iteration` route contract. CLI errors report
bounded response, external evidence, and project execution as distinct stages.

Bounded Provider requests and observations are conversation-owned durable
steps. A crash after an exact observed response resumes without a Provider
replay; a pending or not-yet-bound transport outcome stops fail-closed. Recovery
also reuses the same response candidate and idempotent assistant ledger entry.

Set `OPENPILOT_MODEL_VISIBLE_PROTOCOL_REPAIR=true` only for the bounded recovery
canary. Local and provider-native tool paths then expose one unknown-tool or
invalid-input failure to the model and accept one corrected call. A second
protocol failure or exact repeated invalid call stops; permission, scope,
confirmation, checkpoint, and validation failures remain terminal. Provider
tool-call/result IDs stay paired and the current phase's tool surface is not
expanded.

Project-scoped Python validation is gated by a read-only `.venv` preflight.
Existing ready environments attach without install/network writes; setup or
resync follows the root permission policy. Failure blocks validation instead of
falling back to host Python, and resume reattaches and verifies the checkpointed
environment identity before continuing.

Task-owned active diagnosis records typed conflicts, risks, and
measure/act/verify/recover/stop decisions in `RuntimeStateMetadata`. Its
content-sensitive progress signature and decision history survive checkpoints;
the evaluator selects the next need, while `ToolRouter`, Guard, executors, and
the verifier keep their existing capability and authority boundaries.

The verified core/post-core boundary is canary-only. Set
`OPENPILOT_CORE_POST_CORE_INTEGRATION=true` to defer the legacy
pre-finalization improvement call and derive the unique, content-addressed Core
Completion Package after the core checkpoint/report is durable. Until a
post-core package consumer is present, the stage remains skipped; this flag
does not authorize mutation. The automatic policy is optional `0/1/1` (zero
hard accepted transactions, at most one accepted transaction and one attempt).
`--improvement-iterations N` with `N > 0` is an explicit required quality gate,
while `0` disables improvement. Optional failure is reported without changing
completed core task evidence.
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
