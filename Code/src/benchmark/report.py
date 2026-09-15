"""Descriptive benchmark reports and baseline/candidate comparisons."""

from __future__ import annotations

from typing import Iterable

from pydantic import BaseModel, ConfigDict, Field

from benchmark.process import BenchmarkProcessCost
from benchmark.runner import BenchmarkSuiteResult


class BenchmarkProcessCostSummary(BaseModel):
    """Mean process observations; no field is a quality score."""

    model_config = ConfigDict(extra="forbid")

    event_count: float = 0.0
    tool_calls: float = 0.0
    tool_successes: float = 0.0
    tool_failures: float = 0.0
    llm_requests: float = 0.0
    llm_responses: float = 0.0
    llm_failures: float = 0.0
    retry_count: float = 0.0
    verification_state_changes: float = 0.0
    phase_changes: float = 0.0
    tool_duration_seconds: float = 0.0
    elapsed_seconds: float | None = None
    prompt_tokens: float | None = None
    completion_tokens: float | None = None
    total_tokens: float | None = None
    reasoning_tokens: float | None = None


class BenchmarkCaseReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    repetitions: int = Field(ge=1)
    passed_count: int = Field(ge=0)
    failed_count: int = Field(ge=0)
    pending_count: int = Field(ge=0)
    acceptance_pass_rate: float = Field(ge=0.0, le=1.0)
    safety_violation_rate: float = Field(ge=0.0, le=1.0)
    pending_review_rate: float = Field(ge=0.0, le=1.0)
    safe_no_task_modification_rate: float | None = Field(default=None, ge=0.0, le=1.0)
    explicit_blocked_termination_rate: float | None = Field(default=None, ge=0.0, le=1.0)
    process_cost: BenchmarkProcessCostSummary


class BenchmarkSuiteReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    protocol_id: str
    protocol_version: str
    repeat_count: int = Field(ge=1)
    case_count: int = Field(ge=1)
    acceptance_pass_rate: float = Field(ge=0.0, le=1.0)
    safety_violation_rate: float = Field(ge=0.0, le=1.0)
    pending_review_rate: float = Field(ge=0.0, le=1.0)
    safe_no_task_modification_rate: float | None = Field(default=None, ge=0.0, le=1.0)
    explicit_blocked_termination_rate: float | None = Field(default=None, ge=0.0, le=1.0)
    process_cost: BenchmarkProcessCostSummary
    cases: list[BenchmarkCaseReport]


class BenchmarkCaseComparison(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    acceptance_pass_rate_delta: float
    safety_violation_rate_delta: float
    pending_review_rate_delta: float
    safe_no_task_modification_rate_delta: float | None
    explicit_blocked_termination_rate_delta: float | None
    process_cost_delta: BenchmarkProcessCostSummary


class BenchmarkComparison(BaseModel):
    model_config = ConfigDict(extra="forbid")

    baseline_protocol_id: str
    candidate_protocol_id: str
    baseline_protocol_version: str
    candidate_protocol_version: str
    acceptance_pass_rate_delta: float
    safety_violation_rate_delta: float
    pending_review_rate_delta: float
    safe_no_task_modification_rate_delta: float | None
    explicit_blocked_termination_rate_delta: float | None
    process_cost_delta: BenchmarkProcessCostSummary
    case_comparisons: list[BenchmarkCaseComparison]


def build_suite_report(suite: BenchmarkSuiteResult) -> BenchmarkSuiteReport:
    """Aggregate repeated runs into separate acceptance/safety/cost views."""

    if not suite.runs:
        raise ValueError("cannot report an empty benchmark suite")
    grouped: dict[str, list] = {}
    for run in suite.runs:
        grouped.setdefault(run.case_id, []).append(run)
    case_reports = [_build_case_report(case_id, runs) for case_id, runs in grouped.items()]
    return BenchmarkSuiteReport(
        protocol_id=suite.protocol_id,
        protocol_version=suite.protocol_version,
        repeat_count=suite.repeat_count,
        case_count=len(case_reports),
        acceptance_pass_rate=_rate(sum(run.passed is True for run in suite.runs), len(suite.runs)),
        safety_violation_rate=_rate(sum(_has_safety_violation(run) for run in suite.runs), len(suite.runs)),
        pending_review_rate=_rate(sum(run.passed is None for run in suite.runs), len(suite.runs)),
        safe_no_task_modification_rate=_indicator_rate(
            suite.runs, "safe_no_task_modification"
        ),
        explicit_blocked_termination_rate=_indicator_rate(
            suite.runs, "explicit_blocked_termination"
        ),
        process_cost=_mean_process_cost([run.process_cost for run in suite.runs]),
        cases=case_reports,
    )


def compare_suite_reports(
    baseline: BenchmarkSuiteReport,
    candidate: BenchmarkSuiteReport,
) -> BenchmarkComparison:
    """Compare matched reports; deltas are always candidate minus baseline."""

    if (baseline.protocol_id, baseline.protocol_version) != (
        candidate.protocol_id,
        candidate.protocol_version,
    ):
        raise ValueError("baseline and candidate must use the same benchmark protocol")
    baseline_cases = {item.case_id: item for item in baseline.cases}
    candidate_cases = {item.case_id: item for item in candidate.cases}
    if set(baseline_cases) != set(candidate_cases):
        raise ValueError("baseline and candidate must contain the same case ids")
    case_comparisons = [
        _compare_case(baseline_cases[case_id], candidate_cases[case_id])
        for case_id in sorted(baseline_cases)
    ]
    return BenchmarkComparison(
        baseline_protocol_id=baseline.protocol_id,
        candidate_protocol_id=candidate.protocol_id,
        baseline_protocol_version=baseline.protocol_version,
        candidate_protocol_version=candidate.protocol_version,
        acceptance_pass_rate_delta=candidate.acceptance_pass_rate - baseline.acceptance_pass_rate,
        safety_violation_rate_delta=candidate.safety_violation_rate - baseline.safety_violation_rate,
        pending_review_rate_delta=candidate.pending_review_rate - baseline.pending_review_rate,
        safe_no_task_modification_rate_delta=_subtract_optional(
            candidate.safe_no_task_modification_rate,
            baseline.safe_no_task_modification_rate,
        ),
        explicit_blocked_termination_rate_delta=_subtract_optional(
            candidate.explicit_blocked_termination_rate,
            baseline.explicit_blocked_termination_rate,
        ),
        process_cost_delta=_subtract_process_cost(candidate.process_cost, baseline.process_cost),
        case_comparisons=case_comparisons,
    )


def _build_case_report(case_id: str, runs: list) -> BenchmarkCaseReport:
    total = len(runs)
    return BenchmarkCaseReport(
        case_id=case_id,
        repetitions=total,
        passed_count=sum(run.passed is True for run in runs),
        failed_count=sum(run.passed is False for run in runs),
        pending_count=sum(run.passed is None for run in runs),
        acceptance_pass_rate=_rate(sum(run.passed is True for run in runs), total),
        safety_violation_rate=_rate(sum(_has_safety_violation(run) for run in runs), total),
        pending_review_rate=_rate(sum(run.passed is None for run in runs), total),
        safe_no_task_modification_rate=_indicator_rate(
            runs, "safe_no_task_modification"
        ),
        explicit_blocked_termination_rate=_indicator_rate(
            runs, "explicit_blocked_termination"
        ),
        process_cost=_mean_process_cost([run.process_cost for run in runs]),
    )


def _has_safety_violation(run) -> bool:
    return any(
        check.name == "write_scope" and not check.passed
        for check in run.evaluation.checks
    )


def _indicator_rate(runs: list, check_name: str) -> float | None:
    checks = [
        check
        for run in runs
        for check in run.evaluation.checks
        if check.name == check_name
    ]
    if not checks:
        return None
    return _rate(sum(check.passed for check in checks), len(checks))


def _rate(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def _mean_process_cost(costs: Iterable[BenchmarkProcessCost]) -> BenchmarkProcessCostSummary:
    values = list(costs)
    return BenchmarkProcessCostSummary(
        event_count=_mean([item.event_count for item in values]),
        tool_calls=_mean([item.tool_calls for item in values]),
        tool_successes=_mean([item.tool_successes for item in values]),
        tool_failures=_mean([item.tool_failures for item in values]),
        llm_requests=_mean([item.llm_requests for item in values]),
        llm_responses=_mean([item.llm_responses for item in values]),
        llm_failures=_mean([item.llm_failures for item in values]),
        retry_count=_mean([item.retry_count for item in values]),
        verification_state_changes=_mean([item.verification_state_changes for item in values]),
        phase_changes=_mean([item.phase_changes for item in values]),
        tool_duration_seconds=_mean([item.tool_duration_seconds for item in values]),
        elapsed_seconds=_mean_optional([item.elapsed_seconds for item in values]),
        prompt_tokens=_mean_optional([item.prompt_tokens for item in values]),
        completion_tokens=_mean_optional([item.completion_tokens for item in values]),
        total_tokens=_mean_optional([item.total_tokens for item in values]),
        reasoning_tokens=_mean_optional([item.reasoning_tokens for item in values]),
    )


def _subtract_process_cost(
    candidate: BenchmarkProcessCostSummary,
    baseline: BenchmarkProcessCostSummary,
) -> BenchmarkProcessCostSummary:
    return BenchmarkProcessCostSummary(
        **{
            field: _subtract_optional(getattr(candidate, field), getattr(baseline, field))
            for field in BenchmarkProcessCostSummary.model_fields
        }
    )


def _compare_case(
    baseline: BenchmarkCaseReport,
    candidate: BenchmarkCaseReport,
) -> BenchmarkCaseComparison:
    return BenchmarkCaseComparison(
        case_id=baseline.case_id,
        acceptance_pass_rate_delta=candidate.acceptance_pass_rate - baseline.acceptance_pass_rate,
        safety_violation_rate_delta=candidate.safety_violation_rate - baseline.safety_violation_rate,
        pending_review_rate_delta=candidate.pending_review_rate - baseline.pending_review_rate,
        safe_no_task_modification_rate_delta=_subtract_optional(
            candidate.safe_no_task_modification_rate,
            baseline.safe_no_task_modification_rate,
        ),
        explicit_blocked_termination_rate_delta=_subtract_optional(
            candidate.explicit_blocked_termination_rate,
            baseline.explicit_blocked_termination_rate,
        ),
        process_cost_delta=_subtract_process_cost(candidate.process_cost, baseline.process_cost),
    )


def _mean(values: list[int | float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _mean_optional(values: list[int | float | None]) -> float | None:
    known = [value for value in values if value is not None]
    return sum(known) / len(known) if known else None


def _subtract_optional(candidate: float | None, baseline: float | None) -> float | None:
    if candidate is None or baseline is None:
        return None
    return candidate - baseline
