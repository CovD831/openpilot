"""op0 CLI: claude-code-style REPL over the Pi execution base (L0, read-only)."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from op0.bridge import ReadOnlyToolBridge
from op0.contracts import TaskSpec
from op0.engine import Engine, EngineConfig
from op0.session import Session

_PROMPT_TEMPLATE = (
    "Answer the user's task. If inspecting project files is needed, use the "
    "openpilot_read tool with a project-relative path; it only serves paths "
    "inside the project. Shell commands, network access, and file writes are "
    "not available.\n\nUser task:\n{goal}"
)


def run_once_task(spec: TaskSpec) -> str:
    """Run one task end to end and return the sanitized model response."""
    session = Session(spec.resolved_root())
    session.record("task_received", {"goal": spec.goal, "project_root": spec.project_root})
    bridge: ReadOnlyToolBridge | None = None
    if _engine_enables_read_tool():
        bridge = ReadOnlyToolBridge(
            (spec.project_root,),
            on_request=lambda payload: session.record(
                "tool_call", payload, producer="bridge", call_id=str(payload.get("toolCallId") or "")
            ),
            on_result=lambda payload: session.record(
                "tool_result", payload, producer="bridge", call_id=str(payload.get("toolCallId") or "")
            ),
        )
        bridge.start()
    engine = Engine(session, _engine_config(spec))
    response = engine.run_once(spec, bridge=bridge)
    session.record(
        "run_finished",
        {"state": engine.state.value, "response_chars": len(response)},
    )
    return response


def _engine_enables_read_tool() -> bool:
    return True


def _engine_config(spec: TaskSpec) -> EngineConfig:
    return EngineConfig(
        provider=str(os.environ.get("OP0_PI_PROVIDER") or ""),
        model=str(os.environ.get("OP0_PI_MODEL") or ""),
        cwd=spec.project_root,
        timeout_seconds=spec.timeout_seconds,
        enable_read_tool=True,
    )


def _print_response(text: str) -> None:
    print()
    print(text if text else "(no model response observed)")
    print()


def _run_repl(project_root: Path) -> int:
    from prompt_toolkit import PromptSession
    from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
    from prompt_toolkit.history import InMemoryHistory

    session: PromptSession[str] = PromptSession(
        history=InMemoryHistory(),
        auto_suggest=AutoSuggestFromHistory(),
    )
    print("op0 L0 - Pi execution base (read-only). Type a task, /help, or /exit.")
    while True:
        try:
            line = session.prompt("op0> ")
        except KeyboardInterrupt:
            print("\n(interrupted) type /exit to quit")
            continue
        except EOFError:
            print()
            return 0
        text = line.strip()
        if not text:
            continue
        if text in {"/exit", "/quit", "exit", "quit", ":q"}:
            return 0
        if text == "/help":
            print("Type a task and op0 runs it through Pi (read-only). /clear /exit")
            continue
        if text == "/clear":
            print("\033[2J\033[H", end="")
            continue
        response = run_once_task(TaskSpec(goal=text, project_root=str(project_root)))
        _print_response(response)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="op0", description="op0 L0 execution base")
    parser.add_argument("--once", help="run one goal and exit")
    parser.add_argument("--project-path", default=".", help="project root for this task")
    args = parser.parse_args(argv)
    project_root = Path(args.project_path).expanduser().resolve(strict=False)

    if args.once:
        response = run_once_task(TaskSpec(goal=args.once, project_root=str(project_root)))
        _print_response(response)
        return 0 if response else 1
    return _run_repl(project_root)


if __name__ == "__main__":
    sys.exit(main())
