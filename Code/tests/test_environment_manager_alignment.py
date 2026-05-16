from __future__ import annotations

from types import SimpleNamespace

from memory.agents.virtual_environment_manager import (
    EnvOperationResult,
    EnvironmentManager as MemoryEnvironmentManager,
    VirtualEnvironmentManager,
)
from tools.env_tools import EnvironmentManager, project_environment_tool_executor


class FakeEnvironmentManager:
    def __init__(self) -> None:
        self.created = []
        self.installed_packages = []

    def create_env(self, env_name):
        self.created.append(env_name)
        return EnvOperationResult(success=True, message="created")

    def install_package(self, env_name, package):
        self.installed_packages.append((env_name, package))
        return EnvOperationResult(success=True, message=f"installed {package}")

    def install_requirements(self, env_name, requirements_file):
        return EnvOperationResult(success=True, message="requirements installed")

    def list_packages(self, env_name):
        return [f"{package}==1.0" for _, package in self.installed_packages]

    def get_env_info(self, env_name):
        return SimpleNamespace(python_version="3.13.0")


def test_virtual_environment_manager_agent_exposes_instruction_functions(tmp_path) -> None:
    (tmp_path / "requirements.txt").write_text("rich\n", encoding="utf-8")
    manager = VirtualEnvironmentManager(tmp_path)

    creator = manager.environment_creator()
    installer = manager.packet_installer(["rich"])
    context = manager.get_environment_context()

    assert creator["commands"] == ["python -m venv .venv"]
    assert installer["commands"] == [".venv/bin/pip install rich"]
    assert context["packages"] == ["rich"]
    assert ".venv/bin/python" == context["python_executable"]


def test_env_tools_environment_manager_is_memory_manager_alias() -> None:
    assert EnvironmentManager is MemoryEnvironmentManager


def test_project_environment_tool_uses_injected_manager_without_real_venv(tmp_path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "app.py").write_text("import pygame\nprint('ok')\n", encoding="utf-8")
    fake_manager = FakeEnvironmentManager()

    result = project_environment_tool_executor(
        {
            "project_path": str(project),
            "written_files": ["app.py"],
            "install": True,
            "_environment_manager": fake_manager,
        }
    )

    assert result["env_name"] == ".venv"
    assert result["detected_packages"] == ["pygame"]
    assert fake_manager.created == [".venv"]
    assert fake_manager.installed_packages == [(".venv", "pygame")]
    assert not (project / ".venv").exists()
