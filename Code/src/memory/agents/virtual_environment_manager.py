"""Virtual Environment Manager agent facade."""

from __future__ import annotations

import os
import platform
import subprocess
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel


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


class EnvironmentManager:
    """Manager for project virtual environments."""

    def __init__(self, base_dir: str | Path = ".venvs") -> None:
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def create_env(
        self,
        name: str,
        python_version: str | None = None,
        env_type: EnvType = EnvType.VENV,
    ) -> EnvOperationResult:
        """Create a virtual environment."""
        env_path = self.base_dir / name
        if env_path.exists():
            return EnvOperationResult(
                success=False,
                message=f"Environment '{name}' already exists",
                error="Environment exists",
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
                    error="Unsupported type",
                )

            if not result.success:
                return result
            env_info = self.get_env_info(name)
            return EnvOperationResult(
                success=True,
                message=f"Environment '{name}' created successfully",
                env_info=env_info.__dict__ if env_info else None,
            )
        except Exception as exc:
            return EnvOperationResult(
                success=False,
                message=f"Failed to create environment: {exc}",
                error=str(exc),
            )

    def delete_env(self, name: str) -> EnvOperationResult:
        """Delete a virtual environment."""
        env_path = self.base_dir / name
        if not env_path.exists():
            return EnvOperationResult(
                success=False,
                message=f"Environment '{name}' not found",
                error="Not found",
            )
        try:
            import shutil

            shutil.rmtree(env_path)
            return EnvOperationResult(success=True, message=f"Environment '{name}' deleted successfully")
        except Exception as exc:
            return EnvOperationResult(
                success=False,
                message=f"Failed to delete environment: {exc}",
                error=str(exc),
            )

    def list_envs(self) -> list[EnvInfo]:
        """List all virtual environments."""
        if not self.base_dir.exists():
            return []
        envs = []
        for item in self.base_dir.iterdir():
            if item.is_dir():
                env_info = self.get_env_info(item.name)
                if env_info:
                    envs.append(env_info)
        return envs

    def get_env_info(self, name: str) -> EnvInfo | None:
        """Get information about an environment."""
        env_path = self.base_dir / name
        if not env_path.exists():
            return None
        return EnvInfo(
            name=name,
            path=env_path,
            env_type=self._detect_env_type(env_path),
            python_version=self._get_python_version(env_path),
            status=EnvStatus.ACTIVE if self._is_env_active(env_path) else EnvStatus.INACTIVE,
        )

    def install_package(self, env_name: str, package: str, upgrade: bool = False) -> EnvOperationResult:
        """Install a package in an environment."""
        env_path = self.base_dir / env_name
        if not env_path.exists():
            return EnvOperationResult(success=False, message=f"Environment '{env_name}' not found", error="Not found")
        pip_path = self._get_pip_path(env_path)
        if not pip_path or not pip_path.exists():
            return EnvOperationResult(success=False, message="pip not found in environment", error="pip not found")

        try:
            cmd = [str(pip_path), "install"]
            if upgrade:
                cmd.append("--upgrade")
            cmd.append(package)
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            if result.returncode == 0:
                return EnvOperationResult(success=True, message=f"Package '{package}' installed successfully")
            return EnvOperationResult(
                success=False,
                message=f"Failed to install package: {result.stderr}",
                error=result.stderr,
            )
        except Exception as exc:
            return EnvOperationResult(success=False, message=f"Failed to install package: {exc}", error=str(exc))

    def install_requirements(self, env_name: str, requirements_file: str | Path) -> EnvOperationResult:
        """Install packages from requirements file."""
        requirements_file = Path(requirements_file)
        if not requirements_file.exists():
            return EnvOperationResult(
                success=False,
                message=f"Requirements file not found: {requirements_file}",
                error="File not found",
            )
        env_path = self.base_dir / env_name
        if not env_path.exists():
            return EnvOperationResult(success=False, message=f"Environment '{env_name}' not found", error="Not found")
        pip_path = self._get_pip_path(env_path)
        if not pip_path:
            return EnvOperationResult(success=False, message="pip not found in environment", error="pip not found")

        try:
            result = subprocess.run(
                [str(pip_path), "install", "-r", str(requirements_file)],
                capture_output=True,
                text=True,
                timeout=600,
            )
            if result.returncode == 0:
                return EnvOperationResult(success=True, message="Requirements installed successfully")
            return EnvOperationResult(
                success=False,
                message=f"Failed to install requirements: {result.stderr}",
                error=result.stderr,
            )
        except Exception as exc:
            return EnvOperationResult(success=False, message=f"Failed to install requirements: {exc}", error=str(exc))

    def list_packages(self, env_name: str) -> list[str]:
        """List installed packages in an environment."""
        env_path = self.base_dir / env_name
        if not env_path.exists():
            return []
        pip_path = self._get_pip_path(env_path)
        if not pip_path:
            return []
        try:
            result = subprocess.run([str(pip_path), "list", "--format=freeze"], capture_output=True, text=True, timeout=30)
            if result.returncode == 0:
                return result.stdout.strip().split("\n")
            return []
        except Exception:
            return []

    def _create_venv(self, env_path: Path, python_version: str | None) -> EnvOperationResult:
        python_cmd = sys.executable
        if python_version:
            python_cmd = self._find_python_executable(python_version)
            if not python_cmd:
                return EnvOperationResult(
                    success=False,
                    message=f"Python {python_version} not found",
                    error="Python version not found",
                )
        try:
            result = subprocess.run([python_cmd, "-m", "venv", str(env_path)], capture_output=True, text=True, timeout=60)
            if result.returncode == 0:
                return EnvOperationResult(success=True, message="venv created")
            return EnvOperationResult(success=False, message=f"venv creation failed: {result.stderr}", error=result.stderr)
        except Exception as exc:
            return EnvOperationResult(success=False, message=f"venv creation failed: {exc}", error=str(exc))

    def _create_virtualenv(self, env_path: Path, python_version: str | None) -> EnvOperationResult:
        cmd = ["virtualenv", str(env_path)]
        if python_version:
            cmd.extend(["-p", f"python{python_version}"])
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            if result.returncode == 0:
                return EnvOperationResult(success=True, message="virtualenv created")
            return EnvOperationResult(
                success=False,
                message=f"virtualenv creation failed: {result.stderr}",
                error=result.stderr,
            )
        except FileNotFoundError:
            return EnvOperationResult(success=False, message="virtualenv not installed", error="virtualenv not found")
        except Exception as exc:
            return EnvOperationResult(success=False, message=f"virtualenv creation failed: {exc}", error=str(exc))

    def _create_conda(self, name: str, python_version: str | None) -> EnvOperationResult:
        cmd = ["conda", "create", "-n", name, "-y"]
        if python_version:
            cmd.append(f"python={python_version}")
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            if result.returncode == 0:
                return EnvOperationResult(success=True, message="conda env created")
            return EnvOperationResult(success=False, message=f"conda creation failed: {result.stderr}", error=result.stderr)
        except FileNotFoundError:
            return EnvOperationResult(success=False, message="conda not installed", error="conda not found")
        except Exception as exc:
            return EnvOperationResult(success=False, message=f"conda creation failed: {exc}", error=str(exc))

    def _detect_env_type(self, env_path: Path) -> EnvType:
        if (env_path / "pyvenv.cfg").exists():
            return EnvType.VENV
        if (env_path / "bin" / "activate").exists() or (env_path / "Scripts" / "activate").exists():
            return EnvType.VIRTUALENV
        return EnvType.VENV

    def _get_python_version(self, env_path: Path) -> str | None:
        python_path = self._get_python_path(env_path)
        if not python_path or not python_path.exists():
            return None
        try:
            result = subprocess.run([str(python_path), "--version"], capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                return result.stdout.strip().split()[-1]
            return None
        except Exception:
            return None

    def _get_python_path(self, env_path: Path) -> Path | None:
        python_path = env_path / ("Scripts/python.exe" if platform.system() == "Windows" else "bin/python")
        return python_path if python_path.exists() else None

    def _get_pip_path(self, env_path: Path) -> Path | None:
        pip_path = env_path / ("Scripts/pip.exe" if platform.system() == "Windows" else "bin/pip")
        return pip_path if pip_path.exists() else None

    def _is_env_active(self, env_path: Path) -> bool:
        virtual_env = os.environ.get("VIRTUAL_ENV")
        return Path(virtual_env) == env_path if virtual_env else False

    def _find_python_executable(self, version: str) -> str | None:
        candidates = [
            f"python{version}",
            f"python{version.split('.')[0]}.{version.split('.')[1]}",
            f"python{version.split('.')[0]}",
        ]
        for candidate in candidates:
            try:
                result = subprocess.run([candidate, "--version"], capture_output=True, text=True, timeout=5)
                if result.returncode == 0:
                    return candidate
            except FileNotFoundError:
                continue
        return None


class VirtualEnvironmentManager:
    """Return environment setup commands and context without creating envs."""

    def __init__(self, project_path: str | Path = ".") -> None:
        self.project_path = Path(project_path).expanduser()

    def environment_creator(self, env_name: str = ".venv") -> dict[str, Any]:
        """Return commands to create a project-local virtual environment."""
        return {
            "project_path": str(self.project_path),
            "env_name": env_name,
            "commands": [f"python -m venv {env_name}"],
        }

    def packet_installer(self, packet_names: list[str], env_name: str = ".venv") -> dict[str, Any]:
        """Return package installation commands."""
        pip_bin = self._pip_bin(env_name)
        command = f"{pip_bin} install {' '.join(packet_names)}" if packet_names else ""
        return {
            "project_path": str(self.project_path),
            "env_name": env_name,
            "packet_names": packet_names,
            "commands": [command] if command else [],
        }

    def get_environment_context(
        self,
        env_name: str = ".venv",
        package_names: list[str] | None = None,
    ) -> dict[str, Any]:
        """Return virtual environment context."""
        package_names = package_names if package_names is not None else self._read_requirements()
        creator = self.environment_creator(env_name)
        installer = self.packet_installer(package_names, env_name)
        return {
            "project_path": str(self.project_path),
            "env_name": env_name,
            "python_executable": self._python_bin(env_name),
            "pip_executable": self._pip_bin(env_name),
            "packages": package_names,
            "setup_commands": creator["commands"] + installer["commands"],
        }

    def _read_requirements(self) -> list[str]:
        requirements = self.project_path / "requirements.txt"
        if not requirements.exists():
            return []
        packages = []
        for line in requirements.read_text(encoding="utf-8").splitlines():
            item = line.strip()
            if item and not item.startswith("#"):
                packages.append(item)
        return packages

    def _python_bin(self, env_name: str) -> str:
        return f"{env_name}/Scripts/python.exe" if platform.system() == "Windows" else f"{env_name}/bin/python"

    def _pip_bin(self, env_name: str) -> str:
        return f"{env_name}/Scripts/pip.exe" if platform.system() == "Windows" else f"{env_name}/bin/pip"
