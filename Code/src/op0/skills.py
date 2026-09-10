"""Agent Skills: directory discovery + one-line index for the contract.

Implements the Agent Skills open standard's loading model (three-level
progressive disclosure): the pinned contract carries only `name:
description` per skill; the body is read on demand via openpilot_read;
bundled scripts run via openpilot_bash, which the sandbox walls in. The
project level overrides the user level - conventions of the project at
hand beat personal defaults.
"""

from __future__ import annotations

from pathlib import Path


def _skill_dirs(project_root: str) -> tuple[Path, ...]:
    root = Path(project_root).expanduser().resolve(strict=False)
    return (root / ".openpilot" / "skills", Path.home() / ".openpilot" / "skills")


def _frontmatter(path: Path) -> tuple[str, str]:
    """Parse the `---` YAML block's name/description lines. The standard
    fields are flat scalars, so a line parser avoids a yaml dependency;
    a skill with no frontmatter is skipped (not installed)."""
    name = description = ""
    inside = False
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        if line.strip() == "---":
            if inside:
                break
            inside = True
            continue
        if inside and line.startswith("name:"):
            name = line.split(":", 1)[1].strip()
        elif inside and line.startswith("description:"):
            description = line.split(":", 1)[1].strip()
    return name, description


def discover(project_root: str) -> list[tuple[str, str, Path]]:
    """Installed skills as (name, description, SKILL.md path); project
    entries shadow same-named user entries."""
    found: dict[str, tuple[str, Path]] = {}
    for directory in reversed(_skill_dirs(project_root)):
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob("*/SKILL.md")):
            name, description = _frontmatter(path)
            if name:
                found[name] = (description, path)
    return [(name, text, path) for name, (text, path) in sorted(found.items())]


def index_block(project_root: str) -> str:
    """The contract segment: one line per skill with its body path, so the
    model can read the SKILL.md on demand without guessing locations."""
    skills = discover(project_root)
    if not skills:
        return ""
    lines = [f"- {name}: {text} (body: {path})" for name, text, path in skills]
    return (
        "Installed skills — when the task matches one, read its body first "
        "with openpilot_read and follow it:\n" + "\n".join(lines)
    )
