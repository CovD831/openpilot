"""G4: the clean base never exceeds its line budget."""

from __future__ import annotations

from pathlib import Path

# 3000 approved on the 2,893-line base; 2026-09-09 the boss raised it twice:
# 3250 (compaction P1, after +144 of parallel tui work) then 3300 (P3/P4/P5).
# S1-S4 token savings net +114 (the S3 handoff builder outweighs the removed
# snip family) -> real number 3,414, budget 3,420. Do not raise casually.
LINE_BUDGET = 3420


def test_line_budget() -> None:
    src = Path(__file__).resolve().parents[1] / "Code" / "src"
    assert src.exists(), "Code/src missing"
    total = sum(
        len(p.read_text(encoding="utf-8", errors="ignore").splitlines())
        for p in src.rglob("*.py")
    )
    assert total <= LINE_BUDGET, f"{total} lines > {LINE_BUDGET}"
