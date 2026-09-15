"""Command line interface for OpenPilot."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence
from uuid import uuid4

from rich.console import Console

from core.config import EmbeddingSettings, LLMSettings


def build_parser() -> argparse.ArgumentParser:
    """Build the modern OpenPilot CLI parser."""
    parser = argparse.ArgumentParser(prog="openpilot", description="OpenPilot AI Agent System")
    subparsers = parser.add_subparsers(dest="command", required=True)

    config_parser = subparsers.add_parser("config", help="Configuration commands")
    config_subparsers = config_parser.add_subparsers(dest="config_command", required=True)
    config_subparsers.add_parser("check", help="Check LLM configuration")

    _add_run_parser(subparsers, "run", "Run the modern interactive OpenPilot CLI")
    _add_run_parser(subparsers, "openpilot", "Backward-compatible alias for run")
    revoke_parser = subparsers.add_parser(
        "revoke",
        help="Revoke one active mutation consent for an explicitly named Run",
    )
    revoke_parser.add_argument("--project-path", required=True, help="Project root that owns the consent state")
    revoke_parser.add_argument("--run-id", required=True, help="Run identity shown when the mutation started")
    revoke_parser.add_argument("--consent-id", required=True, help="Consent identity shown when the mutation started")
    recover_parser = subparsers.add_parser(
        "recover",
        help="Reconcile one indeterminate Pi mutation by rerunning its exact declared validation",
    )
    recover_parser.add_argument("--project-path", required=True, help="Project root that owns the Pi Evidence Run")
    recover_parser.add_argument("--run-id", required=True, help="Indeterminate Pi Run to reconcile")
    recover_parser.add_argument(
        "--confirm",
        action="store_true",
        help="Confirm one new approval for the original Run's exact validation only",
    )
    return parser


def _add_run_parser(subparsers, name: str, help_text: str) -> None:
    run_parser = subparsers.add_parser(name, help=help_text)
    run_parser.add_argument("--once", help="Run one goal and exit")
    run_parser.add_argument("--project-path", help="Explicit project root for task admission")


def main(argv: Sequence[str] | None = None, llm_client: Any | None = None) -> int:
    parser = build_parser()
    normalized_argv = list(sys.argv[1:] if argv is None else argv)
    if not normalized_argv or normalized_argv[0].startswith("-"):
        normalized_argv.insert(0, "run")
    args = parser.parse_args(normalized_argv)
    console = Console()

    if args.command == "config" and args.config_command == "check":
        return _config_check(console)

    if args.command == "revoke":
        return _revoke_mutation_consent(console, args)

    if args.command == "recover":
        return _recover_pi_mutation(console, args)

    if args.command in {"run", "openpilot"}:
        return _run_openpilot(args, console, llm_client)

    parser.error("Unknown command")
    return 2


def _run_openpilot(args, console: Console, llm_client: Any | None) -> int:
    """Run OpenPilot with enhanced UI."""
    from ui.enhanced_cli import run_enhanced_cli

    return run_enhanced_cli(args, console, llm_client)


def _config_check(console: Console) -> int:
    settings = LLMSettings()
    embedding_settings = EmbeddingSettings()
    rows = [
        ("provider", settings.provider),
        ("base_url", "set" if settings.base_url.strip() else "missing"),
        ("model", settings.model),
        ("timeout_seconds", str(settings.timeout_seconds)),
        ("temperature", str(settings.temperature)),
        ("api_key", "set" if settings.api_key and settings.api_key.strip() else "missing"),
        ("embedding_provider", embedding_settings.provider),
        ("embedding_base_url", "set" if embedding_settings.base_url and embedding_settings.base_url.strip() else "missing"),
        ("embedding_model", embedding_settings.model),
        ("embedding_timeout_seconds", str(embedding_settings.timeout_seconds)),
        ("embedding_api_key", "set" if embedding_settings.api_key and embedding_settings.api_key.strip() else "missing"),
    ]

    console.print("OpenPilot LLM Configuration")
    for field, value in rows:
        console.print(f"{field}: {value}")

    missing = settings.missing_fields()
    embedding_missing = embedding_settings.missing_fields()
    if missing:
        console.print(
            f"Missing LLM configuration: {', '.join(missing)}. "
            "Real LLM calls will fail."
        )
    if embedding_missing:
        console.print(
            f"Missing embedding configuration: {', '.join(embedding_missing)}. "
            "Real embedding calls will fail."
        )
    if missing or embedding_missing:
        return 0
    console.print("Configuration is ready.")
    return 0


def _revoke_mutation_consent(console: Console, args) -> int:
    """Persist a fail-closed revoke without starting the normal CLI runtime."""

    from autonomous_iteration.task_consent import TaskConsentRegistry

    project_root = Path(str(args.project_path)).expanduser().resolve(strict=False)
    if not project_root.is_dir():
        console.print("Mutation consent revoke failed: project path is not a directory.")
        return 2
    registry = TaskConsentRegistry(state_directory=project_root / ".openpilot" / "consents")
    try:
        state = registry.revoke(
            str(args.consent_id),
            run_id=str(args.run_id),
            project_root=project_root,
        )
    except (FileNotFoundError, KeyError, PermissionError, ValueError) as exc:
        console.print(f"Mutation consent revoke failed: {exc}")
        return 2
    console.print(
        f"Mutation consent revoked for run {state.consent.run_id}: {state.consent.consent_id}"
    )
    return 0


def _recover_pi_mutation(console: Console, args) -> int:
    """Present or execute the strictly scoped Pi mutation reconciliation flow."""

    from autonomous_iteration.pi_mutation_recovery import PiMutationRecoveryRunner
    from metadata import TaskApprovalGrant

    project_root = Path(str(args.project_path)).expanduser().resolve(strict=False)
    if not project_root.is_dir():
        console.print("Pi recovery failed: project path is not a directory.", markup=False)
        return 2
    runner = PiMutationRecoveryRunner()
    try:
        recovery = runner.prepare(str(args.run_id), project_root=project_root)
    except (KeyError, PermissionError, ValueError) as exc:
        console.print(f"Pi recovery preflight failed: {exc}", markup=False)
        return 2

    proposal = {
        "run_id": recovery.run_id,
        "mode": "exact_validation_recovery",
        "admission_id": recovery.admission.admission_id,
        "task_id": recovery.admission.task_id,
        "project_root": recovery.admission.project_root,
        "validation_command": recovery.admission.validation.command if recovery.admission.validation else "",
        "confirmation_required": True,
    }
    if not bool(args.confirm):
        console.print("approval_required: review the Pi recovery proposal, then rerun with --confirm.", markup=False)
        console.print(json.dumps(proposal, ensure_ascii=False, indent=2), markup=False)
        return 2

    approval = TaskApprovalGrant(
        approval_id=f"approval_recovery_{uuid4().hex}",
        proposal_id=recovery.proposal_id,
        admission_id=recovery.admission.admission_id,
        task_id=recovery.admission.task_id,
        project_root=recovery.admission.project_root,
        conversation_id=recovery.conversation_id,
        protocol_version=recovery.admission.protocol_version,
    )
    try:
        result = runner.recover(
            recovery.run_id,
            recovery.admission,
            approval=approval,
            conversation_id=recovery.conversation_id,
        )
    except (KeyError, PermissionError, RuntimeError, ValueError) as exc:
        console.print(f"Pi recovery failed: {exc}", markup=False)
        return 2
    console.print(json.dumps(result, ensure_ascii=False, indent=2), markup=False)
    return 0 if bool(result.get("success")) else 1


if __name__ == "__main__":
    raise SystemExit(main())
