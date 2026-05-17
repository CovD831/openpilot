"""Runtime environment guardrails for OpenPilot CLI."""

from __future__ import annotations

import os
from pathlib import Path

from rich.console import Console
from rich.panel import Panel


PROJECT_ROOT = Path(__file__).resolve().parents[3]
PROJECT_VENV_NAMES = {".venv", "venv"}


def active_project_venv() -> Path | None:
    """Return the active project-local venv when OpenPilot is running inside one."""
    virtual_env = os.environ.get("VIRTUAL_ENV")
    if not virtual_env:
        return None

    env_path = Path(virtual_env).expanduser().resolve()
    try:
        env_path.relative_to(PROJECT_ROOT)
    except ValueError:
        return None

    if env_path.name in PROJECT_VENV_NAMES:
        return env_path
    return None


def project_venv_message(env_path: Path) -> str:
    """Build a clear diagnostic for project-local venv activation."""
    return (
        "OpenPilot is running from a project-local virtual environment:\n"
        f"{env_path}\n\n"
        "This environment is intended for generated project artifacts, not for the OpenPilot runtime. "
        "It may be missing runtime dependencies such as httpx[socks], which causes SOCKS proxy errors.\n\n"
        "Deactivate the project venv, activate the OpenPilot conda environment, then rerun OpenPilot:\n\n"
        "deactivate\n"
        "conda activate openpilot\n"
        "openpilot run"
    )


def show_project_venv_error(console: Console, env_path: Path) -> None:
    """Render a project-local venv error."""
    console.print(
        Panel(
            project_venv_message(env_path),
            title="[bold red]OpenPilot Runtime Environment Mismatch[/bold red]",
            border_style="red",
        )
    )


def block_project_venv(console: Console) -> bool:
    """Return True after showing an error when a project-local venv is active."""
    env_path = active_project_venv()
    if not env_path:
        return False
    show_project_venv_error(console, env_path)
    return True


def is_socks_dependency_error(exc: BaseException) -> bool:
    """Detect the common httpx SOCKS extra / socksio missing dependency error."""
    text = str(exc).lower()
    return "socks proxy" in text and ("socksio" in text or "httpx[socks]" in text)


def agent_generator_llm_error_message(exc: BaseException) -> str:
    """Return a clearer Agent Generator LLM failure message when possible."""
    if not is_socks_dependency_error(exc):
        return str(exc)

    env_path = active_project_venv()
    env_note = (
        f"\n\nActive project .venv: {env_path}"
        if env_path is not None
        else ""
    )
    return (
        "Agent Generator could not call the LLM because SOCKS proxy support is missing. "
        "You are likely running OpenPilot from a project .venv or an environment missing httpx[socks]."
        f"{env_note}\n\n"
        "Fix options:\n"
        "1. deactivate\n"
        "2. conda activate openpilot\n"
        "3. pip install \"httpx[socks]>=0.24.0\"\n"
        "4. openpilot run"
    )
