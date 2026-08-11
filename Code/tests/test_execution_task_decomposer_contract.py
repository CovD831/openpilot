from __future__ import annotations

from types import SimpleNamespace

import pytest

from autonomous_iteration.agents.execution_task_decomposer import TaskDecomposer
from autonomous_iteration.task_models import Task
from core.exceptions import InvalidLLMResponseError


def _decomposer_for(payload: object) -> TaskDecomposer:
    decomposer = TaskDecomposer(SimpleNamespace())
    decomposer._generate_decomposition = lambda _task, _context: payload  # type: ignore[method-assign]
    return decomposer


@pytest.mark.parametrize("raw_kind", ["general", None])
def test_decomposition_accepts_general_and_missing_kind(raw_kind: str | None) -> None:
    result = _decomposer_for(
        {
            "rationale": "one bounded task",
            "subtasks": [{"description": "Answer the user", "kind": raw_kind}],
        }
    ).decompose("Answer the user")

    assert len(result.subtasks) == 1
    assert result.subtasks[0].kind == "general"


@pytest.mark.parametrize(
    "payload",
    [
        {"subtasks": [{"description": "Answer the user", "kind": "unsupported"}]},
        {"subtasks": ["not an object"]},
        {"subtasks": [{"kind": "general"}]},
        {"subtasks": "not a list"},
        {"subtasks": []},
        {
            "subtasks": [
                {"description": f"Task {index}", "kind": "general"}
                for index in range(8)
            ]
        },
        [],
    ],
)
def test_malformed_decomposition_is_bounded_for_runtime_conversion(payload: object) -> None:
    with pytest.raises(ValueError) as error_info:
        _decomposer_for(payload).decompose("Answer the user")

    error = error_info.value
    assert len(str(error)) < 200


def test_simple_code_malformed_subtask_is_bounded_before_compaction() -> None:
    with pytest.raises(ValueError, match="JSON object"):
        _decomposer_for({"subtasks": ["not an object"]}).decompose(
            "Build a script at /tmp/example.py"
        )


def test_prompt_task_kinds_and_validator_share_one_contract() -> None:
    prompt_kinds = TaskDecomposer.task_kind_prompt_values()

    assert "general" in prompt_kinds
    for kind in prompt_kinds:
        normalized = TaskDecomposer._normalize_subtask_contract(
            {"description": "bounded work", "kind": kind}
        )
        assert normalized["kind"] == kind


def test_decomposition_accepts_exact_seven_subtasks() -> None:
    result = _decomposer_for(
        {
            "subtasks": [
                {"description": f"Task {index}", "kind": "general"}
                for index in range(7)
            ]
        }
    ).decompose("Run bounded work")

    assert len(result.subtasks) == 7


def test_interactive_python_direct_run_is_normalized_to_bounded_compile() -> None:
    result = _decomposer_for(
        {
            "subtasks": [
                {
                    "description": "实现贪吃蛇小游戏。",
                    "kind": "implement",
                    "write_files": ["snake_game.py"],
                },
                {
                    "description": "运行游戏并确认能够启动。",
                    "kind": "validate",
                    "read_files": ["snake_game.py"],
                    "validation_command": "python snake_game.py",
                    "dependencies": [0],
                },
            ]
        }
    ).decompose("帮我做一个贪吃蛇小游戏")

    assert result.subtasks[1].validation_command == "python -m py_compile snake_game.py"


def test_interactive_python_direct_run_requires_a_grounded_target() -> None:
    decomposer = _decomposer_for(
        {
            "subtasks": [
                {
                    "description": "运行游戏并确认能够启动。",
                    "kind": "validate",
                    "read_files": ["other.py"],
                    "validation_command": "python snake_game.py",
                }
            ]
        }
    )

    with pytest.raises(ValueError, match="grounded Python target"):
        decomposer.decompose("帮我做一个贪吃蛇小游戏")


@pytest.mark.parametrize(
    ("task_description", "validation_command"),
    [
        ("Create a terminating report script", "python report.py"),
        ("Create an observer report script", "python observer.py"),
        ("Fix calculator.py", "python -m pytest -q"),
        ("Build an interactive game", "python -m py_compile game.py"),
    ],
)
def test_bounded_or_noninteractive_validation_commands_remain_unchanged(
    task_description: str,
    validation_command: str,
) -> None:
    if "game" in task_description:
        target = "game.py"
    elif "observer" in task_description:
        target = "observer.py"
    else:
        target = "report.py"
    result = _decomposer_for(
        {
            "subtasks": [
                {
                    "description": "Validate the implementation.",
                    "kind": "validate",
                    "read_files": [target],
                    "validation_command": validation_command,
                }
            ]
        }
    ).decompose(task_description)

    assert result.subtasks[0].validation_command == validation_command


def test_invalid_decomposition_receives_one_bounded_repair() -> None:
    decomposer = TaskDecomposer(SimpleNamespace())
    payloads = iter(
        [
            {"subtasks": [{"description": "Answer", "kind": "unsupported"}]},
            {"subtasks": [{"description": "Answer", "kind": "general"}]},
        ]
    )
    calls: list[object | None] = []

    def request(_task, _context, *, repair_payload=None):
        calls.append(repair_payload)
        return next(payloads)

    decomposer._request_decomposition = request  # type: ignore[method-assign]

    result = decomposer._generate_decomposition(Task(id="task-1", description="Answer"), {})

    assert result["subtasks"][0]["kind"] == "general"
    assert calls == [None, {"subtasks": [{"description": "Answer", "kind": "unsupported"}]}]


def test_invalid_repair_stops_after_exactly_two_provider_steps() -> None:
    decomposer = TaskDecomposer(SimpleNamespace())
    calls = 0

    def request(_task, _context, *, repair_payload=None):
        nonlocal calls
        calls += 1
        return {"subtasks": [{"description": "Answer", "kind": "unsupported"}]}

    decomposer._request_decomposition = request  # type: ignore[method-assign]

    with pytest.raises(InvalidLLMResponseError, match="after one repair") as error_info:
        decomposer._generate_decomposition(Task(id="task-1", description="Answer"), {})

    assert calls == 2
    assert error_info.value.response_text == ""


def test_invalid_json_response_receives_the_same_single_repair_step() -> None:
    decomposer = TaskDecomposer(SimpleNamespace())
    calls: list[object | None] = []

    def request(_task, _context, *, repair_payload=None):
        calls.append(repair_payload)
        if repair_payload is None:
            raise InvalidLLMResponseError("invalid JSON", response_text="not-json")
        return {"subtasks": [{"description": "Answer", "kind": "general"}]}

    decomposer._request_decomposition = request  # type: ignore[method-assign]

    result = decomposer._generate_decomposition(Task(id="task-1", description="Answer"), {})

    assert result["subtasks"][0]["kind"] == "general"
    assert calls == [None, "not-json"]


def test_repair_payload_is_bounded_and_credential_redacted() -> None:
    payload = TaskDecomposer._bounded_repair_payload(
        {
            "api_key": "sk-test-secret",
            "subtasks": [{"description": "x" * 2000, "kind": "general"}],
        }
    )

    assert isinstance(payload, dict)
    assert payload["api_key"] == "[REDACTED]"
    assert "sk-test-secret" not in str(payload)
    assert len(payload["subtasks"][0]["description"]) == 1000
