"""A/B: S1-S4 token savings (repeat-read intercept, command-aware bash
compression, concise-reply contract) ON vs OFF, real provider.

The OFF arm imports op0 from a worktree of the pre-S commit; the ON arm
from the current tree. Identical task set and files; budget stays 0 so
compaction never fires and the measured delta is S1/S2/S4 alone.

Usage: python scripts/ab_savings.py --src <op0-src> [--label on]
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--src", default=str(Path(__file__).resolve().parents[1] / "Code" / "src"))
parser.add_argument("--label", default="on")
args = parser.parse_args()
sys.path.insert(0, args.src)

from op0.bridge import ReadOnlyToolBridge  # noqa: E402
from op0.engine import Engine, EngineConfig  # noqa: E402
from op0.receipts import ReceiptStore, decide_closure  # noqa: E402
from op0.session import Session  # noqa: E402

MAIN = Path(__file__).resolve().parents[1]
PYTEST = str(MAIN / "Code" / ".venv" / "bin" / "python")

_REPEAT_BODY = "".join(
    f"line {i}: routine entry, nothing actionable.\n" for i in range(110)
) + (
    "inventory: 3 wrenches, 2 drills, 1 saw.\n"
    "deadline: 2026-10-01\n"
    "owner: platform team\n"
)


def _seed_repeat(root: Path) -> None:
    (root / "notes").mkdir(parents=True, exist_ok=True)
    (root / "notes" / "alpha.txt").write_text(_REPEAT_BODY, encoding="utf-8")  # ~6k, below E1


def _seed_tests(root: Path) -> None:
    tests = root / "tests"
    tests.mkdir(parents=True, exist_ok=True)
    body = "".join(f"\n\ndef test_case_{i:02d}():\n    assert {i} * 2 == {i * 2}\n" for i in range(30))
    (tests / "test_demo.py").write_text(body, encoding="utf-8")


def _seed_summary(root: Path) -> None:
    (root / "notes").mkdir(parents=True, exist_ok=True)
    (root / "notes" / "beta.txt").write_text(
        "beta.txt holds the migration checklist for the storage layer: three phases,\n"
        "owner rotation each phase, and a rollback window after every deploy.\n" * 6,
        encoding="utf-8",
    )


TASKS: list[tuple[str, object, list[str]]] = [
    (
        "repeat",
        _seed_repeat,
        [
            "Use openpilot_read on notes/alpha.txt, then tell me: how many wrenches? One short sentence.",
            "Re-read notes/alpha.txt with openpilot_read, then tell me: how many drills? One short sentence.",
            "Re-read notes/alpha.txt with openpilot_read, then tell me: what is the deadline? One short sentence.",
        ],
    ),
    (
        "tests",
        _seed_tests,
        [f"Run `{PYTEST} -m pytest tests/ -v` with openpilot_bash and report the outcome in one short sentence."],
    ),
    (
        "summary",
        _seed_summary,
        ["Read notes/beta.txt with openpilot_read and summarize it in 2-3 sentences. Do not modify anything."],
    ),
]


def _run_arm(label: str, root: Path) -> dict:
    totals = {"input": 0, "output": 0, "turns": 0, "ok": 0, "intercepts": 0, "s2": 0, "closures": {}}
    for name, seed, script in TASKS:
        task_root = root / f"{label}-{name}"
        task_root.mkdir(parents=True, exist_ok=True)
        seed(task_root)
        session = Session(task_root)
        store = ReceiptStore(task_root)

        def on_bash(command: str, code: int, out: str, consent: object) -> None:
            store.write_bash_receipt(
                run_id=session.run_id, consent_id="ab", proposal_id="ab", admission_id="ab",
                command=command, exit_code=code, output_tail=out,
            )

        bridge = ReadOnlyToolBridge(
            (str(task_root),),
            observations_dir=str(task_root / ".openpilot" / "observations"),
            command_authorizer=lambda command, args: True,
            on_bash_executed=on_bash,
            on_result=lambda r: session.record("tool_result", r, producer="bridge", call_id=str(r.get("toolCallId") or "")),
        )
        config = EngineConfig(
            # the pi binary lives in the main checkout (node_modules is not in
            # git); both arms use the same binary, only the op0 src differs
            command=(str(MAIN / "Code" / "pi_sidecar" / "node_modules" / ".bin" / "pi"),),
            cwd=str(task_root),
            timeout_seconds=180.0,
            enable_read_tool=True,
            context_budget_tokens=0,  # compaction off: the delta is S1/S2/S4 alone
            observations_dir=str(task_root / ".openpilot" / "observations"),
        )
        engine = Engine(session, config)
        bridge.start()
        engine.start(bridge)
        saw_response = False
        for index, prompt in enumerate(script, 1):
            response = engine.ask(prompt, first_turn=(index == 1))
            totals["turns"] += 1
            if response:
                totals["ok"] += 1
                saw_response = True
        engine.stop()
        bridge.stop()
        events = session.load_events()
        for event in events:
            payload = event.payload or {}
            if event.event_type in ("turn_finished", "agent_end"):
                message = payload.get("message") if isinstance(payload.get("message"), dict) else {}
                usage = message.get("usage") or {}
                totals["input"] += int(usage.get("input") or 0)
                totals["output"] += int(usage.get("output") or usage.get("output_tokens") or usage.get("outputTokens") or 0)
            if event.producer == "bridge":
                preview = str(payload.get("preview") or "")
                totals["intercepts"] += preview.count("unchanged repeat-read skipped")
                totals["s2"] += preview.count("[test output:")
        status, _ = decide_closure(store.all(run_id=session.run_id), saw_model_response=saw_response)
        totals["closures"][name] = status
    return totals


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

    root = Path(tempfile.mkdtemp(prefix=f"op0-savings-{args.label}-"))
    result = _run_arm(args.label, root)
    closures = " ".join(f"{k}={v}" for k, v in result.pop("closures").items())
    result["label"] = args.label
    result["src"] = args.src
    print("RESULT " + str(result) + " closures: " + closures)
    return 0 if result["ok"] == result["turns"] else 1


if __name__ == "__main__":
    sys.exit(main())
