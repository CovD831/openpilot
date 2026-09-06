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
