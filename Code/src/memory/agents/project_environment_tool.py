"""Environment management tools for virtual environments."""

from __future__ import annotations

import platform
import sys
import ast
import os
from pathlib import Path
from typing import Any

from metadata import (
    DependencyStrategyMetadata,
    ProjectDependencyMetadata,
    ToolContractMetadata,
    ToolInputMetadata,
    ToolResultMetadata,
    metadata_tool_result,
)


from core.python_packages import IMPORT_TO_DISTRIBUTION, distribution_for_import
from memory.agents.git_manager_agent import GitManagerAgent, GitManagerError
from memory.memory_models import MemoryRecord, MemoryType
from memory.agents.virtual_environment_manager import (
    EnvInfo,
    EnvOperationResult,
    EnvStatus,
    EnvType,
    EnvironmentManager,
)
from core.tool_contracts import (
    PermissionLevel,
    ToolCapability,
    ToolDefinition,
    ToolFailureMode,
)


PROJECT_ENVIRONMENT_TOOL_DEFINITION = ToolDefinition(
    name="project_environment_tool",
    display_name="Project Environment Tool",
    description="Create or sync a project-bound Python virtual environment and install detected dependencies",
    version="1.0.0",
    capabilities=[ToolCapability.FILE_READ, ToolCapability.SHELL_EXECUTION, ToolCapability.NETWORK],
    permission_level=PermissionLevel.MEDIUM,
    contract_metadata=ToolContractMetadata(
        tool_name='project_environment_tool',
        input_metadata_type="ToolInputMetadata",
        output_metadata_type="ToolResultMetadata",
        required_input_fields=['project_path'],
        input_defaults={'written_files': [], 'entry_files': [], 'run_command': '', 'env_name': '.venv', 'install': True},
    ),
    timeout_seconds=900,
    max_retries=0,
    failure_modes=[
        ToolFailureMode(
            error_type="environment_setup_failed",
            description="The project virtual environment could not be created or synchronized",
            recovery_strategy="Inspect the venv creation or pip install error and retry after fixing dependencies",
        ),
    ],
    tags=["environment", "venv", "dependencies", "project"],
    audit_required=True,
)


THIRD_PARTY_IMPORT_MAP = IMPORT_TO_DISTRIBUTION

DEPENDENCY_ROLE_HINTS = {
    "pygame": "interactive_window_rendering_input_game_loop",
    "pillow": "image_processing",
    "opencv-python": "computer_vision_image_processing",
    "pyyaml": "configuration_data_loading",
    "scikit-learn": "machine_learning",
    "numpy": "numeric_computing",
    "pandas": "data_analysis",
    "matplotlib": "data_visualization",
    "rich": "terminal_ui_formatting",
    "click": "cli_command_interface",
    "typer": "cli_command_interface",
    "flask": "web_server",
    "fastapi": "web_api",
    "requests": "http_client",
    "speechrecognition": "speech_to_text",
    "pyttsx3": "text_to_speech",
}

PACKAGING_TOOL_PACKAGES = {"pip", "setuptools", "wheel"}


@metadata_tool_result('project_environment_tool')
def project_environment_tool_executor(input_metadata: ToolInputMetadata) -> ToolResultMetadata:
    params = input_metadata.to_params()
    """Create/sync a project-local .venv and record dependency context."""
    project_path = Path(params["project_path"]).expanduser()
    project_path.mkdir(parents=True, exist_ok=True)
    env_name = str(params.get("env_name") or ".venv")
    written_files = _coerce_path_list(params.get("written_files", []))
    entry_files = _coerce_path_list(params.get("entry_files", []))
    install = bool(params.get("install", True))
    memory_store = params.get("_memory_store")
    manager = params.get("_environment_manager") or EnvironmentManager(base_dir=project_path)

    env_path = project_path / env_name
    operations: list[dict[str, Any]] = []
    if not env_path.exists():
        create_result = manager.create_env(env_name)
        operations.append({"operation": "create_env", "success": create_result.success, "message": create_result.message})
        if not create_result.success:
            raise RuntimeError(create_result.error or create_result.message)
    else:
        operations.append({"operation": "create_env", "success": True, "message": f"Environment '{env_name}' already exists"})

    requirements = project_path / "requirements.txt"
    if requirements.exists():
        dependency_source = "requirements.txt"
        detected_packages = _read_requirements_packages(requirements)
        if install:
            install_result = manager.install_requirements(env_name, requirements)
            operations.append({"operation": "install_requirements", "success": install_result.success, "message": install_result.message})
            if not install_result.success:
                raise RuntimeError(install_result.error or install_result.message)
    else:
        dependency_source = "import_scan"
        detected_packages = infer_project_dependencies(project_path, written_files + entry_files)
        if install:
            installed_names = _installed_package_names(manager.list_packages(env_name))
            for package in detected_packages:
                if _package_key(package) in installed_names:
                    operations.append({"operation": "install_package", "package": package, "success": True, "message": "already installed"})
                    continue
                install_result = manager.install_package(env_name, package)
                operations.append(
                    {
                        "operation": "install_package",
                        "package": package,
                        "success": install_result.success,
                        "message": install_result.message,
                    }
                )
                if not install_result.success:
                    raise RuntimeError(install_result.error or install_result.message)

    packages = [package for package in manager.list_packages(env_name) if package]
    dependency_context = build_project_dependency_context(
        project_path=project_path,
        files=written_files + entry_files,
        detected_packages=detected_packages,
        installed_packages=packages,
        dependency_source=dependency_source,
    )
    dependency_strategy = build_dependency_strategy(dependency_context)
    warnings: list[str] = []
    git_repository = None
    git_snapshot = None
    try:
        git_repository, git_snapshot = GitManagerAgent().ensure_repository(project_path)
        operations.append(
            {
                "operation": "git_ensure_repository",
                "success": True,
                "message": "git repository ready",
                "head": git_repository.head,
                "snapshot": git_snapshot.commit_hash if git_snapshot else "",
            }
        )
    except GitManagerError as exc:
        warnings.append(f"Git safety unavailable: {exc}")
        operations.append({"operation": "git_ensure_repository", "success": False, "message": str(exc)})
    env_info = manager.get_env_info(env_name)
    python_executable = _venv_python_path(env_path)
    pip_executable = _venv_pip_path(env_path)
    run_command = _venv_run_command(project_path, entry_files + written_files, params.get("run_command"))
    setup_commands = _venv_setup_commands(env_name, detected_packages, dependency_source)
    command_env = _venv_command_env(env_path)
    payload = {
        "project_path": str(project_path),
        "venv_path": str(env_path),
        "env_name": env_name,
        "python_executable": str(python_executable),
        "pip_executable": str(pip_executable),
        "python_version": getattr(env_info, "python_version", None) or "",
        "detected_packages": detected_packages,
        "installed_packages": packages,
        "dependencies": [dependency.to_json_dict() for dependency in dependency_context],
        "dependency_strategy": dependency_strategy.to_json_dict(),
        "git_repository": git_repository.to_json_dict() if git_repository else None,
        "git_snapshot": git_snapshot.to_json_dict() if git_snapshot else None,
        "dependency_source": dependency_source,
        "setup_commands": setup_commands,
        "run_command": run_command,
        "command_cwd": str(project_path),
        "command_env": command_env,
        "python_command": str(python_executable),
        "pip_command": str(pip_executable),
        "operations": operations,
        "warnings": warnings,
    }
    _save_environment_memory(memory_store, project_path, payload)
    return payload


def infer_project_dependencies(project_path: Path, files: list[str]) -> list[str]:
    """Infer third-party packages from Python imports."""
    candidates = _candidate_python_files(project_path, files)
    local_modules = {path.stem for path in candidates}
    local_modules.update(path.stem for path in project_path.glob("*.py") if path.is_file())
    local_modules.update(path.name for path in project_path.iterdir() if path.is_dir() and (path / "__init__.py").exists())
    imports: set[str] = set()
    for path in candidates:
        imports.update(_read_top_level_imports(path))
    packages = []
    for import_name in sorted(imports):
        if _is_stdlib_or_local(import_name, local_modules):
            continue
        packages.append(distribution_for_import(import_name))
    return sorted(set(packages), key=str.lower)


def build_project_dependency_context(
    *,
    project_path: Path,
    files: list[str],
    detected_packages: list[str] | None = None,
    installed_packages: list[str] | None = None,
    dependency_source: str = "",
    readme_text: str = "",
) -> list[ProjectDependencyMetadata]:
    """Merge installed packages, imports, requirements, and README hints into dependency metadata."""
    detected = detected_packages if detected_packages is not None else infer_project_dependencies(project_path, files)
    installed = installed_packages or []
    imports_by_package = _imports_by_package(project_path, files)
    by_key: dict[str, dict[str, Any]] = {}

    for package in detected:
        key = _package_key(package)
        item = by_key.setdefault(key, _dependency_seed(package))
        item["dependency_sources"].append(dependency_source or "import_scan")
        item["evidence"].append(f"detected dependency: {package}")

    for raw_package in installed:
        name, version = _parse_installed_package(raw_package)
        if not name or _package_key(name) in PACKAGING_TOOL_PACKAGES:
            continue
        key = _package_key(name)
        item = by_key.setdefault(key, _dependency_seed(name))
        item["package_name"] = name
        item["version"] = version or item["version"]
        item["dependency_sources"].append("installed")
        item["evidence"].append(f"installed package: {raw_package}")

    for package, import_names in imports_by_package.items():
        key = _package_key(package)
        item = by_key.setdefault(key, _dependency_seed(package))
        item["import_names"].extend(import_names)
        item["import_usage"].extend(f"import {name}" for name in import_names)
        item["dependency_sources"].append("import_scan")
        item["evidence"].append(f"code imports: {', '.join(import_names)}")

    requirements = project_path / "requirements.txt"
    for package in _read_requirements_packages(requirements) if requirements.exists() else []:
        key = _package_key(package)
        item = by_key.setdefault(key, _dependency_seed(package))
        item["dependency_sources"].append("requirements")
        item["evidence"].append(f"requirements.txt declares: {package}")

    readme_lower = readme_text.lower()
    for package_key, item in list(by_key.items()):
        if package_key and package_key in readme_lower:
            item["dependency_sources"].append("readme")
            item["evidence"].append(f"README mentions {item['package_name']}")

    dependencies = []
    for item in by_key.values():
        package_key = _package_key(item["package_name"])
        role = DEPENDENCY_ROLE_HINTS.get(package_key, "")
        sources = sorted(set(item["dependency_sources"]))
        evidence = _dedupe_text(item["evidence"])
        confidence = 0.45
        if "installed" in sources:
            confidence += 0.18
        if "import_scan" in sources:
            confidence += 0.22
        if "requirements" in sources or "readme" in sources:
            confidence += 0.12
        if role:
            confidence += 0.08
        dependencies.append(
            ProjectDependencyMetadata(
                package_name=item["package_name"],
                version=item["version"],
                import_names=_dedupe_text(item["import_names"]),
                dependency_sources=sources,
                import_usage=_dedupe_text(item["import_usage"]),
                role=role,
                evidence=evidence,
                confidence=min(0.98, round(confidence, 3)),
            )
        )
    return sorted(dependencies, key=lambda dependency: dependency.package_name.lower())


def build_dependency_strategy(dependencies: list[ProjectDependencyMetadata]) -> DependencyStrategyMetadata:
    """Default policy: preserve useful existing libraries and require evidence before replacing them."""
    preserve = []
    rationale = []
    for dependency in dependencies:
        if dependency.role or dependency.import_names or "installed" in dependency.dependency_sources:
            preserve.append(dependency.package_name)
            role_text = f" for {dependency.role}" if dependency.role else ""
            rationale.append(f"Preserve {dependency.package_name}{role_text}; it is existing project capability evidence.")
    return DependencyStrategyMetadata(
        preserve_packages=sorted(set(preserve), key=str.lower),
        recommended_packages=[],
        replaceable_packages=[],
        rejected_removals=[],
        rationale=_dedupe_text(rationale),
        confidence=0.78 if preserve else 0.52,
    )


def _coerce_path_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (str, Path)):
        return [str(value)]
    if isinstance(value, list):
        result = []
        for item in value:
            if isinstance(item, dict):
                item = item.get("file_path") or item.get("path")
            if item:
                result.append(str(item))
        return result
    return []


def _candidate_python_files(project_path: Path, files: list[str]) -> list[Path]:
    candidates: list[Path] = []
    for raw_path in files:
        path = Path(raw_path).expanduser()
        if not path.is_absolute():
            path = project_path / path
        if path.exists() and path.suffix == ".py" and path not in candidates:
            candidates.append(path)
    if candidates:
        return candidates
    return [path for path in sorted(project_path.glob("*.py")) if path.is_file()]


def _read_top_level_imports(path: Path) -> set[str]:
    try:
        source = path.read_text(encoding="utf-8")
    except OSError:
        return set()
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return set()
    imports = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module.split(".", 1)[0])
    return imports


def _imports_by_package(project_path: Path, files: list[str]) -> dict[str, list[str]]:
    imports: dict[str, list[str]] = {}
    candidates = _candidate_python_files(project_path, files)
    local_modules = {path.stem for path in candidates}
    local_modules.update(path.stem for path in project_path.glob("*.py") if path.is_file())
    for path in candidates:
        for import_name in _read_top_level_imports(path):
            if _is_stdlib_or_local(import_name, local_modules):
                continue
            package = distribution_for_import(import_name)
            imports.setdefault(package, []).append(import_name)
    return {package: sorted(set(names)) for package, names in imports.items()}


def _dependency_seed(package: str) -> dict[str, Any]:
    name, version = _parse_installed_package(package)
    return {
        "package_name": name or package,
        "version": version,
        "import_names": [],
        "dependency_sources": [],
        "import_usage": [],
        "evidence": [],
    }


def _parse_installed_package(package: str) -> tuple[str, str]:
    text = str(package or "").strip()
    if not text:
        return "", ""
    for separator in ("==", ">=", "<=", "~=", ">", "<"):
        if separator in text:
            name, version = text.split(separator, 1)
            return name.strip(), version.strip()
    return text.strip(), ""


def _dedupe_text(items: list[str]) -> list[str]:
    seen = set()
    result = []
    for item in items:
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        result.append(text)
        seen.add(text)
    return result


def _is_stdlib_or_local(import_name: str, local_modules: set[str]) -> bool:
    if import_name in local_modules:
        return True
    if import_name in THIRD_PARTY_IMPORT_MAP:
        return False
    stdlib = getattr(sys, "stdlib_module_names", set())
    return import_name in stdlib or import_name.startswith("_")


def _read_requirements_packages(requirements: Path) -> list[str]:
    packages = []
    for line in requirements.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith("-"):
            continue
        packages.append(stripped)
    return packages


def _installed_package_names(packages: list[str]) -> set[str]:
    names = set()
    for package in packages:
        name = package.split("==", 1)[0].split(">=", 1)[0].split("<=", 1)[0].strip()
        if name:
            names.add(_package_key(name))
    return names


def _package_key(package: str) -> str:
    return package.lower().replace("_", "-")


def _venv_python_path(env_path: Path) -> Path:
    return env_path / ("Scripts/python.exe" if platform.system() == "Windows" else "bin/python")


def _venv_pip_path(env_path: Path) -> Path:
    return env_path / ("Scripts/pip.exe" if platform.system() == "Windows" else "bin/pip")


def _venv_setup_commands(env_name: str, packages: list[str], dependency_source: str) -> list[str]:
    python_bin = f"{env_name}/Scripts/python.exe" if platform.system() == "Windows" else f"{env_name}/bin/python"
    pip_bin = f"{env_name}/Scripts/pip.exe" if platform.system() == "Windows" else f"{env_name}/bin/pip"
    commands = [f"python -m venv {env_name}"]
    if dependency_source == "requirements.txt":
        commands.append(f"{pip_bin} install -r requirements.txt")
    elif packages:
        commands.append(f"{pip_bin} install {' '.join(packages)}")
    commands.append(f"{python_bin} --version")
    return commands


def _venv_run_command(project_path: Path, files: list[str], explicit_run_command: Any) -> str:
    entry = _select_entry_file(project_path, files)
    if not entry:
        existing = str(explicit_run_command or "").strip()
        return existing
    python_bin = ".venv/Scripts/python.exe" if platform.system() == "Windows" else ".venv/bin/python"
    try:
        relative = entry.resolve().relative_to(project_path.resolve()).as_posix()
    except ValueError:
        relative = entry.name
    return f"{python_bin} {relative}"


def _venv_command_env(env_path: Path) -> dict[str, str]:
    bin_dir = env_path / ("Scripts" if platform.system() == "Windows" else "bin")
    current_path = os.environ.get("PATH", "")
    path_value = str(bin_dir) + (os.pathsep + current_path if current_path else "")
    return {
        "VIRTUAL_ENV": str(env_path),
        "PATH": path_value,
    }


def _select_entry_file(project_path: Path, files: list[str]) -> Path | None:
    candidates = _candidate_python_files(project_path, files)
    if not candidates:
        return None
    for name in ("main.py", "app.py"):
        for path in candidates:
            if path.name == name:
                return path
    return candidates[0]


def _save_environment_memory(memory_store: Any, project_path: Path, payload: dict[str, Any]) -> None:
    if not memory_store or not hasattr(memory_store, "save"):
        return
    packages = payload.get("detected_packages") or []
    content = (
        f"Project environment for {project_path}: "
        f"venv={payload.get('venv_path')} python={payload.get('python_executable')} "
        f"python_version={payload.get('python_version')} packages={packages} "
        f"dependency_source={payload.get('dependency_source')} run_command={payload.get('run_command')}"
    )
    try:
        memory_store.save(
            MemoryRecord(
                id="",
                memory_type=MemoryType.SHORT_TERM,
                content=content,
                tags=["project_environment", project_path.name, *[_package_key(package) for package in packages]],
                confidence=0.95,
                attributes=payload,
            )
        )
    except Exception:
        pass
