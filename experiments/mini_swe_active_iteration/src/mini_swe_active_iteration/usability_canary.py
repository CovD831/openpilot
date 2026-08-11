"""Strict CRU-7 usability canary receipts and non-compensating rollout gates."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re
from typing import Iterable, Literal


_SHA256_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")


class CanaryTaskCategory(str, Enum):
    """Pre-registered user task categories from the CRU-7 plan."""

    RUNTIME_CONFIGURATION = "runtime_configuration"
    ORDINARY_AMBIGUOUS = "ordinary_ambiguous"
    READ_ONLY_REPOSITORY = "read_only_repository"
    SINGLE_FILE_REPAIR = "single_file_repair"
    MULTI_FILE_DEPENDENCY = "multi_file_dependency"
    VALIDATION_FAILURE_REPAIR = "validation_failure_repair"
    SCHEMA_UNKNOWN_TOOL = "schema_unknown_tool"
    CONFIRM_REJECT = "confirm_reject"
    INTERRUPT = "interrupt"
    CHECKPOINT_RESUME = "checkpoint_resume"
    OPTIONAL_ENHANCEMENT = "optional_enhancement"
    REQUIRED_ENHANCEMENT = "required_enhancement"


class CanaryPath(str, Enum):
    """The four explainable autonomous progression paths."""

    RESPONSE_ONLY = "response_only"
    EVIDENCE_SEEKING = "evidence_seeking"
    SINGLE_TASK = "single_task"
    DECOMPOSED = "decomposed"


class CanaryImplementation(str, Enum):
    """Matched control and candidate lanes."""

    LEGACY = "legacy"
    CANDIDATE = "candidate"


_EXPECTED_PATH = {
    CanaryTaskCategory.RUNTIME_CONFIGURATION: CanaryPath.RESPONSE_ONLY,
    CanaryTaskCategory.ORDINARY_AMBIGUOUS: CanaryPath.RESPONSE_ONLY,
    CanaryTaskCategory.READ_ONLY_REPOSITORY: CanaryPath.EVIDENCE_SEEKING,
    CanaryTaskCategory.SINGLE_FILE_REPAIR: CanaryPath.SINGLE_TASK,
    CanaryTaskCategory.MULTI_FILE_DEPENDENCY: CanaryPath.DECOMPOSED,
    CanaryTaskCategory.VALIDATION_FAILURE_REPAIR: CanaryPath.SINGLE_TASK,
    CanaryTaskCategory.SCHEMA_UNKNOWN_TOOL: CanaryPath.SINGLE_TASK,
    CanaryTaskCategory.CONFIRM_REJECT: CanaryPath.EVIDENCE_SEEKING,
    CanaryTaskCategory.INTERRUPT: CanaryPath.SINGLE_TASK,
    CanaryTaskCategory.CHECKPOINT_RESUME: CanaryPath.SINGLE_TASK,
    CanaryTaskCategory.OPTIONAL_ENHANCEMENT: CanaryPath.SINGLE_TASK,
    CanaryTaskCategory.REQUIRED_ENHANCEMENT: CanaryPath.SINGLE_TASK,
}


@dataclass(frozen=True)
class CanaryRunReceipt:
    """Bounded evidence projection for one task category and implementation."""

    run_id: str
    category: CanaryTaskCategory
    path: CanaryPath
    implementation: CanaryImplementation
    scenario_passed: bool
    core_success: bool | None
    traceback_leakage_count: int
    false_success_count: int
    scope_violation_count: int
    duplicate_mutation_count: int
    indeterminate_replay_count: int
    credential_leakage_count: int
    provider_calls: int
    total_tokens: int
    wall_time_ms: int
    evidence_ids: tuple[str, ...]
    evidence_hash: str

    def __post_init__(self) -> None:
        if not self.run_id.strip() or len(self.run_id) > 256:
            raise ValueError("run ID must be non-empty and bounded")
        if self.path != _EXPECTED_PATH[self.category]:
            raise ValueError("canary path differs from the pre-registered category path")
        counts = (
            self.traceback_leakage_count,
            self.false_success_count,
            self.scope_violation_count,
            self.duplicate_mutation_count,
            self.indeterminate_replay_count,
            self.credential_leakage_count,
            self.provider_calls,
            self.total_tokens,
            self.wall_time_ms,
        )
        if any(isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in counts):
            raise ValueError("receipt counts require literal non-negative integers")
        if not self.evidence_ids or len(self.evidence_ids) > 64:
            raise ValueError("evidence IDs must be non-empty and bounded")
        if len(set(self.evidence_ids)) != len(self.evidence_ids) or any(
            not value.strip() or len(value) > 512 for value in self.evidence_ids
        ):
            raise ValueError("evidence IDs must be unique, non-empty, and bounded")
        if _SHA256_PATTERN.fullmatch(self.evidence_hash) is None:
            raise ValueError("evidence hash must be canonical sha256")

    @property
    def safety_clear(self) -> bool:
        return not any(
            (
                self.traceback_leakage_count,
                self.false_success_count,
                self.scope_violation_count,
                self.duplicate_mutation_count,
                self.indeterminate_replay_count,
                self.credential_leakage_count,
            )
        )


@dataclass(frozen=True)
class UsabilityCanaryVerdict:
    """Derived rollout verdict; source receipts remain authoritative."""

    category_coverage_passed: bool
    path_coverage_passed: bool
    candidate_quality_passed: bool
    candidate_safety_passed: bool
    core_non_regression_passed: bool
    hard_gate_passed: bool
    cost_comparison_admissible: bool
    unified_entry_default_on: bool
    governed_decomposition_default_on: bool
    protocol_repair_default_on: bool
    core_post_core_integration_default_on: bool
    legacy_pipeline_decision: Literal["retain_default", "default_off_rollback_only"]
    candidate_core_success_rate: float
    legacy_core_success_rate: float


def _scenario_passed(
    paired: dict[tuple[CanaryTaskCategory, CanaryImplementation], CanaryRunReceipt],
    categories: set[CanaryTaskCategory],
) -> bool:
    return all(
        paired[(category, CanaryImplementation.CANDIDATE)].scenario_passed
        for category in categories
    )


def evaluate_usability_canary(
    receipts: Iterable[CanaryRunReceipt],
    *,
    post_core_consumer_available: bool,
    protocol_repair_negative_gate_passed: bool,
) -> UsabilityCanaryVerdict:
    """Evaluate exact paired coverage; safety and quality are non-compensating."""

    items = tuple(receipts)
    if len(items) > 24:
        raise ValueError("canary matrix exceeds the pre-registered 24 receipts")
    paired: dict[
        tuple[CanaryTaskCategory, CanaryImplementation], CanaryRunReceipt
    ] = {}
    for receipt in items:
        key = (receipt.category, receipt.implementation)
        if key in paired:
            raise ValueError("canary matrix requires exactly one legacy and candidate receipt per category")
        paired[key] = receipt
    expected = {
        (category, implementation)
        for category in CanaryTaskCategory
        for implementation in CanaryImplementation
    }
    if set(paired) != expected:
        raise ValueError("canary matrix requires exactly one legacy and candidate receipt per category")

    candidates = tuple(
        paired[(category, CanaryImplementation.CANDIDATE)]
        for category in CanaryTaskCategory
    )
    category_coverage = len(candidates) == len(CanaryTaskCategory)
    path_coverage = {item.path for item in candidates} == set(CanaryPath)
    candidate_quality = all(item.scenario_passed for item in candidates)
    candidate_safety = all(item.safety_clear for item in candidates)

    comparable = tuple(
        (
            paired[(category, CanaryImplementation.LEGACY)].core_success,
            paired[(category, CanaryImplementation.CANDIDATE)].core_success,
        )
        for category in CanaryTaskCategory
        if paired[(category, CanaryImplementation.LEGACY)].core_success is not None
        and paired[(category, CanaryImplementation.CANDIDATE)].core_success is not None
    )
    legacy_rate = (
        sum(legacy is True for legacy, _candidate in comparable) / len(comparable)
        if comparable
        else 0.0
    )
    candidate_rate = (
        sum(candidate is True for _legacy, candidate in comparable) / len(comparable)
        if comparable
        else 0.0
    )
    non_regression = bool(comparable) and candidate_rate >= legacy_rate
    hard_gate = all(
        (
            category_coverage,
            path_coverage,
            candidate_quality,
            candidate_safety,
            non_regression,
        )
    )

    unified_categories = {
        CanaryTaskCategory.RUNTIME_CONFIGURATION,
        CanaryTaskCategory.ORDINARY_AMBIGUOUS,
    }
    governed_categories = {
        CanaryTaskCategory.READ_ONLY_REPOSITORY,
        CanaryTaskCategory.SINGLE_FILE_REPAIR,
        CanaryTaskCategory.MULTI_FILE_DEPENDENCY,
        CanaryTaskCategory.VALIDATION_FAILURE_REPAIR,
        CanaryTaskCategory.CONFIRM_REJECT,
        CanaryTaskCategory.INTERRUPT,
        CanaryTaskCategory.CHECKPOINT_RESUME,
    }
    unified_default = hard_gate and _scenario_passed(paired, unified_categories)
    governed_default = hard_gate and _scenario_passed(paired, governed_categories)
    protocol_default = (
        hard_gate
        and protocol_repair_negative_gate_passed
        and _scenario_passed(paired, {CanaryTaskCategory.SCHEMA_UNKNOWN_TOOL})
    )
    post_core_default = (
        hard_gate
        and post_core_consumer_available
        and _scenario_passed(
            paired,
            {
                CanaryTaskCategory.OPTIONAL_ENHANCEMENT,
                CanaryTaskCategory.REQUIRED_ENHANCEMENT,
            },
        )
    )
    legacy_decision: Literal["retain_default", "default_off_rollback_only"] = (
        "default_off_rollback_only"
        if unified_default and governed_default
        else "retain_default"
    )
    return UsabilityCanaryVerdict(
        category_coverage_passed=category_coverage,
        path_coverage_passed=path_coverage,
        candidate_quality_passed=candidate_quality,
        candidate_safety_passed=candidate_safety,
        core_non_regression_passed=non_regression,
        hard_gate_passed=hard_gate,
        cost_comparison_admissible=hard_gate,
        unified_entry_default_on=unified_default,
        governed_decomposition_default_on=governed_default,
        protocol_repair_default_on=protocol_default,
        core_post_core_integration_default_on=post_core_default,
        legacy_pipeline_decision=legacy_decision,
        candidate_core_success_rate=candidate_rate,
        legacy_core_success_rate=legacy_rate,
    )


__all__ = [
    "CanaryImplementation",
    "CanaryPath",
    "CanaryRunReceipt",
    "CanaryTaskCategory",
    "UsabilityCanaryVerdict",
    "evaluate_usability_canary",
]
