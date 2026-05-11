"""Environment management tools for virtual environments."""

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
