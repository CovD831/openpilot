"""Terminal UI for op0 — a read-only projection of runtime facts.

Every pixel here is derived from the trajectory, receipts, and the admission
registry. The UI owns no facts, makes no decisions, and must never gate or
alter a recorded permission outcome: if rendering fails, the run continues.
"""

from __future__ import annotations

import difflib
import io
import re
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.markdown import Markdown
from rich.markup import escape
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text

console = Console()

_CLOSURE_STYLES = {
    "success": ("bold green", "✔"),
    "indeterminate": ("bold yellow", "…"),
    "failed": ("bold red", "✘"),
    "blocked": ("dim", "·"),
    "closed": ("bold green", "✔"),
    "clean": ("bold green", "✔"),
}

_KIND_LABELS = {
    "patch": "Edit file",
    "write": "Write file",
    "bash": "Bash command",
}


def banner(project_root: str, version: str, pending_recovery: int) -> None:
    root = Text(project_root, style="cyan")
    head = Text.assemble(
        ("◆ op0 ", "bold magenta"),
        (f"v{version}", "dim"),
        ("  —  governed coding agent\n", "dim"),
        ("  project: ", "dim"),
        root,
    )
    console.print(head)
    if pending_recovery:
        console.print(
            f"  [yellow]{pending_recovery} unvalidated receipt(s) from previous runs — see recovery report[/yellow]"
        )
    console.print("  [dim]type a task · /help for commands[/dim]\n")


def closure_line(status: str, reason: str) -> None:
    style, mark = _CLOSURE_STYLES.get(status, ("dim", "·"))
    console.print(f"  [{style}]{mark} closure: {status}[/{style}] [dim]— {reason}[/dim]")


def console_default():
    return console


def markdown_response(text: str) -> None:
    """Render the response with always-visible colors: prose as plain text
    (terminal default color), fenced code highlighted. rich Markdown's theme
    colors were nearly invisible on dark terminals."""
    if not (text or "").strip():
        console.print("[dim](no model response observed)[/dim]")
        return
    console.print()  # one separator line between the tool transcript and the answer
    parts = re.split(r"```(\w*)\n?(.*?)```", text, flags=re.S)
    for i, part in enumerate(parts):
        if i % 3 == 1:
            continue  # language tag
        if i % 3 == 2:
            console.print(Syntax(part, parts[i - 1] or "text", theme="ansi_dark", word_wrap=True))
        elif part.strip():
            # model prose is data, not markup: print literally so brackets in
            # the answer can neither crash nor be eaten as rich tags
            console.print(_plain_md(part.strip()), markup=False, highlight=False)
    console.print()


def model_error_markup(error: str) -> str:
    """A failed model call must read differently from a silent empty response."""
    message = escape((error or "").strip() or "model call failed without an error message")
    return f"[red]model error:[/red] {message} [dim]— no model response; closure stays evidence-based[/dim]"


def _plain_md(md: str) -> str:
    """Strip markdown decoration so plain text stays readable everywhere."""
    md = re.sub(r"^#{1,6}\s*", "", md, flags=re.M)
    md = md.replace("**", "").replace("__", "")
    md = re.sub(r"`([^`]*)`", r"\1", md)
    return md


def tool_status_line(tool: str, detail: str) -> str:
    """Plain status text used by the live spinner; derived from the tool call."""
    detail = detail.replace("\n", " ")[:80]
    return f"[dim]→ {tool}[/dim] {detail}"


def recovery_report(reconciled: list, status: str, actions: list[str], console=None) -> None:
    console = console or console_default()
    table = Table(title="recovery — durable receipts vs disk", border_style="yellow")
    table.add_column("receipt", style="dim")
    table.add_column("path")
    table.add_column("disk", style="cyan")
    table.add_column("validation")
    for item in reconciled:
        validation_style = "green" if item.receipt.validation_status == "passed" else "yellow"
        table.add_row(
            item.receipt.receipt_id,
            Path(item.receipt.path).name,
            item.disk_state,
            f"[{validation_style}]{item.receipt.validation_status}[/{validation_style}]",
        )
    console.print(table)
    for action in actions:
        console.print(f"  [yellow]→ {action}[/yellow]")
    console.print()


def make_diff_preview(kind: str, args: dict[str, Any], project_root: str) -> str:
    """Projection helper: what would this change look like? Read-only."""
    if kind == "bash":
        return f"--- run in {project_root}\n+++ command\n$ {args.get('command', '')}"
    raw_path = str(args.get("path") or "")
    if not raw_path:
        return ""
    path = Path(raw_path).expanduser()
    if not path.is_absolute():
        path = Path(project_root) / path
    path = path.resolve(strict=False)
    old_text = path.read_text(encoding="utf-8", errors="replace") if path.is_file() else ""
    if kind == "write":
        new_text = str(args.get("content") or "")
    else:
        from op0.bridge import patched_text

        try:
            new_text = patched_text(
                old_text, int(args.get("lineStart") or 0), int(args.get("lineEnd") or 0),
                str(args.get("replacementText") or ""),
            )
        except (ValueError, IndexError):
            return "(invalid line range)"
    fromfile = path.name + (" (new)" if not old_text else " (current)")
    diff = "\n".join(
        difflib.unified_diff(
            old_text.splitlines(), new_text.splitlines(),
            fromfile=fromfile, tofile=path.name + " (after)", lineterm="",
        )
    )
    return diff[:4000]


# -- turn transcript (claude-code style folding) -----------------------------

_COLLAPSIBLE = {"openpilot_read", "openpilot_search"}


def _short_args(tool: str, args: dict[str, Any]) -> str:
    if tool == "openpilot_bash":
        return str(args.get("command") or "")[:80]
    path = str(args.get("path") or "")
    name = Path(path).name or path
    if tool == "openpilot_read":
        return name
    if tool == "openpilot_search":
        return f"{args.get('pattern', '')!r} in {name or 'project'}"
    if tool == "openpilot_patch":
        return f"{name} L{args.get('lineStart')}–{args.get('lineEnd')}"
    if tool == "openpilot_write":
        return f"{name} ({len(str(args.get('content') or ''))} chars)"
    return name


def render_turn_tools(events: list, *, verbose: bool = False, console=None) -> None:
    """Project one turn's tool calls claude-code style.

    Consecutive reads/searches collapse into one summary line; patch/write/
    bash stay visible; every result shows a one-line folded preview unless
    verbose. Derived entirely from trajectory events.
    """
    console = console or console_default()
    calls: list[tuple[str, dict, str, str]] = []  # tool, args, call_id, preview
    results: dict[str, dict] = {}
    for event in events:
        if event.event_type == "tool_call" and event.producer == "bridge":
            payload = event.payload or {}
            calls.append(
                (
                    str(payload.get("toolName") or ""),
                    dict(payload.get("args") or {}),
                    str(payload.get("toolCallId") or ""),
                    "",
                )
            )
        elif event.event_type == "tool_result" and event.producer == "bridge":
            payload = event.payload or {}
            results[str(payload.get("toolCallId") or "")] = payload

    groups: list[tuple[str, list[int]]] = []
    for index, (tool, _args, _cid, _preview) in enumerate(calls):
        collapsible = tool in _COLLAPSIBLE
        if groups and collapsible and groups[-1][0] == "read-search":
            groups[-1][1].append(index)
        elif collapsible:
            groups.append(("read-search", [index]))
        else:
            groups.append((tool, [index]))

    for group_kind, indices in groups:
        if group_kind == "read-search" and len(indices) > 1 and not verbose:
            reads = sum(1 for i in indices if calls[i][0] == "openpilot_read")
            searches = len(indices) - reads
            parts = []
            if reads:
                parts.append(f"Read×{reads}")
            if searches:
                parts.append(f"Search×{searches}")
            console.print(f"  [dim]⏺ {' + '.join(parts)} (collapsed)[/dim]")
            continue
        for i in indices:
            tool, args, call_id, _ = calls[i]
            short = tool.replace("openpilot_", "").title()
            ok = results.get(call_id, {}).get("success")
            mark_style = "green" if ok is not False else "red"
            console.print(
                f"  [{mark_style}]⏺[/{mark_style}] [bold]{short}[/bold][dim]({_short_args(tool, args)})[/dim]"
            )
            preview = str(results.get(call_id, {}).get("preview") or "")
            if preview:
                first_line = preview.splitlines()[0][:100]
                more = len(preview.splitlines()) - 1
                suffix = f" [dim](+{more} lines)[/dim]" if more > 0 and not verbose else ""
                console.print(f"    [dim]⎿ {first_line}{suffix}[/dim]")
                if verbose and more > 0:
                    for extra in preview.splitlines()[1:6]:
                        console.print(f"      [dim]{extra[:110]}[/dim]")


def render_markdown_to_str(text: str) -> str:
    """Render the response markdown to an ANSI string for the transcript."""
    global console
    import io

    width = console.width
    previous = console
    capture = Console(file=io.StringIO(), force_terminal=True, width=width)
    console = capture
    try:
        markdown_response(text)
    finally:
        console = previous
    return capture.file.getvalue()


def render_closure_to_str(status: str, reason: str) -> str:
    global console
    import io

    width = console.width
    previous = console
    capture = Console(file=io.StringIO(), force_terminal=True, width=width)
    console = capture
    try:
        closure_line(status, reason)
    finally:
        console = previous
    return capture.file.getvalue()


def render_settled_line(proposal, answered: str) -> str:
    """One-line outcome that stays in the transcript after the live card
    closes (claude-code settles the dialog into the tool-use line)."""
    grant = proposal.grant
    action = grant.command or (", ".join(grant.write_paths) if grant.write_paths else grant.goal)
    if answered in ("y", "a"):
        return f"[green]✓[/green] approved · {escape(action)}"
    return f"[red]✗ denied[/red] · {escape(action)}"


def render_proposal_to_str(proposal, *, verbose: bool = False, selected: int | None = None,
                           answered: str = "") -> str:
    """Live approval card, claude-code shape — reconstructed from the
    decompiled PermissionDialog/PermissionPrompt/ListItem source
    (777genius/claude-code-source-code-full):

    - a top-only rounded border (no side/bottom borders, they misalign)
    - bold tool title, dim command, dim question
    - pointer options WITHOUT numbers (❯ = focused, blank = not)
    - dim footer, no closing rule

    selected: which option carries the ❯ (live selection). answered: settled
    mode — options collapse into the chosen outcome. Returns RENDERED ANSI
    (the TUI card window and /proposals print it as-is)."""
    from rich.console import Console as RichConsole

    grant = proposal.grant
    label = _KIND_LABELS.get(grant.kind, grant.kind.upper())
    width = console.width
    rule = "╭" + "─" * max(18, width - 2) + "╮"

    def opt_row(index: int, text: str) -> str:
        pointer = "[bold cyan]❯[/bold cyan]" if selected == index else " "
        return f"{pointer} {text}"

    if answered:
        verdict = {"y": "[green]✓ Yes — approved[/green]",
                   "a": "[green]✓ Yes to all — approved[/green]",
                   "n": "[red]✗ No — denied, tell the model what to do differently[/red]"}.get(answered, answered)
        options_block = f"   {verdict}"
    else:
        options_block = "\n".join([
            "   [dim]Do you want to proceed?[/dim]",
            "   " + opt_row(0, "[bold]Yes[/bold]"),
            "   " + opt_row(1, "Yes to all — approve every pending proposal"),
            "   " + opt_row(2, "No — tell the model what to do differently [dim](esc)[/dim]"),
            "   [dim]Esc to cancel · y/a/n (or 1/2/3)[/dim]",
        ])
    body: list[str] = []
    if grant.command:
        body.append(f"[dim]   $ {escape(grant.command)}[/dim]")
    for path in grant.write_paths:
        body.append(f"[dim]   {escape(path)}[/dim]")
    if grant.diff_preview.strip():
        lines = grant.diff_preview.splitlines()
        added = sum(1 for line in lines if line.startswith("+") and not line.startswith("+++"))
        removed = sum(1 for line in lines if line.startswith("-") and not line.startswith("---"))
        body.append(f"[dim]   changes: +{added} −{removed} lines ('/verbose' to expand)[/dim]")
    body_text = ("\n".join(body) + "\n") if body else ""
    markup = (
        f"[dim]{rule}[/dim]\n"
        f"[bold]{label}[/bold][dim] · {proposal.proposal_id}[/dim]\n"
        f"{body_text}"
        f"{options_block}\n"
    )
    capture = RichConsole(
        file=io.StringIO(), force_terminal=True, color_system="truecolor", width=width
    )
    capture.print(markup, highlight=False)
    return capture.file.getvalue().rstrip("\n")
