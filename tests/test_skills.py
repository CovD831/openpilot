"""Skills: discovery, index injection, and the read-only carve-out."""

from __future__ import annotations

from pathlib import Path

from op0 import skills
from op0.bridge import ReadOnlyToolBridge
from op0.engine import compose_turn_message

BODY = """---
name: greeting
description: Forces the AHOY greeting protocol. Use when asked to greet anyone.
---

## Instructions
Every greeting MUST start with the word AHOY.
"""


def _install(root: Path, name: str, body: str) -> Path:
    directory = root / ".openpilot" / "skills" / name
    directory.mkdir(parents=True)
    path = directory / "SKILL.md"
    path.write_text(body, encoding="utf-8")
    return path


def test_discover_reads_frontmatter(tmp_path: Path) -> None:
    _install(tmp_path, "greeting", BODY)
    found = skills.discover(str(tmp_path))
    assert len(found) == 1
    name, description, path = found[0]
    assert name == "greeting"
    assert description.startswith("Forces the AHOY")
    assert path.name == "SKILL.md"


def test_project_overrides_user(tmp_path: Path, monkeypatch) -> None:
    _install(tmp_path, "greeting", BODY)
    user_dir = Path.home() / ".openpilot" / "skills" / "greeting"
    user_dir.mkdir(parents=True, exist_ok=True)
    (user_dir / "SKILL.md").write_text(
        "---\nname: greeting\ndescription: USER LEVEL\n---\nbody\n", encoding="utf-8"
    )
    try:
        found = skills.discover(str(tmp_path))
        assert len(found) == 1 and found[0][1].startswith("Forces the AHOY")
    finally:
        (user_dir / "SKILL.md").unlink()
        user_dir.rmdir()


def test_index_block_format_and_empty(tmp_path: Path) -> None:
    assert skills.index_block(str(tmp_path)) == ""
    _install(tmp_path, "greeting", BODY)
    block = skills.index_block(str(tmp_path))
    assert block.startswith("Installed skills")
    assert "- greeting: Forces the AHOY" in block
    assert "SKILL.md" in block  # body path present for on-demand reads


def test_compose_carries_skills(tmp_path: Path) -> None:
    message = compose_turn_message("hi", skills="SKILL-LINE")
    assert "SKILL-LINE" in message and "Context from earlier turns" not in message
    folded = compose_turn_message("hi", context="proj", skills="SKILL-LINE")
    assert folded.index("SKILL-LINE") < folded.index("Context from earlier turns")


def test_bridge_read_passes_write_denied_for_skill_dirs(tmp_path: Path) -> None:
    _install(tmp_path, "greeting", BODY)
    body_path = tmp_path / ".openpilot" / "skills" / "greeting" / "SKILL.md"
    bridge = ReadOnlyToolBridge((str(tmp_path),))
    read = bridge._handle(
        {"toolName": "openpilot_read", "toolCallId": "aaaaaaaa-0000-4000-8000-00000000sk01",
         "args": {"path": str(body_path)}}
    )
    assert read["success"] is True and "AHOY" in read["content"]  # outside scope, still readable
    write = bridge._handle(
        {"toolName": "openpilot_write", "toolCallId": "aaaaaaaa-0000-4000-8000-00000000sk02",
         "args": {"path": str(body_path), "content": "tampered"}}
    )
    assert write["success"] is False  # the model must not edit its own instructions
    assert "AHOY" in body_path.read_text(encoding="utf-8")
