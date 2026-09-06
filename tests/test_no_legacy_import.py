"""G5: no legacy-tree imports may ever enter the clean base."""

from __future__ import annotations

import ast
from pathlib import Path

LEGACY_TOPS = frozenset(
    {
        "autonomous_iteration",
        "metadata",
        "tools",
        "memory",
        "core",
        "evidence_core",
        "ui",
        "utils",
    }
)


def test_no_legacy_import() -> None:
    src = Path(__file__).resolve().parents[1] / "Code" / "src"
    assert src.exists(), "Code/src missing"
    offenders: list[str] = []
    for pyfile in sorted(src.rglob("*.py")):
        try:
            tree = ast.parse(pyfile.read_text(encoding="utf-8", errors="ignore"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                modules = [node.module or ""]
            else:
                continue
            for module in modules:
                top = (module or "").split(".")[0]
                if top in LEGACY_TOPS:
                    offenders.append(f"{pyfile.relative_to(src)}: {module}")
    assert not offenders, f"legacy imports entered the clean base: {offenders}"
