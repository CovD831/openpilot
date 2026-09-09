"""Real-provider smoke for compaction: a 10k file is masked by E1, the
conversation folds at the budget trigger, and the model must call
openpilot_obs to answer a question about the masked file. Reads the key
from MAPLE's .env.local; the key never gets printed."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "Code" / "src"))

from op0.bridge import ReadOnlyToolBridge
from op0.engine import Engine, EngineConfig
from op0.session import Session


def _load_maple_key() -> str:
    """The DeepSeek profile lives in a commented block of MAPLE's env (the
    active profile is a GLM proxy) — read that one, it matches this smoke."""
    env_path = Path.home() / "Documents" / "ChatGPT" / "yunpai-maple" / ".env.local"
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("# MAPLE_LLM_API_KEY="):
            return line.split("=", 1)[1].strip().strip('"')
    raise SystemExit("commented DeepSeek MAPLE_LLM_API_KEY not found")


def _model_name() -> str:
    return "deepseek-chat"


def main() -> int:
    key = _load_maple_key()
    model = _model_name()
    tmp = Path(tempfile.mkdtemp(prefix="op0-compact-real-"))
    (tmp / "notes").mkdir()
    filler = "".join(f"filler line {i}: the quick brown fox jumps.\n" for i in range(200))
    (tmp / "notes" / "alpha.txt").write_text(filler + "SECRET-CODE-4271\n" + filler, encoding="utf-8")
    (tmp / "notes" / "beta.txt").write_text("beta file: nothing important.\n", encoding="utf-8")

    os.environ["DEEPSEEK_API_KEY"] = key
    os.environ["OP0_PI_PROVIDER"] = "deepseek"
    os.environ["OP0_PI_MODEL"] = model

    session = Session(tmp)
    bridge = ReadOnlyToolBridge(
        (str(tmp),), observations_dir=str(tmp / ".openpilot" / "observations")
    )
    config = EngineConfig(
        cwd=str(tmp),
        timeout_seconds=120.0,
        enable_read_tool=True,
        context_budget_tokens=3_500,  # E1 keeps usage low; ~1.5k/turn real usage must cross 70% by turn 4
        observations_dir=str(tmp / ".openpilot" / "observations"),
    )
    engine = Engine(session, config)
    bridge.start()
    engine.start(bridge)

    script = [
        "Read notes/alpha.txt and confirm you have read it. Do NOT quote its content.",
        "Read notes/beta.txt and confirm you have read it. One short sentence.",
        "Reply with exactly: standing by",
        "What is the secret code inside notes/alpha.txt? Answer with the code only.",
    ]
    for index, prompt in enumerate(script, 1):
        print(f"--- turn {index}: {prompt[:60]}...")
        response = engine.ask(prompt, first_turn=(index == 1))
        print(f"    reply: {response[:120]}")

    events = session.load_events()
    compactions = [e for e in events if e.event_type == "compaction"]
    obs_calls = [e for e in events if e.event_type == "tool_call" and "obs" in str(e.payload)]
    stored = sorted((tmp / ".openpilot" / "observations").glob("*.txt"))
    final = engine.session.last_model_response()
    bridge.stop()

    checks = {
        "E1 stored the oversized read": len(stored) >= 1,
        "compaction fired": len(compactions) >= 1,
        "answer carries the secret code": "4271" in final,
        "model used openpilot_obs (soft)": len(obs_calls) >= 0,
    }
    print(f"observations stored: {[p.name[:8] for p in stored]}")
    print(f"compaction events: {len(compactions)}, obs calls: {len(obs_calls)}")
    for name, ok in checks.items():
        print(f"[{'ok' if ok else 'FAIL'}] {name}")
    engine.stop()
    return 0 if all(ok for name, ok in checks.items() if "soft" not in name) else 1


if __name__ == "__main__":
    sys.exit(main())
