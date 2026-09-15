"""Convenient terminal entry point for the standalone coding agent."""

from __future__ import annotations

import argparse
import shlex
import sys
import tempfile
from pathlib import Path
from typing import Sequence

from evidence_core import EvidenceReader, EvidenceStore

from coding_agent import CodingAgent, CodingTask, OpenPilotWorkspaceAdapter


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="coding-agent",
        description="Run the evidence-first standalone coding agent.",
        epilog=(
            "Examples: coding-agent --demo; "
            "coding-agent --workspace . --file calculator.py "
            "--draft-file /tmp/calculator.py --validate 'python -m pytest -q'"
        ),
    )
    parser.add_argument("--demo", action="store_true", help="Run a safe temporary hello.py demo")
    parser.add_argument("--workspace", help="Workspace root; required unless --demo is used")
    parser.add_argument("--file", dest="target_path", help="Target path relative to workspace")
    change = parser.add_mutually_exclusive_group()
    change.add_argument("--draft", help="Replace the target file with this text")
    change.add_argument("--draft-file", type=Path, help="Read replacement text from this file")
    change.add_argument("--patch", help="Replace an inclusive line range with this text")
    change.add_argument("--patch-file", type=Path, help="Read patch text from this file")
    parser.add_argument("--line-start", type=int, help="First line for --patch")
    parser.add_argument("--line-end", type=int, help="Last line for --patch")
    parser.add_argument(
        "--validate",
        help="Validation command, parsed with shell-like quoting (for example 'python -m pytest -q')",
    )
    parser.add_argument("--task-id", default="terminal-coding-task", help="Stable task identifier")
    parser.add_argument("--max-turns", type=int, default=4, help="Maximum planning turns (default: 4)")
    parser.add_argument(
        "--evidence-dir",
        type=Path,
        help="Evidence directory (default: <workspace>/.openpilot/evidence_core)",
    )
    parser.add_argument("--show-events", action="store_true", help="Print the recorded event timeline")
    return parser


def _read_change(args: argparse.Namespace) -> tuple[str, str]:
    if args.draft is not None:
        return "draft", args.draft
    if args.draft_file is not None:
        return "draft", args.draft_file.read_text(encoding="utf-8")
    if args.patch is not None:
        return "patch", args.patch
    if args.patch_file is not None:
        return "patch", args.patch_file.read_text(encoding="utf-8")
    return "", ""


def _demo_task() -> tuple[Path, CodingTask]:
    root = Path(tempfile.mkdtemp(prefix="openpilot-coding-demo-"))
    workspace = root / "workspace"
    workspace.mkdir()
    target = workspace / "hello.py"
    target.write_text("print('old')\n", encoding="utf-8")
    validation = [
        sys.executable,
        "-c",
        f"from pathlib import Path; assert Path(r'{target}').read_text() == \"print('new')\\n\"",
    ]
    return workspace, CodingTask(
        task_id="terminal-demo",
        session_id="terminal-demo-session",
        goal="replace hello.py and verify it",
        workspace_root=str(workspace),
        target_path="hello.py",
        draft_text="print('new')\n",
        validation_command=validation,
        max_turns=4,
    )


def _build_task(args: argparse.Namespace) -> tuple[Path, CodingTask]:
    if args.demo:
        return _demo_task()
    if not args.workspace or not args.target_path:
        raise ValueError("--workspace and --file are required unless --demo is used")
    kind, content = _read_change(args)
    if not kind and not args.validate:
        raise ValueError("provide one of --draft/--draft-file/--patch/--patch-file or --validate")
    if kind == "patch" and (args.line_start is None or args.line_end is None):
        raise ValueError("--patch requires --line-start and --line-end")
    workspace = Path(args.workspace).expanduser().resolve()
    validation = shlex.split(args.validate) if args.validate else []
    return workspace, CodingTask(
        task_id=args.task_id,
        goal=f"terminal coding task for {args.target_path}",
        workspace_root=str(workspace),
        target_path=args.target_path,
        draft_text=content if kind == "draft" else "",
        patch_text=content if kind == "patch" else "",
        line_start=args.line_start,
        line_end=args.line_end,
        validation_command=validation,
        max_turns=args.max_turns,
    )


def run(args: argparse.Namespace) -> int:
    workspace, task = _build_task(args)
    evidence_dir = args.evidence_dir or workspace / ".openpilot" / "evidence_core"
    store = EvidenceStore(evidence_dir)
    result = CodingAgent(store=store).run(task, OpenPilotWorkspaceAdapter(workspace))
    reader = EvidenceReader(store)
    replay = reader.replay(result.run_id)
    summary = replay["summary"] if replay is not None else None
    print(f"status={result.status} success={result.success} turns={result.turns_used}")
    print(f"reason={result.reason}")
    print(f"run_id={result.run_id}")
    print(f"trajectory={result.trajectory_dir}")
    if summary is not None:
        print(f"events={summary.event_count} tools={summary.tool_called_count} verification={summary.verification_status}")
    if args.show_events:
        for event in replay["events"] if replay else []:
            print(f"{event.sequence:02d} {event.event_type:<28} {event.phase:<8} {event.summary}")
    return 0 if result.success else 1


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return run(args)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
