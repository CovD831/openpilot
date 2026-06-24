from __future__ import annotations

import json
from pathlib import Path

from memory.context_builder import MemoryContextBuilder
from memory.memory_models import MemoryRecord, MemoryType
from memory.memory_store import MemoryStore
from memory.project_manager import ProjectManager
from memory.short_memory import ShortMemory
from memory.tool.memory_context_tool import memory_context_executor
from metadata import ToolInputMetadata


def test_project_manager_updates_sketch_and_searches_by_content(tmp_path) -> None:
    project = tmp_path / "demo"
    project.mkdir()
    source = project / "app.py"
    source.write_text(
        "def render_dashboard():\n    return 'pineapple project dashboard'\n",
        encoding="utf-8",
    )

    manager = ProjectManager(project)
    update_result = manager.update(project)
    results = manager.search("pineapple dashboard")

    sketch = project / "sketch.json"
    assert sketch.exists()
    sketch_payload = json.loads(sketch.read_text(encoding="utf-8"))
    assert "app.py" in sketch_payload["files"]
    assert "function_description" in sketch_payload["files"]["app.py"]
    assert "semantic_info" in sketch_payload["files"]["app.py"]
    content_index = sketch_payload["files"]["app.py"]["content_index"]
    assert content_index["language"] == "python"
    assert content_index["sections"][0]["title"] == "function render_dashboard"
    assert content_index["sections"][0]["line_start"] == 1
    assert content_index["sections"][0]["line_end"] == 2
    index_file = content_index["index_file"]
    index_payload = json.loads(Path(index_file).read_text(encoding="utf-8"))
    assert index_payload["kind"] == "file_content_index"
    assert index_payload["relative_path"] == "app.py"
    assert index_payload["sections"][0]["embedding"]
    assert update_result["file_count"] == 1
    assert results[0]["name"] == "app.py"
    assert "pineapple project dashboard" in results[0]["description"]


def test_memory_context_builder_combines_dialog_memory_files_and_environment(tmp_path) -> None:
    project = tmp_path / "demo"
    project.mkdir()
    (project / "game.py").write_text("import pygame\n# arcade scene loop\n", encoding="utf-8")

    store = MemoryStore(tmp_path / "memory")
    store.save(
        MemoryRecord(
            id="project-memory",
            memory_type=MemoryType.PROJECT,
            content="The project should prioritize pygame arcade polish.",
            tags=["pygame", "arcade"],
            confidence=0.9,
        )
    )
    store.save(
        MemoryRecord(
            id="env-memory",
            memory_type=MemoryType.SHORT_TERM,
            content="Project environment for demo: pygame installed.",
            tags=["project_environment", "demo", "pygame"],
            confidence=0.95,
        )
    )
    short_memory = ShortMemory(repo_path=tmp_path)
    short_memory.add_message("user", "保持用户原话，不要改写。")
    short_memory.add_message("assistant", "Compressed assistant note.")
    builder = MemoryContextBuilder(
        short_memory=short_memory,
        memory_store=store,
        project_manager=ProjectManager(project),
    )

    context = builder.build(
        "pygame arcade",
        project_path=project,
        limit=5,
        system_prompt="Fixed autonomous iteration prompt.",
    )

    assert context["system_prompt"] == "Fixed autonomous iteration prompt."
    assert context["dialog_context"][0]["content"] == "保持用户原话，不要改写。"
    assert context["related_memories"][0]["id"] == "project-memory"
    assert context["related_files"][0]["name"] == "game.py"
    assert context["environment_context"][0]["id"] == "env-memory"
    prompt_text = context["prompt_text"]
    assert prompt_text.startswith("## System Prompt\nFixed autonomous iteration prompt.")
    assert prompt_text.index("## System Prompt") < prompt_text.index("## Dialog Context")
    assert prompt_text.index("## Dialog Context") < prompt_text.index("## Related Files")
    assert prompt_text.index("## Related Files") < prompt_text.index("## Related Memories")
    assert prompt_text.index("## Related Memories") < prompt_text.index("## Environment Context")
    assert "pygame arcade polish" in context["prompt_text"]


def test_memory_context_tool_returns_stable_context_without_llm(tmp_path) -> None:
    project = tmp_path / "demo"
    project.mkdir()
    (project / "README.md").write_text("Pygame arcade demo", encoding="utf-8")
    store = MemoryStore(tmp_path / "memory")
    store.save(
        MemoryRecord(
            id="memory-1",
            memory_type=MemoryType.PROJECT,
            content="Remember pygame demo requirements.",
            tags=["pygame"],
            confidence=0.8,
        )
    )
    short_memory = ShortMemory(repo_path=tmp_path)
    short_memory.add_message("user", "Build a pygame demo.")

    result = memory_context_executor(
        ToolInputMetadata.from_mapping("memory_context", {
            "query": "pygame demo",
            "project_path": str(project),
            "_memory_store": store,
            "_short_memory": short_memory,
            "_project_manager": ProjectManager(project),
            "system_prompt": "Tool caller fixed prompt.",
        })
    )

    assert result["system_prompt"] == "Tool caller fixed prompt."
    assert result["dialog_context"][0]["content"] == "Build a pygame demo."
    assert result["related_memories"][0]["id"] == "memory-1"
    assert result["related_files"][0]["name"] == "README.md"
    assert result["prompt_text"].startswith("## System Prompt\nTool caller fixed prompt.")
    assert "## Related Files" in result["prompt_text"]
