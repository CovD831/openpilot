"""Sandbox: the physical wall behind the policy gate."""

from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace
from types import SimpleNamespace

import pytest

from op0 import sandbox
from op0.bridge import ReadOnlyToolBridge

ROOT = "/tmp/sbx-proj"


def test_profile_shape_and_scope() -> None:
    profile = sandbox.build_profile((Path(ROOT),), network=False, home="/Users/dev")
    assert "(deny default)" in profile
    assert f'(subpath "{ROOT}")' in profile
    assert "(deny network*)" in profile  # binary: off unless asked for
    assert '(deny file-write* (subpath "' + ROOT + '/.openpilot"))' in profile
    for entry in sandbox._SENSITIVE_READ_DENY:
        assert f'"/Users/dev/{entry}"' in profile


def test_profile_network_flag_and_escaping() -> None:
    assert "(deny network*)" not in sandbox.build_profile(
        (Path(ROOT),), network=True, home="/Users/dev"
    )
    # a scope containing quotes must not break out of the SBPL string
    tricky = Path('/tmp/we"ird\\path')
    profile = sandbox.build_profile((tricky,), network=False, home="/Users/dev")
    assert '(subpath "/tmp/we\\"ird\\\\path")' in profile


def test_sandbox_off_on_non_macos(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sandbox, "available", lambda: False)
    bridge = ReadOnlyToolBridge((ROOT,), sandbox=None)  # auto: platform decides
    assert bridge.sandbox_enabled is False
    bridge2 = ReadOnlyToolBridge((ROOT,), sandbox=True)  # explicit opt-in still honored
    assert bridge2.sandbox_enabled is True


@pytest.mark.skipif(not sandbox.available(), reason="Seatbelt is macOS-only")
def test_sandboxed_bash_inside_and_outside(tmp_path: Path) -> None:
    bridge = ReadOnlyToolBridge((str(tmp_path),), command_authorizer=lambda c, a: SimpleNamespace(consent_id="t"))
    assert bridge.sandbox_enabled is True
    ok = bridge._handle(
        {"toolName": "openpilot_bash", "toolCallId": "aaaaaaaa-0000-4000-8000-00000000sb01",
         "args": {"command": f"echo inside > {tmp_path}/in.txt"}}
    )
    assert ok["success"] is True
    assert (tmp_path / "in.txt").read_text().strip() == "inside"

    outside = tmp_path.parent / f"sbx-outside-{tmp_path.name}.txt"
    blocked = bridge._handle(
        {"toolName": "openpilot_bash", "toolCallId": "aaaaaaaa-0000-4000-8000-00000000sb02",
         "args": {"command": f"echo outside > {outside}"}}
    )
    assert not outside.exists()  # the physical wall holds even for an approved call


@pytest.mark.skipif(not sandbox.available(), reason="Seatbelt is macOS-only")
def test_sandbox_protects_the_ledger(tmp_path: Path) -> None:
    bridge = ReadOnlyToolBridge((str(tmp_path),), command_authorizer=lambda c, a: SimpleNamespace(consent_id="t"))
    ledger = tmp_path / ".openpilot" / "trajectory"
    ledger.mkdir(parents=True)
    (ledger / "run.jsonl").write_text("keep\n", encoding="utf-8")
    bridge._handle(
        {"toolName": "openpilot_bash", "toolCallId": "aaaaaaaa-0000-4000-8000-00000000sb03",
         "args": {"command": f"echo tampered > {tmp_path}/.openpilot/trajectory/run.jsonl"}}
    )
    assert (ledger / "run.jsonl").read_text() == "keep\n"  # audit chain survives bash


@pytest.mark.skipif(not sandbox.available(), reason="Seatbelt is macOS-only")
def test_sandbox_blocks_credential_reads(tmp_path: Path) -> None:
    fake_ssh = Path.home() / ".ssh" / "op0-sbx-probe"
    fake_ssh.write_text("secret\n", encoding="utf-8")
    try:
        bridge = ReadOnlyToolBridge((str(tmp_path),), command_authorizer=lambda c, a: SimpleNamespace(consent_id="t"))
        result = bridge._handle(
            {"toolName": "openpilot_bash", "toolCallId": "aaaaaaaa-0000-4000-8000-00000000sb04",
             "args": {"command": f"cat {fake_ssh}"}}
        )
        assert "secret" not in str(result.get("content") or "")
    finally:
        fake_ssh.unlink(missing_ok=True)


def test_sandbox_exec_smoke() -> None:
    """The primitive itself must work in this environment."""
    if not sandbox.available():
        pytest.skip("no sandbox-exec")
    profile = sandbox.build_profile((Path("/tmp"),), network=False, home=str(Path.home()))
    done = subprocess.run(
        ["/usr/bin/sandbox-exec", "-p", profile, "/bin/echo", "alive"],
        capture_output=True, text=True, timeout=30,
    )
    assert done.returncode == 0 and "alive" in done.stdout
