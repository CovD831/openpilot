from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from agents.evaluation_models import EvaluationResult
from agents.project_evaluator import ProjectEvaluatorAgent
from execution.intelligent_autopilot import IntelligentAutopilot
from memory.memory_store import MemoryStore
from memory.memory_models import MemoryRecord, MemoryType
from tools.env_tools import EnvOperationResult, infer_project_dependencies, project_environment_tool_executor
from tools.project_improvement_tool import project_state_reader_executor


class FakeEnvironmentManager:
    def __init__(self, base_dir: Path, fail_install: bool = False):
        self.base_dir = Path(base_dir)
        self.fail_install = fail_install
        self.installed: list[str] = []
        self.installed_requirements = False

    def create_env(self, name: str):
        env = self.base_dir / name
        (env / "bin").mkdir(parents=True, exist_ok=True)
        (env / "bin" / "python").write_text("# fake python\n", encoding="utf-8")
        (env / "bin" / "pip").write_text("# fake pip\n", encoding="utf-8")
        return EnvOperationResult(success=True, message="created")

    def install_package(self, env_name: str, package: str, upgrade: bool = False):
        if self.fail_install:
            return EnvOperationResult(success=False, message="failed", error=f"cannot install {package}")
        self.installed.append(package)
        return EnvOperationResult(success=True, message="installed")

    def install_requirements(self, env_name: str, requirements_file: str | Path):
        if self.fail_install:
            return EnvOperationResult(success=False, message="failed", error="requirements failed")
        self.installed_requirements = True
        return EnvOperationResult(success=True, message="requirements installed")

    def list_packages(self, env_name: str):
        return [f"{package}==1.0" for package in self.installed]

    def get_env_info(self, env_name: str):
        return SimpleNamespace(python_version="3.13.0")


class ProjectEnvironmentTests(unittest.TestCase):
    def test_import_scan_excludes_stdlib_and_local_modules(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            (project / "helper.py").write_text("VALUE = 1\n", encoding="utf-8")
            main = project / "main.py"
            main.write_text(
                "import sys\nimport random\nimport pygame\nimport cv2\nimport helper\nfrom PIL import Image\n",
                encoding="utf-8",
            )

            packages = infer_project_dependencies(project, [str(main)])

        self.assertEqual(packages, ["opencv-python", "Pillow", "pygame"])

    def test_project_environment_tool_creates_venv_installs_and_saves_memory(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            main = project / "main.py"
            main.write_text("import pygame\n", encoding="utf-8")
            memory = MemoryStore(project / "memory")
            manager = FakeEnvironmentManager(project)

            result = project_environment_tool_executor(
                {
                    "project_path": str(project),
                    "written_files": [str(main)],
                    "entry_files": [str(main)],
                    "run_command": "python main.py",
                    "_environment_manager": manager,
                    "_memory_store": memory,
                }
            )

            short_memories = memory.load_all(MemoryType.SHORT_TERM)

        self.assertEqual(result["detected_packages"], ["pygame"])
        self.assertEqual(manager.installed, ["pygame"])
        self.assertEqual(result["run_command"], ".venv/bin/python main.py")
        self.assertTrue(any("project_environment" in item.tags for item in short_memories))

    def test_requirements_file_takes_precedence_over_import_scan(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            main = project / "main.py"
            main.write_text("import pygame\n", encoding="utf-8")
            (project / "requirements.txt").write_text("requests==2.32.0\n", encoding="utf-8")
            manager = FakeEnvironmentManager(project)

            result = project_environment_tool_executor(
                {
                    "project_path": str(project),
                    "written_files": [str(main)],
                    "_environment_manager": manager,
                }
            )

        self.assertEqual(result["dependency_source"], "requirements.txt")
        self.assertEqual(result["detected_packages"], ["requests==2.32.0"])
        self.assertTrue(manager.installed_requirements)
        self.assertEqual(manager.installed, [])

    def test_environment_install_failure_is_structured_iteration_failure(self):
        autopilot = object.__new__(IntelligentAutopilot)
        autopilot.enable_iterative_improvement = True
        autopilot.required_successful_improvements = 1
        autopilot.max_iteration_attempts = 1
        autopilot.prompt_for_project_improvement_iterations = False
        autopilot._project_improvement_iterations_prompted = False
        autopilot.enhanced_ui = None
        autopilot.memory_store = None

        def sync_failure(**kwargs):
            return {
                "tool": "project_environment_tool",
                "success": False,
                "error": "cannot install pygame",
            }

        autopilot._sync_project_environment = sync_failure
        autopilot._resolve_project_improvement_iterations = lambda goal, project_path: True

        result = autopilot._run_iterative_improvement(
            goal="make snake",
            project_path=Path("/tmp/project"),
            written_files=["/tmp/project/main.py"],
            run_command="python main.py",
        )

        self.assertFalse(result["success"])
        self.assertEqual(result["failure_stage"], "Environment Setup")
        self.assertEqual(result["failed_tool"], "project_environment_tool")
        self.assertIn("cannot install pygame", result["failure_reason"])

    def test_project_state_reader_returns_environment_short_term_memory(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "Snake"
            project.mkdir()
            main = project / "main.py"
            main.write_text("print('ok')\n", encoding="utf-8")
            memory = MemoryStore(Path(tmp) / "memory")
            memory.save(
                MemoryRecord(
                    id="env",
                    memory_type=MemoryType.SHORT_TERM,
                    content=f"Project environment for {project}: packages=['pygame']",
                    tags=["project_environment", "Snake", "pygame"],
                    confidence=0.9,
                    metadata={"detected_packages": ["pygame"]},
                )
            )

            state = project_state_reader_executor(
                {
                    "project_path": str(project),
                    "written_files": [str(main)],
                    "memory_query": "unrelated query",
                    "_memory_store": memory,
                }
            )

        self.assertTrue(any("project_environment" in record["tags"] for record in state["memory_records"]))

    def test_evaluator_prefers_project_venv_python_for_python_commands(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            (project / ".venv" / "bin").mkdir(parents=True)
            fake_python = project / ".venv" / "bin" / "python"
            fake_python.write_text("", encoding="utf-8")
            evaluator = ProjectEvaluatorAgent()

            args = evaluator._normalize_python_args(project, ["python", "main.py"])

        self.assertEqual(args[0], str(fake_python))


if __name__ == "__main__":
    unittest.main()
