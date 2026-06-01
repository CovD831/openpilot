from __future__ import annotations

import shutil
from types import SimpleNamespace

from memory.agents.virtual_environment_manager import (
    EnvOperationResult,
    EnvironmentManager as MemoryEnvironmentManager,
    VirtualEnvironmentManager,
)
from memory.agents.project_environment_tool import (
    EnvironmentManager,
    infer_project_dependencies,
    project_environment_tool_executor,
)
from metadata import ToolInputMetadata


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
        ToolInputMetadata.from_mapping("project_environment_tool", {
            "project_path": str(project),
            "written_files": ["app.py"],
            "install": True,
            "_environment_manager": fake_manager,
        })
    )

    assert result["env_name"] == ".venv"
    assert result["detected_packages"] == ["pygame"]
    assert fake_manager.created == [".venv"]
    assert fake_manager.installed_packages == [(".venv", "pygame")]
    assert not (project / ".venv").exists()
    assert result.result.command_cwd == str(project)
    assert result.result.python_command.endswith(".venv/bin/python")
    assert result.result.pip_command.endswith(".venv/bin/pip")
    assert result.result.command_env["VIRTUAL_ENV"].endswith(".venv")
    assert str(project / ".venv" / "bin") in result.result.command_env["PATH"]
    assert result.result.dependencies[0].package_name == "pygame"
    assert result.result.dependencies[0].import_names == ["pygame"]
    assert "pygame" in result.result.dependency_strategy.preserve_packages
    if shutil.which("git"):
        assert result.result.git_repository is not None
        assert result.result.git_repository.initialized is True
        assert result.result.git_snapshot is not None
        assert ".venv/" in (project / ".gitignore").read_text(encoding="utf-8")
    else:
        assert any("Git safety unavailable" in warning for warning in result.result.warnings)


def test_project_environment_tool_maps_import_name_to_published_distribution(tmp_path) -> None:
    app = tmp_path / "assistant.py"
    app.write_text("import speech_recognition\nimport pyttsx3\n", encoding="utf-8")

    detected = infer_project_dependencies(tmp_path, ["assistant.py"])

    assert detected == ["pyttsx3", "SpeechRecognition"]
