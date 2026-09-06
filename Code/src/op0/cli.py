"""op0 CLI: claude-code-style REPL over the Pi execution base.

L1: patches are demand-driven admitted. When the model asks for a patch, the
bridge creates a typed proposal; until /approve binds a consent to this run,
every patch request is refused at the bridge. Reads stay scope-checked.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from op0.admission import AdmissionRegistry, Proposal
from op0.bridge import ReadOnlyToolBridge
from op0.contracts import TaskSpec
from op0.engine import Engine, EngineConfig
from op0.session import Session


def run_once_task(spec: TaskSpec) -> str:
    """Single-shot path (--once): read-only only; patches would need the REPL flow."""
    session = Session(spec.resolved_root())
    session.record("task_received", {"goal": spec.goal, "project_root": spec.project_root})
    registry = AdmissionRegistry(spec.project_root)
    bridge = _make_bridge(session, registry, spec.project_root, current_goal=spec.goal)
    bridge.start()
    engine = Engine(session, _engine_config(spec))
    try:
        return engine.run_once(spec, bridge=bridge)
    finally:
        if bridge is not None:
            bridge.stop()


def _make_bridge(
    session: Session,
    registry: AdmissionRegistry,
    project_root: str,
    *,
    current_goal: str,
) -> ReadOnlyToolBridge:
    def authorize(raw_path: str):
        canonical = str(Path(raw_path).expanduser().resolve(strict=False))
        try:
            consent = registry.authorize_patch(canonical, session.run_id)
            session.record(
                "patch_authorized",
                {"path": canonical, "consent_id": consent.consent_id},
                producer="admission",
            )
            return consent
        except PermissionError:
            proposal = registry.propose(current_goal, raw_path, (project_root,))
            session.record(
                "patch_proposed",
                {
                    "proposal_id": proposal.proposal_id,
                    "path": canonical,
                    "write_paths": list(proposal.grant.write_paths),
                },
                producer="admission",
            )
            raise

    return ReadOnlyToolBridge(
        (project_root,),
        patch_authorizer=authorize,
        on_request=lambda payload: session.record(
            "tool_call", payload, producer="bridge", call_id=str(payload.get("toolCallId") or "")
        ),
        on_result=lambda payload: session.record(
            "tool_result", payload, producer="bridge", call_id=str(payload.get("toolCallId") or "")
        ),
    )


def _proposal_json(proposal: Proposal) -> str:
    return json.dumps(
        {
            "proposal_id": proposal.proposal_id,
            "task_id": proposal.grant.task_id,
            "goal": proposal.grant.goal,
            "write_paths": list(proposal.grant.write_paths),
            "read_roots": list(proposal.grant.read_roots),
            "status": proposal.status,
        },
        ensure_ascii=False,
        indent=2,
    )


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


def _print_pending(registry: AdmissionRegistry) -> None:
    pending = registry.pending()
    for proposal in pending:
        print(f"— patch proposal (needs approval):")
        print(_proposal_json(proposal))
    if pending:
        print(f"Approve with /approve {pending[0].proposal_id} then retry the task; /deny to refuse.\n")


def _run_repl(project_root: Path) -> int:
    from prompt_toolkit import PromptSession
    from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
    from prompt_toolkit.history import InMemoryHistory

    session: PromptSession[str] = PromptSession(
        history=InMemoryHistory(),
        auto_suggest=AutoSuggestFromHistory(),
    )
    print("op0 L1 - read free, writes admitted (/approve). Type a task, /help, or /exit.")

    traj = Session(project_root)
    traj.record("session_started", {"project_root": str(project_root)})
    registry = AdmissionRegistry(str(project_root))
    engine = Engine(traj, _engine_config(TaskSpec(goal="", project_root=str(project_root))))

    state = {"goal": ""}

    def authorize(raw_path: str):
        canonical = str(Path(raw_path).expanduser().resolve(strict=False))
        try:
            consent = registry.authorize_patch(canonical, traj.run_id)
            traj.record(
                "patch_authorized",
                {"path": canonical, "consent_id": consent.consent_id},
                producer="admission",
            )
            return consent
        except PermissionError:
            proposal = registry.propose(state["goal"], raw_path, (str(project_root),))
            traj.record(
                "patch_proposed",
                {
                    "proposal_id": proposal.proposal_id,
                    "path": canonical,
                    "write_paths": list(proposal.grant.write_paths),
                },
                producer="admission",
            )
            raise

    bridge = ReadOnlyToolBridge(
        (str(project_root),),
        patch_authorizer=authorize,
        on_request=lambda payload: traj.record(
            "tool_call", payload, producer="bridge", call_id=str(payload.get("toolCallId") or "")
        ),
        on_result=lambda payload: traj.record(
            "tool_result", payload, producer="bridge", call_id=str(payload.get("toolCallId") or "")
        ),
    )
    bridge.start()
    engine.start(bridge)
    first_turn = True
    try:
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
                print(
                    "Multi-turn tasks; writes need /approve. "
                    "Commands: /proposals /approve <id> /deny <id> /new /clear /exit"
                )
                continue
            if text == "/proposals":
                pending = registry.pending()
                if not pending:
                    print("(no pending proposals)")
                for proposal in pending:
                    print(_proposal_json(proposal))
                continue
            if text.startswith("/approve"):
                proposal_id = text.split()[1] if len(text.split()) > 1 else ""
                try:
                    consent = registry.approve(proposal_id, traj.run_id)
                except Exception as exc:  # noqa: BLE001
                    print(f"approve failed: {exc}")
                    continue
                traj.record(
                    "consent_bound",
                    {
                        "consent_id": consent.consent_id,
                        "proposal_id": consent.proposal_id,
                        "run_id": consent.run_id,
                    },
                    producer="admission",
                )
                print(f"approved: {consent.consent_id} — retry the task to apply the patch.")
                continue
            if text.startswith("/deny"):
                proposal_id = text.split()[1] if len(text.split()) > 1 else ""
                try:
                    denied = registry.deny(proposal_id)
                except Exception as exc:  # noqa: BLE001
                    print(f"deny failed: {exc}")
                    continue
                traj.record("proposal_denied", {"proposal_id": denied.proposal_id}, producer="admission")
                print(f"denied: {denied.proposal_id}")
                continue
            if text == "/new":
                traj.record("conversation_reset", {})
                traj = Session(project_root)
                engine.session = traj
                first_turn = True
                print("(new conversation)")
                continue
            if text == "/clear":
                print("\033[2J\033[H", end="")
                continue

            state["goal"] = text
            traj.record("task_received", {"goal": text})
            response = engine.ask(text, first_turn=first_turn)
            first_turn = False
            traj.record("run_finished", {"response_chars": len(response)})
            if engine.state.value == "crashed":
                print("(engine crashed; restarting for next turn)")
                engine.start(bridge)
                first_turn = True
            _print_response(response)
            _print_pending(registry)
    finally:
        engine.stop()
        bridge.stop()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="op0", description="op0 L1 execution base")
    parser.add_argument("--once", help="run one read-only goal and exit")
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
