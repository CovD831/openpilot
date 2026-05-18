"""Unicode-safe terminal input helpers."""

from __future__ import annotations

import sys
from typing import Callable


InputFunc = Callable[[str], str]


def read_text(
    prompt: str,
    *,
    default: str | None = None,
    required: bool = False,
    input_func: InputFunc | None = None,
) -> str:
    """Read text with prompt-toolkit when available for proper CJK editing."""
    while True:
        raw = _read_once(prompt, input_func=input_func)
        if raw.strip():
            return raw.strip()
        if default is not None:
            return default
        if not required:
            return ""
        print("This answer is required.")


def read_confirm(
    prompt: str,
    *,
    default: bool = True,
    input_func: InputFunc | None = None,
) -> bool:
    """Read a yes/no answer with an explicit default."""
    suffix = "[Y/n]" if default else "[y/N]"
    while True:
        raw = read_text(f"{prompt} {suffix} ", input_func=input_func)
        normalized = raw.strip().lower()
        if not normalized:
            return default
        if normalized in {"y", "yes"}:
            return True
        if normalized in {"n", "no"}:
            return False
        print("Please answer y or n.")


def _read_once(prompt: str, *, input_func: InputFunc | None) -> str:
    if input_func is not None:
        return input_func(prompt)
    if not getattr(sys.stdin, "isatty", lambda: False)():
        return input(prompt)
    try:
        from prompt_toolkit import PromptSession
        from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
        from prompt_toolkit.history import InMemoryHistory

        session = PromptSession(
            history=InMemoryHistory(),
            auto_suggest=AutoSuggestFromHistory(),
            enable_history_search=True,
            complete_while_typing=False,
            vi_mode=False,
        )
        return session.prompt(prompt)
    except ImportError:
        return input(prompt)
