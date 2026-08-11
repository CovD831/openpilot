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

The unified autonomous pre-task entry is canary-only and disabled by default.
Set `OPENPILOT_UNIFIED_AUTONOMOUS_ENTRY_ENABLED=true` to enable deterministic
runtime-fact completion followed by the bounded zero-tool response controller
in once/interactive autonomous routes. Recognized facts use zero Provider/tool
calls; fully grounded bounded responses use at most one repair and commit the
real assistant turn before display. Project/current claims remain undisplayed
evidence obligations. Set `OPENPILOT_GOVERNED_DECOMPOSITION=true` as a separate
canary to execute those obligations through the existing read-only tool loop
and durable checkpoints. Either evidence-path failure stops without legacy
fallback. Agent Generator routing is unchanged.

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
