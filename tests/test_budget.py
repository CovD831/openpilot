"""G4: the clean base never exceeds its line budget."""

from __future__ import annotations

from pathlib import Path

LINE_BUDGET = 2000


def test_line_budget() -> None:
    src = Path(__file__).resolve().parents[1] / "Code" / "src"
    assert src.exists(), "Code/src missing"
    total = sum(
        len(p.read_text(encoding="utf-8", errors="ignore").splitlines())
        for p in src.rglob("*.py")
    )
    assert total <= LINE_BUDGET, f"{total} lines > {LINE_BUDGET}"
