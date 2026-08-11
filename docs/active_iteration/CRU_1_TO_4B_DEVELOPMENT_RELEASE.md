# CRU 1 Through 4B Development Release

## Release identity

- Package version: `0.1.0.dev2`
- Git branch: `codex/cru-1-to-4b-dev`
- Git tag: `v0.1.0-dev.2`
- Remote baseline: `origin/main` at `21c8e66`
- Functional freeze: `39b1fab` (`Make bounded provider recovery replay-free`)
- Freeze date: 2026-08-11

This is a cumulative development release. It starts from the remote repository
baseline and includes the complete ancestry through CRU-1, CRU-2A through
CRU-2D, CRU-3, CRU-4A, and CRU-4B, together with their required context,
provider, runtime, test, and documentation prerequisites. Release-only version
metadata and this release note are layered on the functional freeze; CRU-5 and
later work is excluded.

## Included cumulative boundary

- CRU-1 autonomous decomposition user-error containment and recoverability.
- CRU-2A conversation-owned pre-task state, durable turn/ingress storage,
  ledger-first assistant commit, and prepared/active task binding.
- CRU-2B deterministic runtime responses.
- CRU-2C bounded zero-tool model response.
- CRU-2D governed evidence escalation.
- CRU-3 governed decomposition and single-task evidence handoff.
- CRU-4A one bounded model-visible tool-protocol repair.
- CRU-4B replay-free durable Provider-step recovery.

The authoritative implementation and evidence details remain in
`CORE_RUNTIME_USABILITY_AND_ACTIVE_ITERATION_PLAN.md`,
`CRU_4B_METADATA_IMPACT_AND_RECOVERY_INVENTORY.md`, and
`../task_trajectory/IMPLEMENTATION_LOG.md`.

## Safety and rollout boundary

The package-level canary flags remain explicit environment controls. The local
`openpilot-dev` launcher enables unified autonomous entry and governed
decomposition for development use, while model-visible protocol repair remains
off. This is a scoped local development canary, not a production default
switch. The release does not claim automatic replay of an indeterminate Provider
request, or authority to infer an unobserved transport result. CRU-5 active
diagnostic strengthening, CRU-6 core/post-core integration, and CRU-7 canary
and default-switch work are not included.

Development canary hardening in `0.1.0.dev2` keeps the top-level route contract
unchanged (`agent_generator | autonomous_iteration`). Lightweight conversation
completes as `IterationDisposition.COMPLETE_RESPONSE` inside autonomous
iteration. Chinese claim segments tolerate whitespace-only boundary
differences. Current-external evidence searches with the original user question,
requires a relevant fresh summary, and atomically replaces the pre-search
candidate before ledger commit. Explicit weather questions use structured
`wttr.in` evidence through the existing `web_searcher` contract.
The local canary is limited to deterministic runtime answers, lightweight
conversation, and current-external questions. Explicit project/file/path work
retains the top-level `autonomous_iteration` route and uses the legacy project
autopilot instead of allowing a zero-tool file-access refusal to complete.

## Validation

The cumulative CRU-1-through-4B functional freeze recorded:

- 88 passing metadata/reducer/bounded-response/assistant-commit/store/
  evidence-escalation/unified-entry/CLI tests;
- 51 passing focused recovery and ledger tests;
- 1,491 passing `Code/tests` tests with one pre-existing pytest deprecation
  warning;
- touched Ruff, `compileall`, and `git diff --check` passing.

The release snapshot was revalidated with:

- `PYTHONPATH=src python -m pytest -q tests`: **1,492 passed**;
- `PYTHONPATH=src python -m pytest -q tests/test_release_version.py`: **1 passed**;
- `python3 -m compileall -q Code/src`: passed;
- isolated wheel build for `0.1.0.dev1`: `openpilot-0.1.0.dev1-py3-none-any.whl`, SHA-256
  `ba8c1c7680ec4ea41a4847272f0c225475f8df598ae1dfc861c4693e557891b6`.

- `git diff --check`: passed.

The `0.1.0.dev2` development canary was validated with:

- `PYTHONPATH=src python -m pytest -q tests`: **1,506 passed**;
- touched Ruff, `compileall`, release-version test, and `git diff --check`: passed;
- isolated wheel: `openpilot-0.1.0.dev2-py3-none-any.whl`, SHA-256
  `583ea7a40cc073dd488701d2c637833535d8a28b2ce8f555b321bc4f369ff8da`;
- editable install reports version `0.1.0.dev2` from this release worktree;
- interactive `openpilot-dev` smoke: greeting completed inside
  `autonomous_iteration`, model identity used deterministic runtime facts, and
  `今天常熟的天气怎么样` returned fresh structured weather evidence after one
  observed transient Provider timeout failed closed.

The explicit `PYTHONPATH=src` is part of the repository's test invocation. An
editable package install alone does not expose the repository's top-level
source packages to pytest collection.

## Known limitations

- The local development launcher enables unified entry and governed decomposition;
  package consumers that do not set the flags retain the package defaults.
- No production default-on claim is included.
- CRU-4 does not authorize Provider replay after an indeterminate request.
- The repository root `README.md` remains generated project-context content and
  is not a release overview; operational entry points remain `Code/README.md`
  and the active-iteration documentation index.
