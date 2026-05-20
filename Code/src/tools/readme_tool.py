"""README Tool - Generate a user-facing README for created projects."""

from __future__ import annotations

import ast
import json
import shlex
from pathlib import Path
from typing import Any

from metadata import ToolContractMetadata, ToolInputMetadata, ToolResultMetadata, metadata_tool_result

from core.tool_contracts import (
    PermissionLevel,
    ToolCapability,
    ToolDefinition,
    ToolFailureMode,
)


README_TOOL_DEFINITION = ToolDefinition(
    name="readme_tool",
    display_name="README Tool",
    description="Generate a README.md with setup and run instructions for a created project",
    version="1.0.0",
    capabilities=[ToolCapability.FILE_WRITE],
    permission_level=PermissionLevel.MEDIUM,
    contract_metadata=ToolContractMetadata(
        tool_name='readme_tool',
        input_metadata_type="ToolInputMetadata",
        output_metadata_type="ToolResultMetadata",
        required_input_fields=['project_path'],
        input_defaults={'project_summary': '', 'written_files': [], 'entry_files': [], 'environment': {}, 'run_command': '', 'setup_commands': [], 'test_command': '', 'overwrite': True},
    ),
    timeout_seconds=30,
    max_retries=1,
    failure_modes=[
        ToolFailureMode(
            error_type="permission_denied",
            description="No permission to write README.md",
            recovery_strategy="Check project directory permissions",
        ),
        ToolFailureMode(
            error_type="file_exists",
            description="README.md exists and overwrite=False",
            recovery_strategy="Set overwrite=True or choose a different project directory",
        ),
        ToolFailureMode(
            error_type="invalid_input",
            description="Project path is missing or invalid",
            recovery_strategy="Provide a valid project_path",
        ),
    ],
    tags=["readme", "documentation", "project", "instructions"],
    audit_required=True,
)


@metadata_tool_result('readme_tool')
def readme_tool_executor(input_metadata: ToolInputMetadata) -> ToolResultMetadata:
    params = input_metadata.to_params()
    """Generate README.md for a project."""
    project_path = Path(params["project_path"]).expanduser()
    readme_path = project_path / "README.md"
    overwrite = params.get("overwrite", True)

    if readme_path.exists() and not overwrite:
        raise FileExistsError(f"README.md exists and overwrite=False: {readme_path}")

    project_path.mkdir(parents=True, exist_ok=True)

    written_files = _coerce_path_list(params.get("written_files", []))
    entry_files = _coerce_path_list(params.get("entry_files", []))
    setup_commands = _coerce_string_list(params.get("setup_commands", []))
    explicit_run_command = str(params.get("run_command") or "").strip()
    test_command = str(params.get("test_command") or "").strip()
    environment = params.get("environment", {})

    inferred = _infer_project_commands(
        project_path=project_path,
        written_files=written_files,
        entry_files=entry_files,
    )
    if not setup_commands:
        setup_commands = inferred["setup_commands"]
    run_command = explicit_run_command or inferred["run_command"]

    content, sections = _build_readme_content(
        project_path=project_path,
        project_summary=str(params.get("project_summary") or ""),
        written_files=written_files,
        environment=environment,
        setup_commands=setup_commands,
        run_command=run_command,
        test_command=test_command,
    )

    created = not readme_path.exists()
    readme_path.write_text(content, encoding="utf-8")
    bytes_written = readme_path.stat().st_size

    return {
        "file_path": str(readme_path.absolute()),
        "bytes_written": bytes_written,
        "created": created,
        "run_command": run_command,
        "setup_commands": setup_commands,
        "sections": sections,
    }


def _coerce_path_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (str, Path)):
        return [str(value)]
    if isinstance(value, list):
        paths: list[str] = []
        for item in value:
            if isinstance(item, dict):
                item = item.get("file_path") or item.get("path")
            if item:
                paths.append(str(item))
        return paths
    return []


def _coerce_string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [str(value)]


def _infer_project_commands(
    project_path: Path,
    written_files: list[str],
    entry_files: list[str],
) -> dict[str, Any]:
    package_json = project_path / "package.json"
    if package_json.exists():
        run_command = _infer_npm_run_command(package_json)
        return {
            "run_command": run_command,
            "setup_commands": ["npm install"],
        }

    candidates = _candidate_paths(project_path, entry_files + written_files)
    python_files = [path for path in candidates if path.suffix == ".py"]
    python_entry = _select_python_entry(project_path, python_files)
    if python_entry:
        files_for_import_scan = python_files or sorted(project_path.glob("*.py"))
        if python_entry not in files_for_import_scan:
            files_for_import_scan.append(python_entry)
        setup_commands = _infer_python_setup_commands(project_path, files_for_import_scan)
        return {
            "run_command": f"python {shlex.quote(_relative_command_path(project_path, python_entry))}",
            "setup_commands": setup_commands,
        }

    return {
        "run_command": "",
        "setup_commands": [],
    }


def _infer_npm_run_command(package_json: Path) -> str:
    try:
        data = json.loads(package_json.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "npm start"

    scripts = data.get("scripts", {}) if isinstance(data, dict) else {}
    if isinstance(scripts, dict):
        if "dev" in scripts:
            return "npm run dev"
        if "start" in scripts:
            return "npm start"
    return "npm start"


def _candidate_paths(project_path: Path, paths: list[str]) -> list[Path]:
    candidates: list[Path] = []
    seen: set[Path] = set()
    for raw_path in paths:
        path = Path(raw_path).expanduser()
        if not path.is_absolute():
            path = project_path / path
        try:
            resolved = path.resolve()
        except OSError:
            resolved = path.absolute()
        if resolved not in seen:
            candidates.append(path)
            seen.add(resolved)
    return candidates


def _select_python_entry(project_path: Path, python_files: list[Path]) -> Path | None:
    if not python_files:
        direct_main = project_path / "main.py"
        direct_app = project_path / "app.py"
        if direct_main.exists():
            return direct_main
        if direct_app.exists():
            return direct_app
        existing = sorted(project_path.glob("*.py"))
        return existing[0] if existing else None

    priority = {"main.py": 0, "app.py": 1}
    return sorted(
        python_files,
        key=lambda path: (
            priority.get(path.name, 2),
            len(path.parts),
            path.name,
        ),
    )[0]


def _infer_python_setup_commands(project_path: Path, python_files: list[Path]) -> list[str]:
    requirements = project_path / "requirements.txt"
    if requirements.exists():
        return ["pip install -r requirements.txt"]

    imports = set()
    for path in python_files:
        imports.update(_read_python_imports(path))
    if "pygame" in imports:
        return ["pip install pygame"]
    return []


def _read_python_imports(path: Path) -> set[str]:
    try:
        source = path.read_text(encoding="utf-8")
    except OSError:
        return set()

    try:
        tree = ast.parse(source)
    except SyntaxError:
        return {"pygame"} if "import pygame" in source or "from pygame" in source else set()

    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module.split(".", 1)[0])
    return imports


def _relative_command_path(project_path: Path, file_path: Path) -> str:
    try:
        return file_path.resolve().relative_to(project_path.resolve()).as_posix()
    except ValueError:
        return file_path.as_posix()


def _build_readme_content(
    project_path: Path,
    project_summary: str,
    written_files: list[str],
    environment: Any,
    setup_commands: list[str],
    run_command: str,
    test_command: str,
) -> tuple[str, list[str]]:
    title = project_path.name or "Project"
    description = project_summary.strip() or "Generated project."
    sections = ["Overview", "Requirements", "Setup", "Run", "Files", "Troubleshooting"]
    if test_command:
        sections.insert(4, "Test")

    lines = [
        f"# {title}",
        "",
        "## Overview",
        "",
        description,
        "",
        "## Requirements",
        "",
    ]

    requirements = _format_environment(environment)
    if requirements:
        lines.extend(requirements)
    elif _looks_like_python_project(project_path, written_files):
        lines.append("- Python 3")
    elif (project_path / "package.json").exists():
        lines.append("- Node.js and npm")
    else:
        lines.append("- A compatible local runtime for the generated files")

    lines.extend(["", "## Setup", ""])
    if setup_commands:
        for command in setup_commands:
            lines.extend(["```bash", command, "```", ""])
    else:
        lines.append("No extra setup is required for the detected project files.")
        lines.append("")

    lines.extend(["## Run", ""])
    if run_command:
        lines.extend(["```bash", run_command, "```", ""])
    else:
        lines.append("Open the generated files with the runtime or application they target.")
        lines.append("")

    if test_command:
        lines.extend(["## Test", "", "```bash", test_command, "```", ""])

    lines.extend(["## Files", ""])
    file_lines = _format_written_files(project_path, written_files)
    if file_lines:
        lines.extend(file_lines)
    else:
        lines.append("- Project files are in this directory.")

    lines.extend([
        "",
        "## Troubleshooting",
        "",
        "- If the run command fails because a package is missing, run the setup command first.",
        "- If you use a virtual environment or Conda environment, activate it before running the project.",
        "- Run commands from this project directory unless the command says otherwise.",
    ])
    if _looks_like_interactive_python_project(project_path, written_files):
        lines.append("- Terminal or GUI games should be run in a real interactive terminal/window, not from a captured non-interactive smoke test.")
    lines.append("")

    return "\n".join(lines), sections


def _format_environment(environment: Any) -> list[str]:
    if not environment:
        return []
    if isinstance(environment, str):
        return [f"- {environment}"] if environment.strip() else []
    if isinstance(environment, dict):
        lines = []
        for key, value in environment.items():
            if value:
                label = str(key).replace("_", " ").title()
                lines.append(f"- {label}: {value}")
        return lines
    return [f"- {environment}"]


def _looks_like_python_project(project_path: Path, written_files: list[str]) -> bool:
    if (project_path / "main.py").exists() or (project_path / "app.py").exists():
        return True
    return any(str(path).endswith(".py") for path in written_files)


def _looks_like_interactive_python_project(project_path: Path, written_files: list[str]) -> bool:
    candidates = _candidate_paths(project_path, written_files)
    python_files = [path for path in candidates if path.suffix == ".py"]
    interactive_imports = {"curses", "tkinter", "turtle", "pygame"}
    for path in python_files:
        if _read_python_imports(path).intersection(interactive_imports):
            return True
    return False


def _format_written_files(project_path: Path, written_files: list[str]) -> list[str]:
    if not written_files:
        return []
    lines = []
    for raw_path in written_files:
        path = Path(raw_path).expanduser()
        if not path.is_absolute():
            path = project_path / path
        lines.append(f"- `{_relative_command_path(project_path, path)}`")
    return lines
