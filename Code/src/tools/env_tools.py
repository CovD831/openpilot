"""Environment management tools for virtual environments."""

from __future__ import annotations

import os
import platform
import subprocess
import sys
import ast
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from memory.memory_models import MemoryRecord, MemoryType
from tools.tool_models import (
    PermissionLevel,
    ToolCapability,
    ToolDefinition,
    ToolFailureMode,
    ToolInputSchema,
    ToolOutputSchema,
)


class EnvType(str, Enum):
    """Virtual environment types."""
    VENV = "venv"
    VIRTUALENV = "virtualenv"
    CONDA = "conda"


class EnvStatus(str, Enum):
    """Environment status."""
    ACTIVE = "active"
    INACTIVE = "inactive"
    NOT_FOUND = "not_found"


@dataclass
class EnvInfo:
    """Virtual environment information."""

    name: str
    path: Path
    env_type: EnvType
    python_version: str | None
    status: EnvStatus
    packages: list[str] | None = None


class EnvOperationResult(BaseModel):
    """Result of environment operation."""

    success: bool
    message: str
    env_info: dict[str, Any] | None = None
    error: str | None = None


PROJECT_ENVIRONMENT_TOOL_DEFINITION = ToolDefinition(
    name="project_environment_tool",
    display_name="Project Environment Tool",
    description="Create or sync a project-bound Python virtual environment and install detected dependencies",
    version="1.0.0",
    capabilities=[ToolCapability.FILE_READ, ToolCapability.SHELL_EXECUTION, ToolCapability.NETWORK],
    permission_level=PermissionLevel.MEDIUM,
    input_schema=[
        ToolInputSchema(name="project_path", type="string", description="Project directory", required=True),
        ToolInputSchema(name="written_files", type="array", description="Project files to scan for Python imports", required=False, default=[]),
        ToolInputSchema(name="entry_files", type="array", description="Preferred runnable entry files", required=False, default=[]),
        ToolInputSchema(name="run_command", type="string", description="Existing run command to adapt to the venv", required=False, default=""),
        ToolInputSchema(name="env_name", type="string", description="Project-local virtual environment directory name", required=False, default=".venv"),
        ToolInputSchema(name="install", type="boolean", description="Install missing dependencies", required=False, default=True),
    ],
    output_schema=ToolOutputSchema(
        type="object",
        description="Project environment sync result",
        properties={
            "project_path": {"type": "string"},
            "venv_path": {"type": "string"},
            "python_executable": {"type": "string"},
            "pip_executable": {"type": "string"},
            "python_version": {"type": "string"},
            "detected_packages": {"type": "array"},
            "installed_packages": {"type": "array"},
            "dependency_source": {"type": "string"},
            "setup_commands": {"type": "array"},
            "run_command": {"type": "string"},
        },
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


THIRD_PARTY_IMPORT_MAP = {
    "pygame": "pygame",
    "PIL": "Pillow",
    "cv2": "opencv-python",
    "yaml": "PyYAML",
    "sklearn": "scikit-learn",
}


class EnvironmentManager:
    """Manager for virtual environments."""

    def __init__(self, base_dir: str | Path = ".venvs"):
        """Initialize environment manager.

        Args:
            base_dir: Base directory for virtual environments
        """
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def create_env(
        self,
        name: str,
        python_version: str | None = None,
        env_type: EnvType = EnvType.VENV
    ) -> EnvOperationResult:
        """Create a virtual environment.

        Args:
            name: Environment name
            python_version: Python version (e.g., "3.11")
            env_type: Type of environment to create

        Returns:
            EnvOperationResult
        """
        env_path = self.base_dir / name

        if env_path.exists():
            return EnvOperationResult(
                success=False,
                message=f"Environment '{name}' already exists",
                error="Environment exists"
            )

        try:
            if env_type == EnvType.VENV:
                result = self._create_venv(env_path, python_version)
            elif env_type == EnvType.VIRTUALENV:
                result = self._create_virtualenv(env_path, python_version)
            elif env_type == EnvType.CONDA:
                result = self._create_conda(name, python_version)
            else:
                return EnvOperationResult(
                    success=False,
                    message=f"Unsupported environment type: {env_type}",
                    error="Unsupported type"
                )

            if result.success:
                env_info = self.get_env_info(name)
                return EnvOperationResult(
                    success=True,
                    message=f"Environment '{name}' created successfully",
                    env_info=env_info.__dict__ if env_info else None
                )
            else:
                return result

        except Exception as e:
            return EnvOperationResult(
                success=False,
                message=f"Failed to create environment: {e}",
                error=str(e)
            )

    def delete_env(self, name: str) -> EnvOperationResult:
        """Delete a virtual environment.

        Args:
            name: Environment name

        Returns:
            EnvOperationResult
        """
        env_path = self.base_dir / name

        if not env_path.exists():
            return EnvOperationResult(
                success=False,
                message=f"Environment '{name}' not found",
                error="Not found"
            )

        try:
            import shutil
            shutil.rmtree(env_path)

            return EnvOperationResult(
                success=True,
                message=f"Environment '{name}' deleted successfully"
            )

        except Exception as e:
            return EnvOperationResult(
                success=False,
                message=f"Failed to delete environment: {e}",
                error=str(e)
            )

    def list_envs(self) -> list[EnvInfo]:
        """List all virtual environments.

        Returns:
            List of EnvInfo objects
        """
        envs = []

        if not self.base_dir.exists():
            return envs

        for item in self.base_dir.iterdir():
            if item.is_dir():
                env_info = self.get_env_info(item.name)
                if env_info:
                    envs.append(env_info)

        return envs

    def get_env_info(self, name: str) -> EnvInfo | None:
        """Get information about an environment.

        Args:
            name: Environment name

        Returns:
            EnvInfo or None if not found
        """
        env_path = self.base_dir / name

        if not env_path.exists():
            return None

        # Detect environment type
        env_type = self._detect_env_type(env_path)

        # Get Python version
        python_version = self._get_python_version(env_path)

        # Check if active
        status = EnvStatus.INACTIVE
        if self._is_env_active(env_path):
            status = EnvStatus.ACTIVE

        return EnvInfo(
            name=name,
            path=env_path,
            env_type=env_type,
            python_version=python_version,
            status=status
        )

    def install_package(
        self,
        env_name: str,
        package: str,
        upgrade: bool = False
    ) -> EnvOperationResult:
        """Install a package in an environment.

        Args:
            env_name: Environment name
            package: Package name (e.g., "requests" or "requests==2.28.0")
            upgrade: Whether to upgrade if already installed

        Returns:
            EnvOperationResult
        """
        env_path = self.base_dir / env_name

        if not env_path.exists():
            return EnvOperationResult(
                success=False,
                message=f"Environment '{env_name}' not found",
                error="Not found"
            )

        pip_path = self._get_pip_path(env_path)

        if not pip_path or not pip_path.exists():
            return EnvOperationResult(
                success=False,
                message="pip not found in environment",
                error="pip not found"
            )

        try:
            cmd = [str(pip_path), "install"]
            if upgrade:
                cmd.append("--upgrade")
            cmd.append(package)

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300
            )

            if result.returncode == 0:
                return EnvOperationResult(
                    success=True,
                    message=f"Package '{package}' installed successfully"
                )
            else:
                return EnvOperationResult(
                    success=False,
                    message=f"Failed to install package: {result.stderr}",
                    error=result.stderr
                )

        except Exception as e:
            return EnvOperationResult(
                success=False,
                message=f"Failed to install package: {e}",
                error=str(e)
            )

    def install_requirements(
        self,
        env_name: str,
        requirements_file: str | Path
    ) -> EnvOperationResult:
        """Install packages from requirements file.

        Args:
            env_name: Environment name
            requirements_file: Path to requirements.txt

        Returns:
            EnvOperationResult
        """
        requirements_file = Path(requirements_file)

        if not requirements_file.exists():
            return EnvOperationResult(
                success=False,
                message=f"Requirements file not found: {requirements_file}",
                error="File not found"
            )

        env_path = self.base_dir / env_name

        if not env_path.exists():
            return EnvOperationResult(
                success=False,
                message=f"Environment '{env_name}' not found",
                error="Not found"
            )

        pip_path = self._get_pip_path(env_path)

        if not pip_path:
            return EnvOperationResult(
                success=False,
                message="pip not found in environment",
                error="pip not found"
            )

        try:
            result = subprocess.run(
                [str(pip_path), "install", "-r", str(requirements_file)],
                capture_output=True,
                text=True,
                timeout=600
            )

            if result.returncode == 0:
                return EnvOperationResult(
                    success=True,
                    message="Requirements installed successfully"
                )
            else:
                return EnvOperationResult(
                    success=False,
                    message=f"Failed to install requirements: {result.stderr}",
                    error=result.stderr
                )

        except Exception as e:
            return EnvOperationResult(
                success=False,
                message=f"Failed to install requirements: {e}",
                error=str(e)
            )

    def list_packages(self, env_name: str) -> list[str]:
        """List installed packages in an environment.

        Args:
            env_name: Environment name

        Returns:
            List of package names with versions
        """
        env_path = self.base_dir / env_name

        if not env_path.exists():
            return []

        pip_path = self._get_pip_path(env_path)

        if not pip_path:
            return []

        try:
            result = subprocess.run(
                [str(pip_path), "list", "--format=freeze"],
                capture_output=True,
                text=True,
                timeout=30
            )

            if result.returncode == 0:
                return result.stdout.strip().split('\n')
            else:
                return []

        except Exception:
            return []

    def _create_venv(self, env_path: Path, python_version: str | None) -> EnvOperationResult:
        """Create venv environment."""
        python_cmd = sys.executable

        if python_version:
            # Try to find specific Python version
            python_cmd = self._find_python_executable(python_version)
            if not python_cmd:
                return EnvOperationResult(
                    success=False,
                    message=f"Python {python_version} not found",
                    error="Python version not found"
                )

        try:
            result = subprocess.run(
                [python_cmd, "-m", "venv", str(env_path)],
                capture_output=True,
                text=True,
                timeout=60
            )

            if result.returncode == 0:
                return EnvOperationResult(success=True, message="venv created")
            else:
                return EnvOperationResult(
                    success=False,
                    message=f"venv creation failed: {result.stderr}",
                    error=result.stderr
                )

        except Exception as e:
            return EnvOperationResult(
                success=False,
                message=f"venv creation failed: {e}",
                error=str(e)
            )

    def _create_virtualenv(self, env_path: Path, python_version: str | None) -> EnvOperationResult:
        """Create virtualenv environment."""
        cmd = ["virtualenv", str(env_path)]

        if python_version:
            cmd.extend(["-p", f"python{python_version}"])

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=60
            )

            if result.returncode == 0:
                return EnvOperationResult(success=True, message="virtualenv created")
            else:
                return EnvOperationResult(
                    success=False,
                    message=f"virtualenv creation failed: {result.stderr}",
                    error=result.stderr
                )

        except FileNotFoundError:
            return EnvOperationResult(
                success=False,
                message="virtualenv not installed",
                error="virtualenv not found"
            )
        except Exception as e:
            return EnvOperationResult(
                success=False,
                message=f"virtualenv creation failed: {e}",
                error=str(e)
            )

    def _create_conda(self, name: str, python_version: str | None) -> EnvOperationResult:
        """Create conda environment."""
        cmd = ["conda", "create", "-n", name, "-y"]

        if python_version:
            cmd.append(f"python={python_version}")

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120
            )

            if result.returncode == 0:
                return EnvOperationResult(success=True, message="conda env created")
            else:
                return EnvOperationResult(
                    success=False,
                    message=f"conda creation failed: {result.stderr}",
                    error=result.stderr
                )

        except FileNotFoundError:
            return EnvOperationResult(
                success=False,
                message="conda not installed",
                error="conda not found"
            )
        except Exception as e:
            return EnvOperationResult(
                success=False,
                message=f"conda creation failed: {e}",
                error=str(e)
            )

    def _detect_env_type(self, env_path: Path) -> EnvType:
        """Detect environment type."""
        if (env_path / "pyvenv.cfg").exists():
            return EnvType.VENV
        elif (env_path / "bin" / "activate").exists() or (env_path / "Scripts" / "activate").exists():
            return EnvType.VIRTUALENV
        else:
            return EnvType.VENV

    def _get_python_version(self, env_path: Path) -> str | None:
        """Get Python version in environment."""
        python_path = self._get_python_path(env_path)

        if not python_path or not python_path.exists():
            return None

        try:
            result = subprocess.run(
                [str(python_path), "--version"],
                capture_output=True,
                text=True,
                timeout=5
            )

            if result.returncode == 0:
                # Parse "Python 3.11.0" -> "3.11.0"
                return result.stdout.strip().split()[-1]
            else:
                return None

        except Exception:
            return None

    def _get_python_path(self, env_path: Path) -> Path | None:
        """Get Python executable path in environment."""
        if platform.system() == "Windows":
            python_path = env_path / "Scripts" / "python.exe"
        else:
            python_path = env_path / "bin" / "python"

        return python_path if python_path.exists() else None

    def _get_pip_path(self, env_path: Path) -> Path | None:
        """Get pip executable path in environment."""
        if platform.system() == "Windows":
            pip_path = env_path / "Scripts" / "pip.exe"
        else:
            pip_path = env_path / "bin" / "pip"

        return pip_path if pip_path.exists() else None

    def _is_env_active(self, env_path: Path) -> bool:
        """Check if environment is currently active."""
        virtual_env = os.environ.get("VIRTUAL_ENV")
        if virtual_env:
            return Path(virtual_env) == env_path
        return False

    def _find_python_executable(self, version: str) -> str | None:
        """Find Python executable for specific version."""
        # Try common Python executable names
        candidates = [
            f"python{version}",
            f"python{version.split('.')[0]}.{version.split('.')[1]}",
            f"python{version.split('.')[0]}",
        ]

        for candidate in candidates:
            try:
                result = subprocess.run(
                    [candidate, "--version"],
                    capture_output=True,
                    text=True,
                    timeout=5
                )

                if result.returncode == 0:
                    return candidate

            except FileNotFoundError:
                continue

        return None


def project_environment_tool_executor(params: dict[str, Any]) -> dict[str, Any]:
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
    env_info = manager.get_env_info(env_name)
    python_executable = _venv_python_path(env_path)
    pip_executable = _venv_pip_path(env_path)
    run_command = _venv_run_command(project_path, entry_files + written_files, params.get("run_command"))
    setup_commands = _venv_setup_commands(env_name, detected_packages, dependency_source)
    payload = {
        "project_path": str(project_path),
        "venv_path": str(env_path),
        "env_name": env_name,
        "python_executable": str(python_executable),
        "pip_executable": str(pip_executable),
        "python_version": getattr(env_info, "python_version", None) or "",
        "detected_packages": detected_packages,
        "installed_packages": packages,
        "dependency_source": dependency_source,
        "setup_commands": setup_commands,
        "run_command": run_command,
        "operations": operations,
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
        packages.append(THIRD_PARTY_IMPORT_MAP.get(import_name, import_name))
    return sorted(set(packages), key=str.lower)


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
                metadata=payload,
            )
        )
    except Exception:
        pass
