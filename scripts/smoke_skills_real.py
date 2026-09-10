"""Real-provider smoke for the skills module (DeepSeek direct, deepseek-v4-flash).

Installs one skill in a temp project's .openpilot/skills/, then asks the
model to greet. The full progressive-disclosure loop must fire:
contract index -> model reads SKILL.md via openpilot_read -> obeys the body.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "Code" / "src"))

from op0.bridge import ReadOnlyToolBridge  # noqa: E402
from op0.engine import Engine, EngineConfig  # noqa: E402
from op0.receipts import ReceiptStore  # noqa: E402
from op0.session import Session  # noqa: E402


def _load_deepseek_key() -> None:
    env_path = Path.home() / "Documents" / "ChatGPT" / "yunpai-maple" / ".env.local"
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("# MAPLE_LLM_API_KEY="):
            os.environ["DEEPSEEK_API_KEY"] = line.split("=", 1)[1].strip().strip('"')
            os.environ["OP0_PI_PROVIDER"] = "deepseek"
            os.environ["OP0_PI_MODEL"] = "deepseek-v4-flash"
            return
    raise SystemExit("DeepSeek key not found")


def main() -> int:
    _load_deepseek_key()
    with tempfile.TemporaryDirectory(prefix="op0-skill-smoke-") as tmp:
        root = Path(tmp)
        skill_dir = root / ".openpilot" / "skills" / "greeting"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            "---\nname: greeting\ndescription: Greeting protocol. Use whenever asked to greet, say hi, or welcome someone.\n---\n\n"
            "## Instructions\nEvery greeting MUST start with the word AHOY, exactly.\n",
            encoding="utf-8",
        )
        session = Session(root)
        store = ReceiptStore(root)
        consent = type("C", (), {"consent_id": "smoke"})()
        bridge = ReadOnlyToolBridge(
            (str(root),),
            patch_authorizer=lambda p, a: consent,
            command_authorizer=lambda c, a: consent,
        )
        config = EngineConfig(
            cwd=str(root),
            timeout_seconds=180.0,
            enable_read_tool=True,
            context_budget_tokens=0,
            observations_dir=str(root / ".openpilot" / "observations"),
        )
        engine = Engine(session, config)
        bridge.start()
        engine.start(bridge)
        answer = engine.ask("Please greet our guest.", first_turn=True)
        engine.stop()
        bridge.stop()
        checks = [
            ("skill body was read (trajectory has the SKILL.md read)", any(
                "SKILL.md" in str(e.payload) for e in session.load_events() if e.event_type == "tool_call"
            )),
            ("answer follows the AHOY protocol", "AHOY" in answer.upper()),
        ]
        print("\nanswer:", answer[:200].replace("\n", " "))
        for check, ok in checks:
            print(f"  [{'ok' if ok else 'FAIL'}] {check}")
        return 0 if all(ok for _, ok in checks) else 1


if __name__ == "__main__":
    sys.exit(main())
