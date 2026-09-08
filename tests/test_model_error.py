"""Model-error surfacing: error stopReason extraction, session lookup,
and the UI markup that must distinguish a failed call from a silent one."""

from __future__ import annotations

import re
from pathlib import Path

from op0.response import error_message_from_payload
from op0.session import Session
from op0.ui import model_error_markup


def _error_payload(message: str = "Connection error.") -> dict:
    return {
        "message": {
            "role": "assistant",
            "content": [],
            "stopReason": "error",
            "errorMessage": message,
        }
    }


def test_error_message_from_payload() -> None:
    assert error_message_from_payload(_error_payload()) == "Connection error."
    assert error_message_from_payload({"message": {"role": "assistant", "content": [], "stopReason": "stop", "errorMessage": "x"}}) == ""
    assert error_message_from_payload({"message": {"role": "user", "stopReason": "error", "errorMessage": "x"}}) == ""
    assert error_message_from_payload({"message": {"role": "assistant", "stopReason": "error"}}) == ""
    assert error_message_from_payload("not a dict") == ""


def test_session_last_model_error(tmp_path: Path) -> None:
    session = Session(tmp_path)
    session.record("model_response", {"message": {"role": "user", "stopReason": "stop"}})
    session.record("model_response", _error_payload("Connection error."))
    # the most recent error wins; callers only consult this on an empty response
    assert session.last_model_response() == ""
    assert session.last_model_error() == "Connection error."

    recovered = Session(tmp_path)
    recovered.record("model_response", _error_payload("Connection error."))
    recovered.record("model_response", {"message": {"role": "assistant", "content": [{"type": "text", "text": "hello"}], "stopReason": "stop"}})
    # a later success makes the response non-empty, so the guard never reads the stale error
    assert recovered.last_model_response() == "hello"
    assert recovered.last_model_error() == "Connection error."


def test_model_error_markup_escapes_and_defaults() -> None:
    rendered = model_error_markup("Connection error.")
    assert "Connection error." in rendered
    assert "[red]" in rendered
    # bracket-bearing error text must not be interpreted as rich markup
    escaped = model_error_markup("bad [constructor] token")
    assert "\\[constructor]" in escaped
    assert "model call failed without an error message" in model_error_markup("")


def test_dynamic_text_with_brackets_never_crashes_render(tmp_path: Path) -> None:
    """Regression: user input / model output containing rich-looking brackets
    (e.g. '[/bold]') crashed the TUI dispatch thread with MarkupError."""
    from op0.ui import markdown_response, render_markdown_to_str, render_proposal_to_str

    from op0.admission import AdmissionRegistry

    # model prose with markup-looking brackets renders literally
    rendered = render_markdown_to_str("answer with [/bold] and [red] raw brackets")
    clean = re.sub(r"\x1b\[[0-9;?]*[a-zA-Z]", "", rendered)
    assert "[/bold]" in clean and "[red]" in clean

    # proposal command with brackets renders without raising
    registry = AdmissionRegistry(str(tmp_path))
    registry.propose_command('goal [/bold] tag', 'grep "[pattern]" src')
    card = re.sub(r"\x1b\[[0-9;?]*[a-zA-Z]", "", render_proposal_to_str(registry.pending()[0]))
    assert 'grep "[pattern]" src' in card

    # and markdown_response itself survives the same input
    markdown_response("prose with [/bold] inside")


def test_user_line_survives_bracket_input() -> None:
    """The exact crash from the field: typed '[...]' hit the user-line markup.
    Escape + universal close tag must render it literally."""
    from op0.tui import _rich_to_ansi

    from rich.markup import escape

    line = _rich_to_ansi(f"[bold on #262626] ❯ {escape('text [/bold] more')} [/]")
    clean = re.sub(r"\x1b\[[0-9;?]*[a-zA-Z]", "", line)
    assert "text [/bold] more" in clean
