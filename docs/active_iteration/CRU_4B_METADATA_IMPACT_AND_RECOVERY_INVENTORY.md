# CRU-4B Metadata Impact and Provider-Step Recovery Inventory

## Scope

CRU-4B closes the crash boundary between a conversation-owned bounded Provider
request, its durable response observation, and grounding/assistant commit. It
does not add transport replay authority, task mutation authority, or a new
Provider executor.

## Existing owner inventory

- `IterationTurnRecordMetadata` is the durable pre-task run owner.
- `IterationControlCursor.pending_provider_request` owns one admitted request
  while its Provider outcome is unknown.
- `RootDecisionBudget` owns call, round, repair, and completion-token usage.
- `DurableArtifactReference` identifies content-addressed request/response
  artifacts; `IterationTurnStore` validates their envelope checksum and kind.
- `decision_progress_signature` binds a completed Provider decision step but
  currently cannot locate the response artifact needed for replay-free recovery.
- `ResponseCandidate`, `GroundingDecision`, and `AssistantTurnCommit` own later
  grounding and ledger transitions.
- `RuntimeCheckpointMetadata` remains the task-owned execution/recovery owner
  after task materialization and is not extended by this slice.

No existing field identifies the exact durable Provider response observation
from a completed pre-task decision step. Scanning the artifact directory or
reconstructing the reference from free text would create ambiguous recovery.

## Metadata impact note

Fact: the exact content-addressed Provider response artifact accepted for the
latest completed pre-task Provider decision.

Authoritative producer: `BoundedModelResponseController`, after a normalized
`LLMResponse` is saved and before `IterationTurnReducer.finish_provider_request`
commits the observed boundary.

Consumers: `IterationTurnReducer` invariant checks and
`BoundedModelResponseController` crash recovery.

Lifecycle: durable project state (conversation/run-scoped pre-task record plus
content-addressed artifact).

Control impact: recovery and completion.

Existing contracts reviewed: `IterationPendingProviderRequest`,
`IterationControlCursor`, `RootDecisionBudget`, `DurableArtifactReference`,
`ResponseCandidate`, `GroundingDecision`, `AssistantTurnCommit`,
`RuntimeCheckpointMetadata`, public metadata exports, reducer/store producers,
and bounded-response tests.

Decision: extend `IterationControlCursor` with one optional
`observed_provider_response_ref` using the existing reference contract.

Why no duplicate source of truth is created: the response body remains owned
only by the content-addressed artifact. The cursor stores only its validated
reference; `decision_progress_signature` continues to bind the request hash and
that reference, while the root budget continues to own usage.

Serialization and migration: the field defaults to `None`, so historical
`cru-2a-v1` records remain readable. Pending request and observed response are
mutually exclusive. A new request clears the prior observed reference and
progress signature atomically. A completed request requires both the reference
and signature. Historical completed records without a response reference are
readable but cannot claim replay-free Provider recovery.

Tests: metadata invalid combinations and JSON round-trip; reducer request /
observe transitions; crash with only a pending request fails closed without a
Provider call; crash after the observed record resumes exact parsing,
grounding, and assistant commit without a Provider call; corrupted/mismatched
response artifacts fail closed.

Documentation updates: contract catalog, API, session resume protocol, active
iteration plan/index, task-trajectory alignment, and implementation log.

## Recovery decisions

- Pending request, no observed reference: indeterminate transport outcome;
  controlled stop, zero automatic Provider replay.
- Observed response reference + valid signature/artifact: resume from that
  exact response, preserve charged budget, zero Provider replay.
- Missing/corrupt/wrong-kind/mismatched artifact: controlled stop.
- Existing response candidate or pending/committed response-only outcome:
  resume the same evidence handoff or assistant ledger payload without a
  Provider call; exact candidate/grounding/outcome/ledger mismatches fail
  closed.
- Existing controlled terminal outcome or active task binding: this controller
  does not reinterpret it as a fresh bounded-response run.

## Five-axis review evidence

### State and effects

| Trigger / input | State or side effect | Blast radius | Failure / recovery | Evidence |
| --- | --- | --- | --- | --- |
| request admitted | request artifact + `decision_requested` generation; one root call/round charged | one conversation/run | pending transport is indeterminate; controlled stop, zero replay | pending-boundary crash test |
| response returned | response artifact, then `decision_recorded` generation with exact ref/signature | one conversation/run | artifact saved but not bound remains pending; bound observation resumes with zero replay | unbound-artifact and observed-record crash tests |
| valid observed candidate | candidate/grounding generation | one response turn | retry returns the same evidence handoff or completes the same payload | approved/evidence candidate crash tests |
| assistant pending/committed | idempotent session ingress append + terminal generation | one assistant turn | exact message/payload resumes; record/artifact/ledger mismatch fails closed | pending, committed, and corrupted-ledger tests |

### Resource bounds

| Operation | Work per item | Cardinality | Max work per invocation | Yield / backlog policy |
| --- | --- | --- | --- | --- |
| Provider step | one bounded request and one content-addressed response write | initial + one repair | 2 Provider calls; existing root token budget | synchronous bounded step; no queue |
| durable response | normalize one response body | one per Provider call | 256,000 characters | oversize response becomes controlled stop |
| recovery lookup | exact turn pointer plus exact request/response refs | constant | no artifact-directory scan | missing/corrupt exact refs fail closed |

### Boundary behavior

| Input | Zero / empty | Exact boundary | Outside boundary | Blast radius / recovery | Test evidence |
| --- | --- | --- | --- | --- | --- |
| durable response content | later schema validation rejects empty response | accepted at configured character limit | limit + 1 produces controlled stop before candidate | one conversation/run; no repair or replay | exact-limit parameterized test |
| Provider attempts | no call only for a recovered post-Provider boundary | second call is the sole repair | third call impossible by fixed ordinal loop/root budget | controlled failure | invalid-observation remaining-repair and second-failure tests |
| recovery state | no request/observation with zero usage is a fresh turn | exact request + response ref/signature resumes | pending, unbound, corrupt, wrong-kind, or mismatched evidence fails closed | zero automatic replay | crash/corruption and metadata invariant tests |

Review conclusion: the slice preserves reducer/store/controller ownership,
introduces no new permission or mutation authority, keeps Provider and storage
work bounded, and improves replay correctness. The controller file remains
large, but extracting a second recovery owner in this slice would duplicate the
turn contract; module separation should occur only with a concrete additional
consumer.
