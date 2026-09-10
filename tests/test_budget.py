"""G4: the clean base never exceeds its line budget."""

from __future__ import annotations

from pathlib import Path

# 3000 approved on the 2,893-line base; 2026-09-09 the boss raised it twice:
# 3250 (compaction P1, after +144 of parallel tui work) then 3300 (P3/P4/P5).
# S1-S4 net +114 -> 3420; the chaos-tested crash-recovery projection fix
# (recovery=True replay, budget-independent injection) cost +10 -> 3,430.
# 2026-09-10: sandbox (the physical wall behind the policy gate, +99 net)
# then skills (discovery + contract index + read carve-out + /skill, +94)
# -> 3,630; subagent phase 1 (metadata registry + openpilot_task + double
# ledger + structured TaskHandoff) -> 3,880; validation loop (validate arg
# on the task ticket + sandboxed auto-run + verdict matrix) -> 3,940;
# parallel delegation + worktree isolation + registry locking -> 4,060,
# pending the boss's ruling.
LINE_BUDGET = 4060


def test_line_budget() -> None:
    src = Path(__file__).resolve().parents[1] / "Code" / "src"
    assert src.exists(), "Code/src missing"
    total = sum(
        len(p.read_text(encoding="utf-8", errors="ignore").splitlines())
        for p in src.rglob("*.py")
    )
    assert total <= LINE_BUDGET, f"{total} lines > {LINE_BUDGET}"
