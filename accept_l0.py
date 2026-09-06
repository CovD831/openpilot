#!/usr/bin/env python3
"""L0 clean-base acceptance gate (stdlib only, zero third-party deps).

Usage:
    python3 accept_l0.py --base-root /Users/abab/Developer/openpilot-l0

Gates:
    G0 environment      node >= 22.19, `pi --version`, OPENPILOT_LLM_API_KEY set
    G1 cold start       `python -m op0 --once <goal> --project-path <fixture>` exits 0
    G2 read-only loop   stdout of G1 contains the expected VALUE (555)
    G3 trajectory       JSONL events include tool_call(read) and model_response
    G4 line budget      Code/src/**/*.py total lines <= 2000
    G5 no legacy import no import of legacy top-level packages anywhere in Code/src

Gates that need the L0 implementation report "blocked" (not failed) while the
clean base does not exist yet; the receipt is still written so partial runs are
auditable. This mirrors the body-free receipt convention of the s6 experiments.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

LINE_BUDGET = 2000
NODE_MIN = (22, 19)
LEGACY_TOPS = frozenset(
    {"autonomous_iteration", "metadata", "tools", "memory", "core", "evidence_core", "ui", "utils"}
)
GOAL = "读取 answer.txt 的内容，回答 VALUE 等于多少"
EXPECTED_MARK = "555"


def _gate(name: str, status: str, detail: str) -> dict[str, str]:
    return {"gate": name, "status": status, "detail": detail}


def _node_version_ok() -> tuple[bool, str]:
    node = shutil.which("node")
    if node is None:
        return False, "node not found in PATH"
    try:
        out = subprocess.run(
            [node, "--version"], capture_output=True, text=True, timeout=10, check=True
        ).stdout.strip()
    except Exception as exc:  # noqa: BLE001
        return False, f"node --version failed: {exc}"
    match = re.match(r"v(\d+)\.(\d+)", out)
    if not match:
        return False, f"unparsable node version: {out!r}"
    ok = (int(match.group(1)), int(match.group(2))) >= NODE_MIN
    return ok, f"node {out} (requires >= {NODE_MIN[0]}.{NODE_MIN[1]})"


def gate_environment(base_root: Path) -> dict[str, str]:
    parts: list[str] = []
    ok, detail = _node_version_ok()
    parts.append(detail)
    if not ok:
        return _gate("G0-environment", "failed", "; ".join(parts))

    sidecar = base_root / "Code" / "pi_sidecar"
    if not (sidecar / "package.json").exists():
        parts.append("Code/pi_sidecar/package.json missing")
        return _gate("G0-environment", "blocked", "; ".join(parts))
    pi_bin = sidecar / "node_modules" / ".bin" / "pi"
    if not pi_bin.exists():
        parts.append("pi binary missing; run `npm install` in Code/pi_sidecar")
        return _gate("G0-environment", "blocked", "; ".join(parts))
    try:
        proc = subprocess.run(
            [str(pi_bin), "--version"], capture_output=True, text=True, timeout=30, cwd=sidecar
        )
    except Exception as exc:  # noqa: BLE001
        return _gate("G0-environment", "failed", f"pi --version raised: {exc}")
    if proc.returncode != 0:
        return _gate("G0-environment", "failed", f"pi --version exit {proc.returncode}")
    parts.append(f"pi {proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else 'ok'}")

    if not os.getenv("OPENPILOT_LLM_API_KEY"):
        return _gate("G0-environment", "blocked", "OPENPILOT_LLM_API_KEY not set; " + "; ".join(parts))
    parts.append("OPENPILOT_LLM_API_KEY set")
    return _gate("G0-environment", "passed", "; ".join(parts))


def _run_once(base_root: Path, project_path: Path) -> subprocess.CompletedProcess[str] | None:
    venv_python = base_root / "Code" / ".venv" / "bin" / "python"
    python = str(venv_python) if venv_python.exists() else sys.executable
    try:
        return subprocess.run(
            [
                python,
                "-m",
                "op0",
                "--once",
                GOAL,
                "--project-path",
                str(project_path),
            ],
            capture_output=True,
            text=True,
            timeout=180,
            cwd=str(project_path),
            env={**os.environ, "PYTHONPATH": str(base_root / "Code" / "src")},
        )
    except Exception:  # noqa: BLE001
        return None


def gate_cold_start(base_root: Path, project_path: Path) -> tuple[dict[str, str], subprocess.CompletedProcess[str] | None]:
    if not (base_root / "Code" / "src" / "op0").exists():
        return _gate("G1-cold-start", "blocked", "Code/src/op0 not implemented yet"), None
    proc = _run_once(base_root, project_path)
    if proc is None:
        return _gate("G1-cold-start", "failed", "runner raised or timed out"), None
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "")[-400:]
        return _gate("G1-cold-start", "failed", f"exit {proc.returncode}: {tail}"), proc
    return _gate("G1-cold-start", "passed", "exit 0"), proc


def gate_read_only_loop(proc: subprocess.CompletedProcess[str] | None) -> dict[str, str]:
    if proc is None:
        return _gate("G2-read-only-loop", "blocked", "depends on G1")
    if EXPECTED_MARK in (proc.stdout or ""):
        return _gate("G2-read-only-loop", "passed", f"stdout contains {EXPECTED_MARK}")
    return _gate(
        "G2-read-only-loop",
        "failed",
        f"expected {EXPECTED_MARK!r} in stdout; got tail: {(proc.stdout or '')[-200:]!r}",
    )


def gate_trajectory(base_root: Path, project_path: Path) -> dict[str, str]:
    if not (base_root / "Code" / "src" / "op0").exists():
        return _gate("G3-trajectory", "blocked", "Code/src/op0 not implemented yet")
    jsonl_files = sorted((project_path / ".openpilot").rglob("*.jsonl"))
    if not jsonl_files:
        return _gate("G3-trajectory", "failed", "no JSONL trajectory under <fixture>/.openpilot")
    saw_tool_call = saw_model_response = False
    for path in jsonl_files:
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            event_type = str(event.get("event_type", ""))
            saw_tool_call = saw_tool_call or "tool_call" in event_type
            saw_model_response = saw_model_response or "model_response" in event_type
    if saw_tool_call and saw_model_response:
        return _gate("G3-trajectory", "passed", f"{len(jsonl_files)} JSONL file(s), tool_call + model_response")
    return _gate(
        "G3-trajectory",
        "failed",
        f"tool_call={saw_tool_call} model_response={saw_model_response}",
    )


def gate_line_budget(base_root: Path) -> dict[str, str]:
    src = base_root / "Code" / "src"
    if not src.exists():
        return _gate("G4-line-budget", "blocked", "Code/src not created yet")
    total = sum(len(p.read_text(encoding="utf-8", errors="ignore").splitlines()) for p in src.rglob("*.py"))
    if total <= LINE_BUDGET:
        return _gate("G4-line-budget", "passed", f"{total} lines <= {LINE_BUDGET}")
    return _gate("G4-line-budget", "failed", f"{total} lines > {LINE_BUDGET}")


def gate_no_legacy_import(base_root: Path) -> dict[str, str]:
    src = base_root / "Code" / "src"
    if not src.exists():
        return _gate("G5-no-legacy-import", "blocked", "Code/src not created yet")
    offenders: list[str] = []
    for pyfile in sorted(src.rglob("*.py")):
        try:
            tree = ast.parse(pyfile.read_text(encoding="utf-8", errors="ignore"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            module = None
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                modules = [node.module or ""]
            else:
                continue
            for module in modules:
                top = (module or "").split(".")[0]
                if top in LEGACY_TOPS:
                    offenders.append(
                        f"{pyfile.relative_to(src)}: {module} (line {node.lineno})"
                    )
    if offenders:
        return _gate("G5-no-legacy-import", "failed", "; ".join(offenders[:8]))
    return _gate("G5-no-legacy-import", "passed", "no legacy top-level imports")


def gate_admission(base_root: Path) -> dict[str, str]:
    """G6: deny blocks approval; approval binds a consent; out-of-scope patches fail."""
    if not (base_root / "Code" / "src" / "op0" / "admission.py").exists():
        return _gate("G6-admission", "blocked", "op0.admission not implemented yet")
    sys.path.insert(0, str(base_root / "Code" / "src"))
    try:
        from op0.admission import AdmissionError, AdmissionRegistry  # noqa: PLC0415
    except Exception as exc:  # noqa: BLE001
        return _gate("G6-admission", "failed", f"import failed: {exc}")

    fixture = Path(tempfile.mkdtemp(prefix="op0-accept-adm-"))
    target = fixture / "code.txt"
    target.write_text("line1\nline2\n", encoding="utf-8")
    try:
        registry = AdmissionRegistry(str(fixture))
        proposal = registry.propose("g", str(target))
        registry.deny(proposal.proposal_id)
        try:
            registry.approve(proposal.proposal_id, "run_x")
            return _gate("G6-admission", "failed", "denied proposal was approvable")
        except AdmissionError:
            pass
        proposal2 = registry.propose("g", str(target))
        consent = registry.approve(proposal2.proposal_id, "run_x")
        if consent.run_id != "run_x":
            return _gate("G6-admission", "failed", "consent not bound to run")
        registry.authorize_patch(str(target), "run_x")
        try:
            registry.authorize_patch(str(fixture / "other.txt"), "run_x")
            return _gate("G6-admission", "failed", "out-of-scope path authorized")
        except PermissionError:
            pass
        return _gate("G6-admission", "passed", "deny/approve/bind/scope all enforced")
    except Exception as exc:  # noqa: BLE001
        return _gate("G6-admission", "failed", f"{type(exc).__name__}: {exc}")


def main() -> int:
    parser = argparse.ArgumentParser(description="L0 clean-base acceptance gate")
    parser.add_argument("--base-root", required=True, help="clean-base worktree root")
    args = parser.parse_args()
    base_root = Path(args.base_root).expanduser().resolve(strict=False)

    fixture = Path(tempfile.mkdtemp(prefix="op0-accept-"))
    (fixture / "answer.txt").write_text("VALUE = 555\nsecond line\nthird line\n", encoding="utf-8")

    gates = [gate_environment(base_root)]
    g1, proc = gate_cold_start(base_root, fixture)
    gates.extend(
        [
            g1,
            gate_read_only_loop(proc),
            gate_trajectory(base_root, fixture),
            gate_line_budget(base_root),
            gate_no_legacy_import(base_root),
            gate_admission(base_root),
        ]
    )

    passed = sum(1 for gate in gates if gate["status"] == "passed")
    failed = sum(1 for gate in gates if gate["status"] == "failed")
    status = "passed" if failed == 0 and passed == len(gates) else ("failed" if failed else "blocked")
    receipt = {
        "schema": "openpilot-l0-acceptance/v1",
        "status": status,
        "base_root": str(base_root),
        "line_budget": LINE_BUDGET,
        "summary": {"passed": passed, "failed": failed, "blocked": len(gates) - passed - failed},
        "gates": gates,
        "generated_at": datetime.now(UTC).isoformat(),
    }

    runs_dir = base_root / "runs" / f"accept_{int(time.time())}"
    runs_dir.mkdir(parents=True, exist_ok=True)
    (runs_dir / "result.json").write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(receipt, ensure_ascii=False, indent=2))
    return 0 if status == "passed" else (1 if status == "failed" else 2)


if __name__ == "__main__":
    raise SystemExit(main())
