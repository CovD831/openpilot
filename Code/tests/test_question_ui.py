from __future__ import annotations

from rich.console import Console

from ui.question_ui import QuestionOption, QuestionUI


def _prompt_recorder(answers: list[str]):
    prompts: list[str] = []

    def read(prompt: str) -> str:
        prompts.append(prompt)
        return answers.pop(0)

    return prompts, read


def test_question_ui_integer_prompt_uses_plain_text() -> None:
    prompts, read = _prompt_recorder(["3"])
    ui = QuestionUI(Console(record=True), input_func=read, interactive=True)

    assert ui.ask_integer("iterations", "How many?", default=2) == 3
    assert prompts == ["Answer (integer, default 2): "]


def test_question_ui_choice_and_confirm_prompts_use_plain_text() -> None:
    prompts, read = _prompt_recorder(["1", "y"])
    ui = QuestionUI(Console(record=True), input_func=read, interactive=True)

    selected = ui.ask_select(
        "mode",
        "Choose mode",
        [QuestionOption("fast", "Fast"), QuestionOption("full", "Full")],
    )
    confirmed = ui.ask_confirm("continue", "Continue?")

    assert selected == "fast"
    assert confirmed is True
    assert prompts == ["Choose (1-2, default 1): ", "Confirm (Y/n): "]
