# CRU-7 Canary and Rollout Inventory

> Status: accepted partial rollout at `10c5a9bfba889d27cba6133c612e6e4c05a4afaa`
>
> Scope: autonomous entry, governed decomposition, bounded protocol repair,
> verified core handoff rollout, and legacy autonomous fallback only.

## 1. Ownership and duplication review

CRU-7 introduces no new runtime metadata and no new control-plane writer. The
canary evaluator is development-only and consumes bounded evidence receipts;
it cannot grant task authority, close completion, mutate a checkpoint, or
change a feature flag. Runtime facts remain owned by `IterationTurnRecord`,
`RuntimeStateMetadata`, `SessionExecutionCursor`, checkpoints, reports, tool
receipts, verification evidence, and the core completion handoff.

Reviewed contracts and consumers:

- `IterationTurnRecord`, `IterationControlCursor`, response outcomes and the
  assistant ledger;
- `DecompositionDecision`, `SessionExecutionCursor`, task results and active
  diagnostic decisions;
- Provider/tool error envelopes, mutation receipts, verification state and
  recovery checkpoints;
- `ProjectImprovementPolicy`, core handoff/package result composition;
- CLI error rendering, Agent Generator bypass, environment flags, API and
  package documentation;
- `docs/metadata/CONTRACT_CATALOG.md` and concrete public exports.

Decision: reuse source evidence by ID/hash and keep the rollout verdict as a
frozen experiment-local derived value. Do not add `MetadataKind`, persist a
second success fact, or let cost compensate for safety/quality.

## 2. Pre-registered matrix and gates

The immutable protocol is
`experiments/mini_swe_active_iteration/CRU_7_USABILITY_CANARY_PROTOCOL_V1.json`.
It requires exactly one legacy and one candidate receipt for each of twelve
user-task categories and covers response-only, evidence-seeking, single-task,
and decomposed progression.

Hard gates are non-compensating:

- candidate scenario quality is 12/12;
- traceback leakage, false success, scope violation, duplicate mutation,
  indeterminate replay, and credential leakage are all zero;
- candidate core success does not regress against the legacy baseline;
- cost metrics are inadmissible until every preceding gate passes.

Correct fail-closed behavior is a scenario pass, not a fabricated business
success. In particular, required enhancement without an accepted PKG3/PKG4
consumer must fail overall while preserving verified core evidence.

## 3. Rollout boundaries

- Unified autonomous entry and governed decomposition may default on only
  after the complete matrix and full Code regression suite pass.
- Model-visible protocol repair has an independent negative-regression gate.
  Any changed no-progress, permission, validation, or call/result behavior
  keeps it explicit opt-in.
- Core/post-core integration cannot default on until an accepted package
  consumer exists; PKG0/package construction alone is insufficient.
- The legacy autonomous pipeline may become default-off rollback-only after
  the first two gates pass. This decision does not deprecate the classifier,
  Agent Generator route, or Agent Generator pipeline.

## 4. Five-axis evidence

### State and effects

| Trigger | Effect | Failure boundary | Evidence |
| --- | --- | --- | --- |
| candidate flag default | selects an existing autonomous lane | explicit false restores legacy lane | default/rollback tests |
| canary evaluator | derives verdict only | missing/duplicate receipt rejects | evaluator tests |
| hard metric nonzero | blocks rollout and cost comparison | no compensating metric | six-metric matrix |
| missing post-core consumer | keeps integration default off | required enhancement remains fail-closed | CRU-6 integration tests |

### Resource bounds

| Input | Bound | Work | Outside bound |
| --- | --- | --- | --- |
| task receipts | exactly 24 paired receipts | O(24) | reject |
| evidence IDs | 1–64 per receipt, 512 chars each | bounded validation | reject |
| IDs/hashes | 256-char run ID, canonical SHA-256 | constant per field | reject |
| counters | literal non-negative integers | constant per metric | reject |

### Boundary behavior

| Case | Expected result |
| --- | --- |
| empty or partial matrix | no verdict |
| duplicate lane/category | no verdict |
| faster but unsafe candidate | rollout false, cost inadmissible |
| candidate core regression | rollout false, cost inadmissible |
| core paths green, repair regression | core defaults may advance; repair stays canary-only |
| post-core package exists without consumer | integration stays canary-only |

### Verdict before execution

- Correctness: approved for test-first implementation; exact category/lane
  coverage and non-compensating gates are explicit.
- Readability: approved; one small experiment-local evaluator, no runtime
  branching abstraction.
- Architecture: approved; source owners and production permission boundaries
  are unchanged.
- Security: approved; all safety metrics are hard zero gates and evidence is
  bounded/hash-linked.
- Maintainability: approved; protocol, evaluator tests, runtime rollout tests,
  result artifact, and documentation are independently reviewable.

## 5. Executed verdict

`CRU_7_USABILITY_CANARY_RESULT_V1.json` records the immutable candidate result:

- 12/12 categories and 4/4 paths passed; focused selection was **21 passed**;
- canary evaluator plus three-arm gates were **15 passed**;
- frozen candidate Code suite was **1530 passed**, and the final suite after an
  explicit legacy rollback-path test was **1531 passed**, versus the CRU-6
  baseline **1528 passed**; all had zero failures;
- every pre-registered safety metric remained zero;
- unified entry and governed decomposition advanced to default-on with explicit
  false rollback switches;
- model-visible repair stayed canary-only after a real default-on regression
  trial produced 2 failures in a 226-test focused suite;
- core/post-core integration stayed canary-only because the authoritative
  package consumer is absent;
- no external Provider credentials were available, so the result makes no live
  token/call/latency superiority claim.
