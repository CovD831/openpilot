"""Terminal MVP for inspecting and exporting Evidence Core trajectories."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Sequence

from evidence_core.export.bundle import copy_run_bundle
from evidence_core.store.fs_store import DEFAULT_DATA_DIR, EvidenceStore


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="evidence",
        description="Inspect and export persisted Evidence Core trajectories.",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=DEFAULT_DATA_DIR,
        help=f"Evidence data directory (default: {DEFAULT_DATA_DIR})",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    list_parser = subparsers.add_parser("list", help="List run summaries")
    list_parser.add_argument("--json", action="store_true", help="Emit JSON")

    show_parser = subparsers.add_parser("show", help="Show one run and its artifacts")
    show_parser.add_argument("run_key", help="run_id, task_id, or session_id")
    show_parser.add_argument("--json", action="store_true", help="Emit JSON")

    timeline_parser = subparsers.add_parser("timeline", help="Show one run's event timeline")
    timeline_parser.add_argument("run_key", help="run_id, task_id, or session_id")
    timeline_parser.add_argument("--json", action="store_true", help="Emit JSON")

    export_parser = subparsers.add_parser("export", help="Copy one run into a portable bundle")
    export_parser.add_argument("run_key", help="run_id, task_id, or session_id")
    export_parser.add_argument("--output", type=Path, required=True, help="Bundle parent directory")
    export_parser.add_argument("--force", action="store_true", help="Replace an existing run bundle")
    serve_parser = subparsers.add_parser("serve", help="Serve the local read-only Evidence Viewer")
    serve_parser.add_argument("--host", default="127.0.0.1")
    serve_parser.add_argument("--port", type=int, default=8765)
    return parser


def _json_print(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


def _store(args: argparse.Namespace) -> EvidenceStore:
    return EvidenceStore(args.data_dir)


def _run_payload(store: EvidenceStore, run_key: str) -> dict[str, Any]:
    replay = store.replay_run(run_key)
    if replay is None:
        raise ValueError(f"run not found: {run_key}")
    return {
        "run": replay["run"].model_dump(mode="python"),
        "summary": replay["summary"].model_dump(mode="python"),
        "artifacts": [item.model_dump(mode="python") for item in replay["artifacts"]],
    }


def run(args: argparse.Namespace) -> int:
    store = _store(args)
    if args.command == "list":
        summaries = [item.model_dump(mode="python") for item in store.list_runs()]
        if args.json:
            _json_print(summaries)
        elif not summaries:
            print("No Evidence Core runs found.")
        else:
            for summary in summaries:
                print(
                    f"{summary['run_id']}  {summary['final_status']:<8} "
                    f"events={summary['event_count']:<3} tools={summary['tool_called_count']:<3} "
                    f"task={summary['task_id']}  goal={summary['goal']}"
                )
        return 0

    if args.command == "show":
        payload = _run_payload(store, args.run_key)
        if args.json:
            _json_print(payload)
        else:
            run_data = payload["run"]
            summary = payload["summary"]
            print(f"run_id: {run_data['run_id']}")
            print(f"task_id: {run_data['task_id']}")
            print(f"status: {summary['final_status']} success={summary['success']}")
            print(f"goal: {run_data['goal']}")
            print(f"reason: {run_data['completion_reason']}")
            print(
                f"events: {summary['event_count']}  tools: {summary['tool_called_count']}  "
                f"verification: {summary['verification_status']}"
            )
            print(f"artifacts: {len(payload['artifacts'])}")
            for artifact in payload["artifacts"]:
                print(f"  - {artifact['kind']}: {artifact['path']} ({artifact['bytes']} bytes)")
        return 0

    if args.command == "timeline":
        replay = store.replay_run(args.run_key)
        if replay is None:
            raise ValueError(f"run not found: {args.run_key}")
        events = [event.model_dump(mode="python") for event in replay["events"]]
        if args.json:
            _json_print(events)
        else:
            for event in events:
                print(
                    f"{event['sequence']:02d} {event['event_type']:<30} "
                    f"{event['phase']:<8} {event['summary']}"
                )
        return 0

    if args.command == "export":
        replay = store.replay_run(args.run_key)
        if replay is None:
            raise ValueError(f"run not found: {args.run_key}")
        run_dir = store.run_dir(replay["run"].run_id)
        target = args.output / run_dir.name
        if target.exists() and not args.force:
            raise ValueError(f"target exists: {target}; pass --force to replace it")
        bundle = copy_run_bundle(run_dir, args.output)
        print(f"exported={bundle}")
        return 0

    if args.command == "serve":
        from evidence_core.web import serve
        serve(args.data_dir, host=args.host, port=args.port)
        return 0

    raise ValueError(f"unknown command: {args.command}")


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
