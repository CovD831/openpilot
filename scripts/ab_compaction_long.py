"""Long-session A/B: does folding pay once the session is actually long?
16 turns over four 10k files (all E1-masked at entry), OFF vs ON."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "Code" / "src"))

from op0.bridge import ReadOnlyToolBridge
from op0.engine import Engine, EngineConfig
from op0.session import Session


def _run(label: str, budget: int, root: Path, *, noise_turns: int = 0) -> dict:
    session = Session(root)
    bridge = ReadOnlyToolBridge((str(root),), observations_dir=str(root / ".openpilot" / "observations"))
    config = EngineConfig(
        cwd=str(root),
        timeout_seconds=120.0,
        enable_read_tool=True,
        context_budget_tokens=budget,
        observations_dir=str(root / ".openpilot" / "observations"),
    )
    engine = Engine(session, config)
    bridge.start()
    engine.start(bridge)
    files = ["alpha.txt", "gamma.txt", "epsilon.txt", "eta.txt"]
    turns = 0
    ok = 0
    script: list[str] = []
    for name in files:
        script.append(f"Read notes/{name} and confirm in one short sentence.")
        script.append("Reply with exactly: standing by")
    script.append("Summarize in one sentence what the four files had in common.")
    script.extend(["Reply with exactly: standing by"] * noise_turns)
    for index, prompt in enumerate(script, 1):
        response = engine.ask(prompt, first_turn=(index == 1))
        turns += 1
        ok += 1 if response else 0
    total_input = 0
    folds = 0
    for event in session.load_events():
        if event.event_type in ("turn_finished", "agent_end"):
            payload = event.payload or {}
            message = payload.get("message") if isinstance(payload.get("message"), dict) else {}
            total_input += int((message.get("usage") or {}).get("input") or 0)
        if event.event_type == "compaction":
            folds += 1
    final = session.last_model_response()
    engine.stop()
    bridge.stop()
    print(f"{label:<8} input={total_input:>8,} turns={turns} ok={ok} folds={folds} final_chars={len(final)}")
    return {"label": label, "input": total_input, "ok": ok, "folds": folds, "turns": turns}


def main() -> int:
    key = ""
    for line in (Path.home() / "Documents" / "ChatGPT" / "yunpai-maple" / ".env.local").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("# MAPLE_LLM_API_KEY="):
            key = line.split("=", 1)[1].strip().strip('"')
    os.environ["DEEPSEEK_API_KEY"] = key
    os.environ["OP0_PI_PROVIDER"] = "deepseek"
    os.environ["OP0_PI_MODEL"] = "deepseek-v4-flash"

    # 4.2k files: below E1 (8k) so they enter context, above the P1 mask line (4k)
    # — this is exactly the zone only project-layer folding can reclaim
    body = "".join(f"log line {i}: status nominal.\n" for i in range(140))
    root = Path(tempfile.mkdtemp(prefix="op0-compact-long-"))
    (root / "notes").mkdir()
    marks = {"alpha.txt": "common thread: all builds pass\n", "gamma.txt": "common thread: all builds pass\n",
             "epsilon.txt": "common thread: all builds pass\n", "eta.txt": "common thread: all builds pass\n"}
    for name in marks:
        (root / "notes" / name).write_text(body + marks[name] + body, encoding="utf-8")

    off = _run("off", 0, root, noise_turns=21)
    on = _run("on", 6_000, root, noise_turns=21)
    if off["input"]:
        delta = (off["input"] - on["input"]) / off["input"] * 100
        print(f"input reduction with compaction ON: {delta:.1f}%")
    print("VERDICT:", "no success regression" if on["ok"] == off["ok"] else "CHECK: success differs")
    return 0 if on["ok"] == off["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
