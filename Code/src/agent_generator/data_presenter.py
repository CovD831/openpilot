"""Presentation helpers for Agent Generator data previews."""

from __future__ import annotations

import json
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from agent_generator.models import DataArtifact


def present_data(data: list[DataArtifact], console: Console | None = None) -> None:
    """Present a sketch and concrete bounded content for generated data."""
    console = console or Console()
    table = Table(title="Agent Generator Data Preview", show_header=True, header_style="bold cyan")
    table.add_column("Artifact", style="cyan", no_wrap=True)
    table.add_column("Kind", style="magenta", no_wrap=True)
    table.add_column("Source", style="green")
    table.add_column("Confidence", justify="right")
    table.add_column("Preview", style="white")

    for artifact in data:
        table.add_row(
            artifact.name,
            str(artifact.kind),
            _truncate(artifact.source, 70),
            f"{artifact.confidence:.2f}",
            artifact.preview,
        )

    console.print()
    console.print(table)
    for artifact in data:
        console.print(_artifact_panel(artifact))
    console.print()


def _artifact_panel(artifact: DataArtifact) -> Panel:
    content = artifact.content
    if isinstance(content, dict):
        mode = content.get("mode")
        if mode == "web":
            body = _render_web_content(content)
        elif mode == "file":
            body = _render_file_content(content)
        elif _is_processed_content(content):
            body = _render_processed_content(content)
        else:
            body = _render_generic_content(content)
    else:
        body = _truncate(str(content), 2400)
    return Panel(body or "[dim]No displayable content.[/dim]", title=f"[bold]{artifact.name}[/bold]", border_style="cyan")


def _render_web_content(content: dict[str, Any]) -> str:
    output = content.get("tool_output") if isinstance(content.get("tool_output"), dict) else {}
    lines = [
        f"[bold]Query:[/bold] {content.get('query') or output.get('query') or ''}",
        f"[bold]Provider:[/bold] {output.get('provider', 'unknown')}",
        f"[bold]Results:[/bold] {output.get('count', 0)}",
    ]

    summary = str(output.get("research_summary") or "").strip()
    if summary:
        lines.extend(["", "[bold]Research Summary[/bold]", _truncate(summary, 1200)])

    key_points = _string_list(output.get("key_points"))
    if key_points:
        lines.extend(["", "[bold]Key Points[/bold]"])
        lines.extend(f"- {_truncate(point, 260)}" for point in key_points[:8])

    source_notes = output.get("source_notes") or []
    if source_notes:
        lines.extend(["", "[bold]Source Notes[/bold]"])
        for note in source_notes[:5]:
            if isinstance(note, dict):
                label = note.get("source") or note.get("title") or note.get("url") or "source"
                text = note.get("note") or note.get("summary") or note.get("content") or ""
                lines.append(f"- {label}: {_truncate(str(text), 260)}")
            else:
                lines.append(f"- {_truncate(str(note), 260)}")

    results = output.get("results") or []
    if results:
        lines.extend(["", "[bold]Top URLs[/bold]"])
        for result in results[:5]:
            if not isinstance(result, dict):
                continue
            title = result.get("title") or result.get("url") or "result"
            url = result.get("url") or ""
            snippet = result.get("snippet") or ""
            lines.append(f"- {_truncate(str(title), 100)}")
            if url:
                lines.append(f"  {url}")
            if snippet:
                lines.append(f"  {_truncate(str(snippet), 220)}")

    pages = output.get("pages") or []
    fetched_pages = [page for page in pages if isinstance(page, dict) and page.get("content_excerpt")]
    if fetched_pages:
        lines.extend(["", "[bold]Fetched Page Excerpts[/bold]"])
        for page in fetched_pages[:2]:
            title = page.get("title") or page.get("url") or "page"
            lines.append(f"[dim]{_truncate(str(title), 120)}[/dim]")
            lines.append(_truncate(str(page.get("content_excerpt") or ""), 700))

    warnings = _string_list(output.get("warnings"))
    if warnings:
        lines.extend(["", "[bold yellow]Warnings[/bold yellow]"])
        lines.extend(f"- {_truncate(warning, 220)}" for warning in warnings[:5])

    return "\n".join(lines)


def _render_file_content(content: dict[str, Any]) -> str:
    output = content.get("tool_output") if isinstance(content.get("tool_output"), dict) else {}
    files = output.get("files") or content.get("files") or []
    if not files and output.get("file_path"):
        files = [output["file_path"]]
    file_content = str(output.get("content") or "")
    lines = [
        f"[bold]Files:[/bold] {len(files)}",
        f"[bold]Truncated:[/bold] {output.get('truncated', False)}",
    ]
    for file_path in files[:8]:
        lines.append(f"- {file_path}")
    if file_content:
        lines.extend(["", "[bold]Content Excerpt[/bold]", _truncate(file_content, 2400)])
    else:
        lines.extend(["", "[dim]No text content returned by file reader.[/dim]"])
    return "\n".join(lines)


def _render_processed_content(content: dict[str, Any]) -> str:
    lines = [
        f"[bold]Task:[/bold] {content.get('task', '')}",
        f"[bold]Processing Strategy:[/bold] {content.get('processing_strategy', '')}",
        f"[bold]Output Format:[/bold] {content.get('result_format') or content.get('output_format', '')}",
    ]
    result_text = str(content.get("result_text") or "").strip()
    if result_text:
        lines.extend(["", "[bold]Processed Result[/bold]", _truncate(result_text, 3600)])
    warnings = _string_list(content.get("warnings"))
    if warnings:
        lines.extend(["", "[bold yellow]Warnings[/bold yellow]"])
        lines.extend(f"- {_truncate(warning, 260)}" for warning in warnings[:4])
    artifacts = content.get("input_artifacts") or []
    if artifacts:
        lines.extend(["", "[bold]Input Data Used[/bold]"])
        for artifact in artifacts[:4]:
            if not isinstance(artifact, dict):
                continue
            lines.append(f"- {artifact.get('name', artifact.get('id', 'artifact'))}: {_truncate(str(artifact.get('preview', '')), 260)}")
            artifact_content = artifact.get("content")
            if isinstance(artifact_content, dict):
                mode = artifact_content.get("mode")
                if mode == "web":
                    output = artifact_content.get("tool_output") if isinstance(artifact_content.get("tool_output"), dict) else {}
                    summary = output.get("research_summary") or ""
                    if summary:
                        lines.append(f"  Summary: {_truncate(str(summary), 320)}")
                    key_points = _string_list(output.get("key_points"))
                    for point in key_points[:3]:
                        lines.append(f"  - {_truncate(point, 220)}")
                elif mode == "file":
                    output = artifact_content.get("tool_output") if isinstance(artifact_content.get("tool_output"), dict) else {}
                    excerpt = str(output.get("content") or "")
                    if excerpt:
                        lines.append(f"  Excerpt: {_truncate(excerpt, 420)}")
    return "\n".join(lines)


def _render_generic_content(content: dict[str, Any]) -> str:
    return _truncate(json.dumps(content, ensure_ascii=False, indent=2, default=str), 2400)


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if item is not None and str(item).strip()]


def _is_processed_content(content: dict[str, Any]) -> bool:
    return "processing_strategy" in content and "input_artifacts" in content


def _truncate(value: str, limit: int) -> str:
    cleaned = " ".join(str(value).split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: max(0, limit - 3)] + "..."
