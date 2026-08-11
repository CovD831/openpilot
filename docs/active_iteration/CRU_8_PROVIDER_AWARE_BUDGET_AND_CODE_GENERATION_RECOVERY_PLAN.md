# CRU-8 Provider-aware Budget and Code-generation Recovery Plan

## Status

Implementation completed for development release `0.1.0.dev7` from the accepted
dev6 baseline `46e1ed4`.

## Objective

Resolve the real single-file generation failures in trajectories
`a1ebfff815764d2caf003f8c23f70c6d` and
`eaaaa48ca2734e34a3412429c3fc2992`. Both requests had roughly 530 prompt
tokens, reserved the existing 3,500-token code-generation ceiling, consumed all
3,500 completion tokens as reasoning, and returned `finish_reason=length`.

The accepted behavior must separate input-context pressure from output-length
pressure, use low or disabled reasoning after authoritative planning, retry one
truncated full-file generation from scratch with a larger typed reservation,
and never expose truncated source to a writer.

## Metadata impact note

```text
Facts: explicit provider completion capability; initial and recovery completion
  ceilings; one source-linked length-recovery reservation; post-plan code-emission
  reasoning intent; observed terminal generation outcome
Authoritative producers: LLMSettings owns configured provider capability;
  RuntimeBudgetMetadata owns the task budget ledger; CodeGenerator owns provider
  generation attempts; ToolEventLoopRunner owns the tool lifecycle; Task owns the
  authorized write scope
Consumers: context request builder, reasoning resolver, enhancement completion
  coordinator, code generator, diagnostics, writer chaining, completion gate
Lifecycle: configured capability plus runtime-only request/reservation evidence;
  existing checkpoint/runtime budget serialization remains authoritative
Control impact: context budget, completion budget, reasoning, bounded retry,
  decomposition/recovery, and completion
Existing contracts reviewed: ReasoningPolicy, ResolvedReasoningPolicy,
  RuntimeBudgetMetadata, EnhancementCompletionBudgetPolicy,
  EnhancementCompletionPurposeLimit, EnhancementCompletionRequest,
  EnhancementCompletionReservation, EnhancementCompletionReconciliation,
  ProviderBudgetDiagnostic, ToolInputMetadata, ToolResultMetadata,
  CodeArtifactMetadata, FailureMetadata, DecompositionPolicyDecision, Task
Decision: extend existing strict owned values and add a config-owned versioned
  capability value; add no MetadataKind and no generalized relationship layer
Why no duplicate source of truth is created: provider capability is configured
  once and projected into requests; the runtime budget ledger remains the sole
  reservation/reconciliation authority; only the final complete CodeArtifact is
  eligible for writer chaining
Serialization and migration: new fields have backward-compatible defaults equal
  to current ceilings; historical RuntimeBudgetMetadata remains readable; invalid
  recovery ceilings and conflicting capability values fail validation
Tests: metadata round trips and invalid states; provider-aware prompt/output
  calculation; post-plan reasoning; observed length with known/unknown usage;
  exactly-one recovery; double-length fail-closed/decomposition; writer isolation;
  frozen real-trajectory replay; full regression and live canary
Documentation updates: CONTRACT_CATALOG, API, .env.example, context-management
  guidance, task-trajectory implementation log, development release
```

## Required state transitions

1. Assemble required context under a provider-aware prompt budget. Compact only
   source-linked non-required dialog/observations; never compact permissions,
   validation commands, task identity, or write scope.
2. Resolve code generation after planning to disabled reasoning when explicitly
   supported, otherwise low effort when supported, otherwise provider default.
3. Reserve the initial code-generation output independently from prompt context.
4. On `stop`, return the complete parsed CodeArtifact.
5. On `length` with observed usage, discard the response, reconcile the first
   reservation, reserve one larger recovery request linked by `recovery_of`, and
   regenerate the full source from the same authoritative task context.
6. On a second `length`, missing usage, unavailable larger reservation, or invalid
   complete source, return a typed recoverable failure/decomposition signal with
   no CodeArtifact and no writer call.
7. Preserve the dev6 durable chain: complete CodeArtifact -> scoped writer ->
   mutation receipt -> exact validation -> completion evidence.

## Initial canary bounds

- Configured prompt budget remains a caller ceiling, but the effective value is
  also bounded by provider context minus planned output, tool schemas, and safety
  reserve.
- Code generation: initial floor 8,000, initial ceiling 16,000, recovery ceiling
  32,000, one recovery only.
- Shared enhancement completion pool: 64,000 for the development canary.
- Full-file generation uses disabled/low reasoning after planning and temperature
  0.2. Planning, diagnosis, and decomposition retain their existing reasoning.
- A second length outcome stops generation and requests decomposition; it never
  increases the single-request ceiling again.

## Acceptance gates

- The two frozen length trajectories reproduce before the change and recover
  without writing the first truncated output after the change.
- A 523-token prompt does not invoke dialog compaction merely because output
  generation reaches its ceiling.
- Exactly one recovery request is possible and it has a larger reservation.
- Unknown usage, provider errors, or exhausted budget do not masquerade as length
  recovery.
- Writer calls are zero after terminal generation failure and exactly one after
  successful recovery.
- The original Snake request creates `snake_game.py` and passes an exact syntax
  validation in a temporary project canary.
- Full tests, Ruff, compileall, and `git diff --check` pass before release.

## Completion evidence

- The shared enhancement pool is 64,000 tokens; code generation reserves
  8,000–16,000 initially and may perform exactly one source-linked full
  regeneration up to 32,000, bounded by the explicit provider output cap.
- Post-plan single-file full emission requests disabled reasoning through the
  configured capability profile. Ambiguous or multi-target generation retains
  provider-default reasoning.
- `length` output is always discarded. Known usage may authorize one larger
  retry; unknown usage, an unavailable larger reservation, or a second length
  produces `decompose_required` and no writer-visible artifact.
- Provider-aware prompt selection is bounded by the configured prompt ceiling,
  the soft context-window ratio, and context-window minus planned output and
  safety reserve. Required authority and task facts remain non-compactable.
- Complete `Code/tests`, touched Ruff, compileall, build, editable-install, and
  release hash evidence are recorded in the dev7 release document and task
  trajectory implementation log.
