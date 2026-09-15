"""Small fixture runner that bridges benchmark cases to the existing task pool."""

from __future__ import annotations

import re
import shlex
import shutil
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Callable, Mapping

from pydantic import BaseModel, ConfigDict, Field

from benchmark.evaluator import BenchmarkEvidence, BenchmarkEvaluation, evaluate_case
from benchmark.manifest import (
    BenchmarkCase,
    BenchmarkProtocol,
    DEFAULT_BENCHMARK_PATH,
    DEFAULT_PROTOCOL_PATH,
    load_benchmark_cases,
    load_benchmark_protocol,
)
from benchmark.process import BenchmarkProcessCost, extract_process_cost
from runtime_diagnostics import DiagnosticRecorder, RuntimeTaskPoolRunner


BenchmarkExecutor = Callable[[str, dict[str, Any]], dict[str, Any]]
BenchmarkExecutorFactory = Callable[[DiagnosticRecorder], BenchmarkExecutor]
BenchmarkWorkspaceFactory = Callable[[BenchmarkCase, int], str | Path | None]


class BenchmarkRunnerError(RuntimeError):
    """Raised when a benchmark case cannot be materialized or validated."""


class BenchmarkRunResult(BaseModel):
    """Compact result for one benchmark case."""

    model_config = ConfigDict(extra="forbid")

    case_id: str
    repeat_index: int = Field(default=1, ge=1)
    passed: bool | None
    evaluation: BenchmarkEvaluation
    runtime_status: str
    modified_files: list[str] = Field(default_factory=list)
    task_modified_files: list[str] = Field(default_factory=list)
    system_generated_files: list[str] = Field(default_factory=list)
    final_answer_present: bool = False
    final_answer_artifact_path: str | None = None
    validation_exit_codes: dict[str, int] = Field(default_factory=dict)
    process_cost: BenchmarkProcessCost = Field(default_factory=BenchmarkProcessCost)
    runtime_error: str | None = None


class BenchmarkSuiteResult(BaseModel):
    """All repeated runs for one frozen benchmark protocol."""

    model_config = ConfigDict(extra="forbid")

    protocol_id: str
    protocol_version: str
    repeat_count: int = Field(ge=1)
    runs: list[BenchmarkRunResult]


class BenchmarkRunner:
    """Run benchmark cases in isolated fixture directories.

    The executor is the only injected runtime behavior. Validation commands
    come from the typed case manifest and are executed without a shell after
    the executor returns.
    """

    def __init__(
        self,
        executor: BenchmarkExecutor,
        *,
        manifest_path: str | Path = DEFAULT_BENCHMARK_PATH,
        workspace_root: str | Path | None = None,
        recorder: DiagnosticRecorder | None = None,
        validation_timeout_seconds: float = 60.0,
    ) -> None:
        self.executor = executor
        self.manifest_path = Path(manifest_path)
        self.fixture_root = self.manifest_path.parent
        self.workspace_root = Path(workspace_root).resolve() if workspace_root else None
        self.recorder = recorder or DiagnosticRecorder()
        self.validation_timeout_seconds = validation_timeout_seconds

    def run_cases(self, cases: list[BenchmarkCase] | None = None) -> list[BenchmarkRunResult]:
        selected = cases if cases is not None else load_benchmark_cases(self.manifest_path)
        return [self.run_case(case) for case in selected]

    def run_case(self, case: BenchmarkCase) -> BenchmarkRunResult:
        with TemporaryDirectory(prefix=f"openpilot-benchmark-{case.case_id}-") as temp_dir:
            project_root = self._materialize_case(case, Path(temp_dir))
            before = _snapshot(project_root)
            captured: dict[str, Any] = {}

            def recording_executor(goal: str, context: dict[str, Any]) -> dict[str, Any]:
                result = self.executor(goal, context)
                captured["result"] = result
                return result

            task = case.task.model_copy(
                update={
                    "context": {
                        **case.task.context,
                        "project_path": str(project_root),
                        "benchmark_case_id": case.case_id,
                        "task_type": case.category,
                        "read_files": _resolve_workspace_paths(
                            project_root,
                            case.acceptance.required_files,
                        ),
                        "write_files": _resolve_workspace_paths(
                            project_root,
                            case.acceptance.allowed_write_paths,
                        ),
                        "validation_commands": list(
                            case.acceptance.required_validation_commands
                        ),
                        "validation_command": (
                            case.acceptance.required_validation_commands[0]
                            if case.acceptance.required_validation_commands
                            else ""
                        ),
                    }
                }
            )
            task_result = RuntimeTaskPoolRunner(
                recording_executor,
                recorder=self.recorder,
            ).run_task(task)
            after = _snapshot(project_root)
            modified_files = sorted(
                path
                for path in set(before) | set(after)
                if before.get(path) != after.get(path)
            )
            validation_exit_codes = self._run_validations(case, project_root)
            run_id = task_result.run_id
            run_record = self.recorder.load_run(run_id)
            trajectory_events = self.recorder.load_trajectory_events(run_id, limit=0)
            raw_result = captured.get("result")
            runtime_status = _runtime_status(raw_result, task_result.success)
            final_answer = _extract_final_answer(raw_result)
            final_answer_artifact_path: str | None = None
            if final_answer:
                final_answer_artifact_path = str(
                    self.recorder.record_artifact(
                        run_id,
                        kind="benchmark_final_answer",
                        content=final_answer,
                        filename="final_answer.txt",
                        content_type="text/plain; charset=utf-8",
                    ).path
                )
            task_modified_files = sorted(
                path
                for path in modified_files
                if not _matches_any_path(path, case.acceptance.system_generated_paths)
            )
            evidence = BenchmarkEvidence(
                status=runtime_status,
                available_files=sorted(after),
                modified_files=modified_files,
                passed_validation_commands=[
                    command
                    for command, exit_code in validation_exit_codes.items()
                    if exit_code == 0
                ],
                trajectory_review_completed=bool(
                    raw_result.get("trajectory_review_completed")
                    if isinstance(raw_result, Mapping)
                    else False
                ),
                final_answer_present=bool(final_answer_artifact_path),
                final_answer_artifact_path=final_answer_artifact_path,
                safe_no_task_modification=(
                    not task_modified_files if case.category == "boundary" else None
                ),
                explicit_blocked_termination=(
                    _explicit_blocked_termination(raw_result, runtime_status)
                    if case.category == "boundary"
                    else None
                ),
            )
            evaluation = evaluate_case(case, evidence)
            system_generated_files = sorted(
                path
                for path in modified_files
                if _matches_any_path(path, case.acceptance.system_generated_paths)
            )
            runtime_error = task_result.error if not task_result.success else None
            return BenchmarkRunResult(
                case_id=case.case_id,
                passed=evaluation.passed,
                evaluation=evaluation,
                runtime_status=runtime_status,
                modified_files=modified_files,
                task_modified_files=task_modified_files,
                system_generated_files=system_generated_files,
                final_answer_present=bool(final_answer_artifact_path),
                final_answer_artifact_path=final_answer_artifact_path,
                validation_exit_codes=validation_exit_codes,
                process_cost=extract_process_cost(
                    trajectory_events,
                    run_record.model_dump(mode="python") if run_record else None,
                ),
                runtime_error=runtime_error,
            )

    def _materialize_case(self, case: BenchmarkCase, temp_root: Path) -> Path:
        if not case.fixture_path:
            if self.workspace_root is None:
                raise BenchmarkRunnerError(
                    f"case {case.case_id} has no fixture_path; provide workspace_root explicitly"
                )
            if not self.workspace_root.is_dir():
                raise BenchmarkRunnerError(f"benchmark workspace does not exist: {self.workspace_root}")
            return self.workspace_root
        source = self.fixture_root / case.fixture_path
        if not source.is_dir():
            raise BenchmarkRunnerError(f"benchmark fixture does not exist: {source}")
        target = temp_root / "project"
        shutil.copytree(source, target)
        return target

    def _run_validations(self, case: BenchmarkCase, project_root: Path) -> dict[str, int]:
        results: dict[str, int] = {}
        for command in case.acceptance.required_validation_commands:
            argv = _safe_argv(command)
            try:
                completed = subprocess.run(
                    argv,
                    cwd=project_root,
                    capture_output=True,
                    text=True,
                    timeout=self.validation_timeout_seconds,
                    check=False,
                )
            except (OSError, subprocess.SubprocessError):
                results[command] = 1
            else:
                results[command] = completed.returncode
        return results


def _safe_argv(command: str) -> list[str]:
    if any(token in command for token in ("&&", "||", ";", "|", ">", "<", "`", "$")):
        raise BenchmarkRunnerError(f"shell syntax is not allowed in validation command: {command}")
    argv = shlex.split(command)
    if not argv or argv[0] not in {"python", "python3"}:
        raise BenchmarkRunnerError(f"validation command must start with python: {command}")
    return argv


def _snapshot(root: Path) -> dict[str, bytes]:
    ignored = {".git", ".venv", "__pycache__", ".pytest_cache"}
    snapshot: dict[str, bytes] = {}
    for path in root.rglob("*"):
        if not path.is_file() or ignored.intersection(path.parts):
            continue
        snapshot[str(path.relative_to(root))] = path.read_bytes()
    return snapshot


def _runtime_status(raw_result: Any, task_success: bool) -> str:
    if isinstance(raw_result, Mapping):
        status = str(raw_result.get("status") or "").strip()
        if status in {"success", "failed", "blocked", "cancelled"}:
            return status
        if raw_result.get("success") is True:
            return "success"
    return "success" if task_success else "failed"


_FINAL_ANSWER_KEYS = ("final_answer", "answer", "final_output", "result_summary")
_CREDENTIAL_PATTERN = re.compile(
    r"(?i)(?:sk-[a-z0-9_-]{16,}|(?:api[_ -]?key|authorization|bearer)\s*[:=]\s*[^\s,;]+)"
)
_RAW_PROVIDER_ERROR_PATTERN = re.compile(
    r"(?is)^(?:http\s+\d{3}\b|provider(?:\s+request)?\s+(?:error|failed)\b|"
    r"(?:authentication|rate[ -]?limit|connection)error\b)"
)


def _extract_final_answer(raw_result: Any) -> str | None:
    """Extract only explicitly final-result-shaped text for human review.

    This intentionally ignores prompt, error, response-preview, and provider
    transport fields. It is a review artifact, never an acceptance signal.
    """

    if not isinstance(raw_result, Mapping):
        return None
    candidates: list[Any] = []
    for key in _FINAL_ANSWER_KEYS:
        if key in raw_result:
            candidates.append(raw_result[key])
    session_result = raw_result.get("session_result")
    if isinstance(session_result, Mapping):
        for key in _FINAL_ANSWER_KEYS + ("final_result",):
            if key in session_result:
                candidates.append(session_result[key])
    if "final_result" in raw_result:
        candidates.append(raw_result["final_result"])
    for candidate in candidates:
        text = _final_answer_text(candidate)
        if text:
            return text
    return None


def _final_answer_text(value: Any, *, depth: int = 0) -> str | None:
    if depth > 6:
        return None
    if hasattr(value, "model_dump") and callable(value.model_dump):
        try:
            value = value.model_dump(mode="python")
        except (TypeError, ValueError):
            return None
    if isinstance(value, str):
        text = value.strip()
        if not text or text == "completed" or _RAW_PROVIDER_ERROR_PATTERN.match(text):
            return None
        return _CREDENTIAL_PATTERN.sub("[REDACTED]", text)[:20000]
    if isinstance(value, Mapping):
        for key in (
            "final_answer",
            "answer",
            "final_output",
            "content",
            "summary",
            "result_summary",
            "attributes",
        ):
            if key in value:
                text = _final_answer_text(value[key], depth=depth + 1)
                if text:
                    return text
        for key in ("result", "subtask_results"):
            nested = value.get(key)
            if isinstance(nested, list):
                for item in reversed(nested):
                    text = _final_answer_text(item, depth=depth + 1)
                    if text:
                        return text
            else:
                text = _final_answer_text(nested, depth=depth + 1)
                if text:
                    return text
    elif isinstance(value, (list, tuple)):
        for item in reversed(value):
            text = _final_answer_text(item, depth=depth + 1)
            if text:
                return text
    return None


def _explicit_blocked_termination(raw_result: Any, runtime_status: str) -> bool:
    if runtime_status != "blocked" or not isinstance(raw_result, Mapping):
        return False
    if str(raw_result.get("status") or "").strip() == "blocked":
        return True
    for key in ("session_result", "runtime_report"):
        nested = raw_result.get(key)
        if isinstance(nested, Mapping) and str(nested.get("status") or "").strip() == "blocked":
            return True
    return False


def _matches_any_path(path: str, patterns: list[str]) -> bool:
    normalized = _normalize_relative_path(path)
    for pattern in patterns:
        normalized_pattern = _normalize_relative_path(pattern)
        if not normalized_pattern:
            continue
        if normalized_pattern.endswith("/"):
            if (
                normalized.startswith(normalized_pattern)
                or f"/{normalized_pattern}" in f"/{normalized}"
            ):
                return True
        elif normalized_pattern.startswith("**/"):
            if normalized.endswith(normalized_pattern[3:]):
                return True
        elif normalized == normalized_pattern:
            return True
    return False


def _normalize_relative_path(value: str) -> str:
    normalized = str(value).strip()
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized


def _resolve_workspace_paths(root: Path, paths: list[str]) -> list[str]:
    resolved: list[str] = []
    for path in paths:
        candidate = Path(path)
        absolute = candidate if candidate.is_absolute() else root / candidate
        value = str(absolute.resolve(strict=False))
        if value not in resolved:
            resolved.append(value)
    return resolved


class BenchmarkSuiteRunner:
    """Repeat cases under one frozen protocol with isolated trajectories."""

    def __init__(
        self,
        executor: BenchmarkExecutor | None = None,
        *,
        executor_factory: BenchmarkExecutorFactory | None = None,
        protocol: BenchmarkProtocol | None = None,
        protocol_path: str | Path = DEFAULT_PROTOCOL_PATH,
        manifest_path: str | Path = DEFAULT_BENCHMARK_PATH,
        workspace_root: str | Path | None = None,
        workspace_factory: BenchmarkWorkspaceFactory | None = None,
        trajectory_root: str | Path | None = None,
        validation_timeout_seconds: float = 60.0,
    ) -> None:
        if (executor is None) == (executor_factory is None):
            raise ValueError("provide exactly one of executor or executor_factory")
        self.executor = executor
        self.executor_factory = executor_factory
        self.protocol = protocol or load_benchmark_protocol(protocol_path)
        self.manifest_path = Path(manifest_path)
        self.workspace_root = workspace_root
        self.workspace_factory = workspace_factory
        self.trajectory_root = Path(trajectory_root) if trajectory_root else None
        self.validation_timeout_seconds = validation_timeout_seconds

    def run_suite(self, cases: list[BenchmarkCase] | None = None) -> BenchmarkSuiteResult:
        selected = cases if cases is not None else load_benchmark_cases(self.manifest_path)
        if self.protocol.task_order == "case_id":
            selected = sorted(selected, key=lambda case: case.case_id)
        runs: list[BenchmarkRunResult] = []
        for repeat_index in range(1, self.protocol.repeat_count + 1):
            for case in selected:
                result = self._run_one(repeat_index, case)
                runs.append(result.model_copy(update={"repeat_index": repeat_index}))
        return BenchmarkSuiteResult(
            protocol_id=self.protocol.protocol_id,
            protocol_version=self.protocol.version,
            repeat_count=self.protocol.repeat_count,
            runs=runs,
        )

    def _run_one(self, repeat_index: int, case: BenchmarkCase) -> BenchmarkRunResult:
        workspace_root = (
            self.workspace_factory(case, repeat_index)
            if self.workspace_factory is not None
            else self.workspace_root
        )
        if self.trajectory_root is not None:
            data_dir = self.trajectory_root / f"repeat-{repeat_index:02d}" / case.case_id
            recorder = DiagnosticRecorder(data_dir)
            return self._runner(recorder, workspace_root).run_case(case)
        with TemporaryDirectory(prefix=f"openpilot-benchmark-{repeat_index}-{case.case_id}-") as data_dir:
            recorder = DiagnosticRecorder(data_dir)
            return self._runner(recorder, workspace_root).run_case(case)

    def _runner(
        self,
        recorder: DiagnosticRecorder,
        workspace_root: str | Path | None,
    ) -> BenchmarkRunner:
        executor = (
            self.executor_factory(recorder)
            if self.executor_factory is not None
            else self.executor
        )
        if executor is None:
            raise RuntimeError("benchmark executor is not configured")
        return BenchmarkRunner(
            executor,
            manifest_path=self.manifest_path,
            workspace_root=workspace_root,
            recorder=recorder,
            validation_timeout_seconds=self.validation_timeout_seconds,
        )
