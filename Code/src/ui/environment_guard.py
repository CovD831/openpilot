"""Runtime environment guardrails for OpenPilot CLI."""

from __future__ import annotations

import os
import sys
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


def active_socks_proxy() -> str | None:
    """Return the first configured SOCKS proxy URL from common env vars."""
    for name in ("ALL_PROXY", "all_proxy", "HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy"):
        value = os.environ.get(name)
        if not value:
            continue
        lowered = value.lower()
        if lowered.startswith(("socks://", "socks4://", "socks5://")):
            return f"{name}={value}"
    return None


def socksio_available() -> bool:
    """Return whether socksio can be imported in the active Python environment."""
    try:
        import socksio  # noqa: F401
    except ImportError:
        return False
    return True


def socks_preflight_error_message() -> str | None:
    """Return a targeted SOCKS dependency error before LLM/httpx calls."""
    proxy = active_socks_proxy()
    if not proxy or socksio_available():
        return None

    conda_env = os.environ.get("CONDA_DEFAULT_ENV") or "unknown"
    return (
        "SOCKS proxy is enabled but the active Python environment is missing socksio.\n\n"
        f"Proxy: {proxy}\n"
        f"Python: {sys.executable}\n"
        f"Conda env: {conda_env}\n\n"
        "httpx is already installed in many environments, but SOCKS proxy support needs the "
        "separate socksio package.\n\n"
        "Preferred fix:\n"
        "conda install -n openpilot -c conda-forge socksio\n\n"
        "Pip fallback if conda is unavailable:\n"
        "python -m pip install socksio -i https://pypi.tuna.tsinghua.edu.cn/simple\n\n"
        "After changing proxy settings, verify with:\n"
        "env | grep -i proxy"
    )


def block_missing_socksio(console: Console) -> bool:
    """Return True after rendering a SOCKS dependency error."""
    message = socks_preflight_error_message()
    if not message:
        return False
    console.print(
        Panel(
            message,
            title="[bold red]Missing SOCKS Proxy Dependency[/bold red]",
            border_style="red",
        )
    )
    return True


def raise_for_missing_socksio() -> None:
    """Raise a RuntimeError when SOCKS proxy is active without socksio."""
    message = socks_preflight_error_message()
    if message:
        raise RuntimeError(message)


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
        "The missing concrete package is socksio; httpx may already be installed."
        f"{env_note}\n\n"
        "Preferred fix:\n"
        "conda install -n openpilot -c conda-forge socksio\n\n"
        "Pip fallback:\n"
        "python -m pip install socksio -i https://pypi.tuna.tsinghua.edu.cn/simple\n\n"
        "Then rerun:\n"
        "conda activate openpilot\n"
        "openpilot run"
    )
