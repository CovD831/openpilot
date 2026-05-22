"""Reusable terminal question UI for OpenPilot startup and confirmations."""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from typing import Any, Callable, Literal

from rich.console import Console
from rich.panel import Panel
from rich.text import Text
from rich.box import ROUNDED
from utils.input_utils import read_text


QuestionKind = Literal["integer", "select", "confirm", "text"]


@dataclass(frozen=True)
class QuestionOption:
    """One selectable answer option."""

    value: Any
    label: str
    description: str = ""


@dataclass(frozen=True)
class QuestionSpec:
    """Declarative question definition used by QuestionUI."""

    id: str
    question: str
    kind: QuestionKind
    title: str = "OpenPilot Setup"
    description: str = ""
    default: Any = None
    options: list[QuestionOption] = field(default_factory=list)
    min_value: int | None = None
    max_value: int | None = None
    required: bool = False


@dataclass(frozen=True)
class QuestionResult:
    """Answer returned by QuestionUI."""

    question_id: str
    value: Any
    raw_input: str = ""
    used_default: bool = False


class QuestionUI:
    """Small, reusable Rich-based question interface.

    The class is intentionally independent of Live dashboards so startup prompts,
    confirmations, and future settings questions can reuse the same renderer.
    """

    def __init__(
        self,
        console: Console | None = None,
        *,
        input_func: Callable[[str], str] | None = None,
        interactive: bool | None = None,
    ) -> None:
        self.console = console or Console()
        self.input_func = input_func
        self.interactive = interactive

    def ask(self, spec: QuestionSpec) -> QuestionResult:
        """Ask a question and return a typed result."""
        if not self._is_interactive():
            self.console.print(
                f"[dim]Using default for {spec.id}: {self._format_default(spec.default)}[/dim]"
            )
            return QuestionResult(spec.id, spec.default, used_default=True)

        self._render_question(spec)
        if spec.kind == "integer":
            return self._ask_integer(spec)
        if spec.kind == "select":
            return self._ask_select(spec)
        if spec.kind == "confirm":
            return self._ask_confirm(spec)
        if spec.kind == "text":
            return self._ask_text(spec)
        raise ValueError(f"Unsupported question kind: {spec.kind}")

    def ask_integer(
        self,
        question_id: str,
        question: str,
        *,
        title: str = "OpenPilot Setup",
        description: str = "",
        default: int = 0,
        min_value: int | None = None,
        max_value: int | None = None,
    ) -> int:
        """Ask for an integer and return the selected value."""
        result = self.ask(
            QuestionSpec(
                id=question_id,
                question=question,
                kind="integer",
                title=title,
                description=description,
                default=default,
                min_value=min_value,
                max_value=max_value,
            )
        )
        return int(result.value)

    def ask_select(
        self,
        question_id: str,
        question: str,
        options: list[QuestionOption],
        *,
        title: str = "OpenPilot Setup",
        description: str = "",
        default_index: int = 0,
    ) -> Any:
        """Ask the user to choose one option."""
        default_index = max(0, min(default_index, len(options) - 1)) if options else 0
        default = options[default_index].value if options else None
        result = self.ask(
            QuestionSpec(
                id=question_id,
                question=question,
                kind="select",
                title=title,
                description=description,
                default=default,
                options=options,
            )
        )
        return result.value

    def ask_confirm(
        self,
        question_id: str,
        question: str,
        *,
        title: str = "OpenPilot Setup",
        description: str = "",
        default: bool = True,
    ) -> bool:
        """Ask a yes/no question."""
        result = self.ask(
            QuestionSpec(
                id=question_id,
                question=question,
                kind="confirm",
                title=title,
                description=description,
                default=default,
            )
        )
        return bool(result.value)

    def _ask_integer(self, spec: QuestionSpec) -> QuestionResult:
        while True:
            raw = self._read_input(self._prompt_suffix(spec))
            if not raw.strip() and spec.default is not None:
                return QuestionResult(spec.id, spec.default, raw, used_default=True)
            try:
                value = int(raw.strip())
            except ValueError:
                self.console.print("[red]Please enter a valid integer.[/red]")
                continue
            if spec.min_value is not None and value < spec.min_value:
                self.console.print(f"[red]Please enter a value >= {spec.min_value}.[/red]")
                continue
            if spec.max_value is not None and value > spec.max_value:
                self.console.print(f"[red]Please enter a value <= {spec.max_value}.[/red]")
                continue
            return QuestionResult(spec.id, value, raw)

    def _ask_select(self, spec: QuestionSpec) -> QuestionResult:
        if not spec.options:
            return QuestionResult(spec.id, spec.default, used_default=True)
        default_index = next(
            (index for index, option in enumerate(spec.options) if option.value == spec.default),
            0,
        )
        while True:
            raw = self._read_input(
                f"Choose (1-{len(spec.options)}, default {default_index + 1}): "
            )
            if not raw.strip():
                return QuestionResult(spec.id, spec.options[default_index].value, raw, used_default=True)
            try:
                index = int(raw.strip()) - 1
            except ValueError:
                self.console.print("[red]Please enter a valid option number.[/red]")
                continue
            if 0 <= index < len(spec.options):
                return QuestionResult(spec.id, spec.options[index].value, raw)
            self.console.print(f"[red]Please enter a number between 1 and {len(spec.options)}.[/red]")

    def _ask_confirm(self, spec: QuestionSpec) -> QuestionResult:
        default_label = "Y/n" if spec.default else "y/N"
        while True:
            raw = self._read_input(f"Confirm ({default_label}): ")
            normalized = raw.strip().lower()
            if not normalized:
                return QuestionResult(spec.id, bool(spec.default), raw, used_default=True)
            if normalized in {"y", "yes"}:
                return QuestionResult(spec.id, True, raw)
            if normalized in {"n", "no"}:
                return QuestionResult(spec.id, False, raw)
            self.console.print("[red]Please answer y or n.[/red]")

    def _ask_text(self, spec: QuestionSpec) -> QuestionResult:
        while True:
            raw = self._read_input(self._prompt_suffix(spec))
            if raw.strip() or not spec.required:
                if not raw.strip() and spec.default is not None:
                    return QuestionResult(spec.id, spec.default, raw, used_default=True)
                return QuestionResult(spec.id, raw.strip(), raw)
            self.console.print("[red]This answer is required.[/red]")

    def _render_question(self, spec: QuestionSpec) -> None:
        content = Text()
        content.append(spec.question, style="bold white")
        if spec.description:
            content.append(f"\n{spec.description}", style="dim white")
        if spec.default is not None:
            content.append(f"\nDefault: {self._format_default(spec.default)}", style="dim")

        self.console.print()
        self.console.print(
            Panel(content, title=f"[bold cyan]{spec.title}[/bold cyan]", border_style="cyan", box=ROUNDED)
        )
        if spec.kind == "select":
            for index, option in enumerate(spec.options, 1):
                marker = ">" if option.value == spec.default else " "
                line = f"  {marker} [{index}] {option.label}"
                if option.description:
                    line += f" - {option.description}"
                self.console.print(line, style="bold cyan" if option.value == spec.default else "white")
        self.console.print()

    def _prompt_suffix(self, spec: QuestionSpec) -> str:
        default = f", default {self._format_default(spec.default)}" if spec.default is not None else ""
        return f"Answer ({spec.kind}{default}): "

    def _read_input(self, prompt: str) -> str:
        if self.input_func is not None:
            return self.input_func(prompt)
        return read_text(prompt)

    def _is_interactive(self) -> bool:
        if self.interactive is not None:
            return self.interactive
        return bool(getattr(sys.stdin, "isatty", lambda: False)())

    @staticmethod
    def _format_default(value: Any) -> str:
        if isinstance(value, bool):
            return "yes" if value else "no"
        return str(value)
