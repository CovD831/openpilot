"""Terminal UI for op0 — a read-only projection of runtime facts.

Every pixel here is derived from the trajectory, receipts, and the admission
registry. The UI owns no facts, makes no decisions, and must never gate or
alter a recorded permission outcome: if rendering fails, the run continues.
"""

from __future__ import annotations

import difflib
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
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
    "patch": "PATCH lines",
    "write": "WRITE file",
    "bash": "RUN command",
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


def markdown_response(text: str) -> None:
    console.print()
    console.print(Markdown(text or "*(no model response observed)*"))
    console.print()


def tool_status_line(tool: str, detail: str) -> str:
    """Plain status text used by the live spinner; derived from the tool call."""
    detail = detail.replace("\n", " ")[:80]
    return f"[dim]→ {tool}[/dim] {detail}"


def _diff_block(diff_text: str) -> Syntax:
    return Syntax(diff_text, "diff", theme="ansi_dark", word_wrap=True)


def proposal_panel(proposal) -> None:
    """Render one pending proposal with its change preview."""
    grant = proposal.grant
    label = _KIND_LABELS.get(grant.kind, grant.kind.upper())
    body_lines: list[str] = [f"[bold]{grant.goal}[/bold]"]
    if grant.command:
        body_lines.append(f"[cyan]$ {grant.command}[/cyan]")
    for path in grant.write_paths:
        body_lines.append(f"[cyan]{path}[/cyan]")
    body = "\n".join(body_lines)
    console.print(
        Panel(
            body,
            title=f"[yellow]{label} — approval required[/yellow]",
            subtitle=f"[dim]{proposal.proposal_id} · task {grant.task_id}[/dim]",
            border_style="yellow",
        )
    )
    if grant.diff_preview.strip():
        console.print(_diff_block(grant.diff_preview))
    console.print(
        f"  [dim]y = approve · n = deny · a = approve all pending · or /validate later[/dim]\n"
    )


def recovery_report(reconciled: list, status: str, actions: list[str]) -> None:
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


def render_turn_tools(events: list, *, verbose: bool = False) -> None:
    """Project one turn's tool calls claude-code style.

    Consecutive reads/searches collapse into one summary line; patch/write/
    bash stay visible; every result shows a one-line folded preview unless
    verbose. Derived entirely from trajectory events.
    """
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
    console.print()
