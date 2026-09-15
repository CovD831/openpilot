"""Typed loader for the small OpenPilot benchmark case manifest.

The benchmark manifest describes evaluation inputs and acceptance boundaries.
It does not execute tasks or become a second runtime task contract; execution
continues to use the existing ``RawTaskInput`` and task-pool runner.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from runtime_diagnostics.raw_task import RawTaskInput


BenchmarkCategory = Literal["readonly", "mutation", "boundary", "recovery"]
BenchmarkEvaluationMode = Literal["deterministic", "trajectory_review"]
BenchmarkSource = Literal[
    "openpilot_local",
    "manual_existing",
    "swe_style",
    "terminal_style",
]


class BenchmarkManifestError(ValueError):
    """Raised when a benchmark manifest cannot be loaded as a valid suite."""


class BenchmarkProvenance(BaseModel):
    """Origin information retained for every benchmark case."""

    model_config = ConfigDict(extra="forbid")

    source: BenchmarkSource
    source_instance_id: str = ""
    source_revision: str = ""
    adaptation_note: str = ""


class BenchmarkAcceptance(BaseModel):
    """Machine-checkable boundary plus optional trajectory review guidance."""

    model_config = ConfigDict(extra="forbid")

    mode: BenchmarkEvaluationMode = "deterministic"
    expected_status: Literal["success", "failed", "blocked", "cancelled"] = "success"
    allowed_write_paths: list[str] = Field(default_factory=list)
    required_write_paths: list[str] = Field(default_factory=list)
    system_generated_paths: list[str] = Field(default_factory=list)
    required_files: list[str] = Field(default_factory=list)
    required_validation_commands: list[str] = Field(default_factory=list)
    review_requirements: list[str] = Field(default_factory=list)

    @field_validator(
        "allowed_write_paths",
        "required_write_paths",
        "system_generated_paths",
        "required_files",
        "required_validation_commands",
        "review_requirements",
    )
    @classmethod
    def _items_must_be_non_blank(cls, values: list[str]) -> list[str]:
        normalized = [str(value).strip() for value in values]
        if any(not value for value in normalized):
            raise ValueError("benchmark acceptance items must not be blank")
        return normalized

    @field_validator(
        "allowed_write_paths",
        "required_write_paths",
        "system_generated_paths",
        "required_files",
    )
    @classmethod
    def _paths_must_be_relative(cls, values: list[str]) -> list[str]:
        for value in values:
            path = Path(value)
            if path.is_absolute() or ".." in path.parts:
                raise ValueError("benchmark paths must be relative and stay inside the fixture")
        return values


class BenchmarkCase(BaseModel):
    """One reproducible task input and its acceptance boundary."""

    model_config = ConfigDict(extra="forbid")

    case_id: str
    category: BenchmarkCategory
    task: RawTaskInput
    fixture_path: str = ""
    provenance: BenchmarkProvenance = Field(
        default_factory=lambda: BenchmarkProvenance(source="openpilot_local")
    )
    acceptance: BenchmarkAcceptance = Field(default_factory=BenchmarkAcceptance)

    @field_validator("case_id", "fixture_path")
    @classmethod
    def _strings_must_be_normalized(cls, value: str, info) -> str:
        normalized = str(value).strip()
        if info.field_name == "case_id" and not normalized:
            raise ValueError("case_id must not be blank")
        if info.field_name == "fixture_path" and normalized:
            path = Path(normalized)
            if path.is_absolute() or ".." in path.parts:
                raise ValueError("fixture_path must be relative")
        return normalized

    @model_validator(mode="after")
    def _validate_category_boundary(self) -> "BenchmarkCase":
        if self.task.task_id != self.case_id:
            raise ValueError("task_id must match case_id")
        if self.category == "readonly" and self.acceptance.allowed_write_paths:
            raise ValueError("readonly case cannot declare a write scope")
        if self.acceptance.mode == "trajectory_review" and not self.acceptance.review_requirements:
            raise ValueError("trajectory_review case requires review_requirements")
        return self


class BenchmarkProtocol(BaseModel):
    """Frozen execution and reporting rules for one benchmark suite version."""

    model_config = ConfigDict(extra="forbid")

    protocol_id: str
    version: str
    repeat_count: int = Field(ge=1, le=100)
    temperature: float = Field(ge=0.0, le=2.0)
    cache_enabled: bool = False
    no_total_score: bool = True
    primary_metrics: list[str] = Field(min_length=1)
    task_order: Literal["manifest_order", "case_id"] = "manifest_order"

    @field_validator("protocol_id", "version", "primary_metrics")
    @classmethod
    def _protocol_fields_must_be_non_blank(cls, value):
        if isinstance(value, list):
            normalized = [str(item).strip() for item in value]
            if any(not item for item in normalized):
                raise ValueError("protocol metric names must not be blank")
            return normalized
        normalized = str(value).strip()
        if not normalized:
            raise ValueError("protocol identity fields must not be blank")
        return normalized

    @model_validator(mode="after")
    def _total_score_is_disabled(self) -> "BenchmarkProtocol":
        if not self.no_total_score:
            raise ValueError("benchmark protocol must not define a total score")
        return self


DEFAULT_BENCHMARK_PATH = (
    Path(__file__).resolve().parents[2] / "tasks" / "benchmark_v0" / "cases.jsonl"
)
DEFAULT_PROTOCOL_PATH = DEFAULT_BENCHMARK_PATH.parent / "protocol.json"


def load_benchmark_cases(path: str | Path = DEFAULT_BENCHMARK_PATH) -> list[BenchmarkCase]:
    """Load and validate a JSON, JSONL, or directory benchmark manifest."""

    source = Path(path)
    if source.is_dir():
        cases: list[BenchmarkCase] = []
        for child in sorted(source.iterdir()):
            if child.suffix.lower() not in {".json", ".jsonl"}:
                continue
            cases.extend(load_benchmark_cases(child))
        return _ensure_unique_case_ids(cases, source)

    try:
        if source.suffix.lower() == ".jsonl":
            payloads = [
                json.loads(line)
                for line in source.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
        elif source.suffix.lower() == ".json":
            payload = json.loads(source.read_text(encoding="utf-8"))
            payloads = payload if isinstance(payload, list) else [payload]
        else:
            raise BenchmarkManifestError(f"unsupported benchmark manifest: {source}")
    except json.JSONDecodeError as exc:
        raise BenchmarkManifestError(f"invalid JSON in benchmark manifest {source}: {exc}") from exc

    try:
        cases = [BenchmarkCase.model_validate(payload) for payload in payloads]
    except (TypeError, ValueError) as exc:
        raise BenchmarkManifestError(f"invalid benchmark manifest {source}: {exc}") from exc
    return _ensure_unique_case_ids(cases, source)


def load_benchmark_protocol(path: str | Path = DEFAULT_PROTOCOL_PATH) -> BenchmarkProtocol:
    """Load the frozen execution/reporting protocol for the benchmark suite."""

    source = Path(path)
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
        protocol = BenchmarkProtocol.model_validate(payload)
    except json.JSONDecodeError as exc:
        raise BenchmarkManifestError(f"invalid JSON in benchmark protocol {source}: {exc}") from exc
    except (TypeError, ValueError) as exc:
        raise BenchmarkManifestError(f"invalid benchmark protocol {source}: {exc}") from exc
    return protocol


def _ensure_unique_case_ids(cases: list[BenchmarkCase], source: Path) -> list[BenchmarkCase]:
    seen: set[str] = set()
    for case in cases:
        if case.case_id in seen:
            raise BenchmarkManifestError(f"duplicate case_id in {source}: {case.case_id}")
        seen.add(case.case_id)
    return cases
