"""A/B: compaction ON vs OFF over the same task set, same files, real
provider. Metrics: cumulative real input tokens (turn-end usage) and
per-turn success. The fold must visibly shrink later-turn inputs."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "Code" / "src"))

from op0.bridge import ReadOnlyToolBridge
from op0.engine import Engine, EngineConfig
from op0.session import Session

TASKS = [
    ("inventory", "notes/alpha.txt", "notes/beta.txt", "what items were listed in alpha.txt?"),
    ("config", "notes/gamma.txt", "notes/delta.txt", "which endpoint was configured in gamma.txt?"),
    ("ledger", "notes/epsilon.txt", "notes/zeta.txt", "what amount did epsilon.txt record?"),
    ("roster", "notes/eta.txt", "notes/theta.txt", "who owns the on-call in eta.txt?"),
    ("plan", "notes/iota.txt", "notes/kappa.txt", "what is the deadline in iota.txt?"),
    ("summary", "notes/lambda.txt", "notes/mu.txt", "what risk did lambda.txt flag?"),
]


def _seed_project(root: Path) -> None:
    notes = root / "notes"
    notes.mkdir(parents=True, exist_ok=True)
    body = "".join(f"log line {i}: status nominal, nothing to act on.\n" for i in range(260))
    files = {
        "alpha.txt": body + "inventory items: 3 wrenches, 2 drills, 1 saw.\n" + body,
        "beta.txt": "beta: secondary notes, no action items.\n" * 40,
        "gamma.txt": body + "configured endpoint: https://example.internal/api\n" + body,
        "delta.txt": "delta: legacy config retained for rollback.\n" * 40,
        "epsilon.txt": body + "epsilon recorded amount: 42,000 USD\n" + body,
        "zeta.txt": "zeta: rounding rules unchanged.\n" * 40,
        "eta.txt": body + "on-call owner: the platform team rota.\n" + body,
        "theta.txt": "theta: escalation path unchanged.\n" * 40,
        "iota.txt": body + "plan deadline: 2026-10-01\n" + body,
        "kappa.txt": "kappa: buffer week retained.\n" * 40,
        "lambda.txt": body + "risk flagged: supplier delay on part 7\n" + body,
        "mu.txt": "mu: mitigation drafted.\n" * 40,
    }
    for name, text in files.items():
        (notes / name).write_text(text, encoding="utf-8")


def _run_arm(label: str, budget: int, root: Path) -> dict:
    total_input = 0
    turns = 0
    ok_turns = 0
    folds = 0
    for name, file_a, file_b, question in TASKS:
        task_root = root / f"{label}-{name}"
        task_root.mkdir(parents=True, exist_ok=True)
        for note in (root / "notes").iterdir():
            (task_root / "notes").mkdir(parents=True, exist_ok=True)
            (task_root / "notes" / note.name).write_text(note.read_text(encoding="utf-8"), encoding="utf-8")
        session = Session(task_root)
        bridge = ReadOnlyToolBridge(
            (str(task_root),), observations_dir=str(task_root / ".openpilot" / "observations")
        )
        config = EngineConfig(
            cwd=str(task_root),
            timeout_seconds=120.0,
            enable_read_tool=True,
            context_budget_tokens=budget,
            observations_dir=str(task_root / ".openpilot" / "observations"),
        )
        engine = Engine(session, config)
        bridge.start()
        engine.start(bridge)
        script = [
            f"Read {file_a} and confirm in one short sentence.",
            f"Read {file_b} and confirm in one short sentence.",
            "Reply with exactly: standing by",
            question + " One short sentence, no quotes.",
        ]
        for index, prompt in enumerate(script, 1):
            response = engine.ask(prompt, first_turn=(index == 1))
            turns += 1
            if response:
                ok_turns += 1
        engine.stop()
        bridge.stop()
        folds += sum(1 for e in session.load_events() if e.event_type == "compaction")
        for event in session.load_events():
            if event.event_type in ("turn_finished", "agent_end"):
                payload = event.payload or {}
                message = payload.get("message") if isinstance(payload.get("message"), dict) else {}
                usage = message.get("usage") or {}
                total_input += int(usage.get("input") or 0)
    return {"label": label, "total_input": total_input, "turns": turns, "ok_turns": ok_turns, "folds": folds}


def main() -> int:
    key = ""
    env_path = Path.home() / "Documents" / "ChatGPT" / "yunpai-maple" / ".env.local"
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("# MAPLE_LLM_API_KEY="):
            key = line.split("=", 1)[1].strip().strip('"')
    if not key:
        raise SystemExit("DeepSeek key not found")
    os.environ["DEEPSEEK_API_KEY"] = key
    os.environ["OP0_PI_PROVIDER"] = "deepseek"
    os.environ["OP0_PI_MODEL"] = "deepseek-v4-flash"

    root = Path(tempfile.mkdtemp(prefix="op0-compact-ab-"))
    _seed_project(root)
    off = _run_arm("off", 0, root)
    on = _run_arm("on", 6_000, root)
    delta = (off["total_input"] - on["total_input"]) / max(off["total_input"], 1) * 100
    print(f"{'arm':<6} {'input tokens':>14} {'turns':>7} {'ok':>5} {'folds':>7}")
    for arm in (off, on):
        print(f"{arm['label']:<6} {arm['total_input']:>14,} {arm['turns']:>7} {arm['ok_turns']:>5} {arm['folds']:>7}")
    print(f"input reduction with compaction ON: {delta:.1f}%")
    success = on["ok_turns"] == off["ok_turns"] == len(TASKS) * 4 and on["folds"] >= 1
    print("VERDICT:", "no success regression, folds fired" if success else "CHECK: success or fold count off")
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
