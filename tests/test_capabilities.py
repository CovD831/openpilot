"""L4 capability layer: bash, write, search — all through the consent gate."""

from __future__ import annotations

import json
import socket
from pathlib import Path

import pytest

from op0.admission import AdmissionError, AdmissionRegistry
from op0.bridge import ReadOnlyToolBridge
from op0.receipts import ReceiptStore

RUN = "run_l4"


def _call(bridge: ReadOnlyToolBridge, payload: dict) -> dict:
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    client.settimeout(10.0)
    client.connect(bridge.socket_path)
    client.sendall(json.dumps(payload).encode("utf-8") + b"\n")
    buffer = bytearray()
    while b"\n" not in buffer:
        chunk = client.recv(4096)
        if not chunk:
            break
        buffer.extend(chunk)
    client.close()
    return json.loads(bytes(buffer.split(b"\n", 1)[0]).decode("utf-8"))


def test_bash_requires_own_consent_and_receipts(tmp_path: Path) -> None:
    registry = AdmissionRegistry(str(tmp_path))
    store = ReceiptStore(tmp_path)
    receipts: list = []

    def on_bash(command: str, exit_code: int, output: str, consent) -> None:
        receipts.append(
            store.write_bash_receipt(
                run_id=RUN, consent_id=consent.consent_id, proposal_id=consent.proposal_id,
                admission_id=consent.admission_id, command=command,
                exit_code=exit_code, output_tail=output,
            )
        )

    bridge = ReadOnlyToolBridge(
        (str(tmp_path),),
        command_authorizer=lambda c, a: registry.authorize_command(c, RUN),
        on_bash_executed=on_bash,
    )
    bridge.start()
    request = {"type": "tool_call", "toolName": "openpilot_bash", "toolCallId": "b1", "args": {"command": "echo hi-from-op0"}}
    try:
        denied = _call(bridge, request)
        assert denied["success"] is False
        proposal = registry.propose_command("run echo", "echo hi-from-op0")
        registry.approve(proposal.proposal_id, RUN)
        allowed = _call(bridge, request)
        assert allowed["success"] is True
        assert "hi-from-op0" in allowed["content"]
        assert len(receipts) == 1
        assert receipts[0].exit_code == 0
        assert receipts[0].validation_status == "passed"
        # a different command is NOT covered by the echo consent
        other = _call(bridge, {**request, "toolCallId": "b2", "args": {"command": "echo other"}})
        assert other["success"] is False
    finally:
        bridge.stop()


def test_write_creates_file_with_receipt(tmp_path: Path) -> None:
    registry = AdmissionRegistry(str(tmp_path))
    store = ReceiptStore(tmp_path)
    new_file = tmp_path / "new.txt"

    def on_applied(path: str, hash_before: str, hash_after: str, consent) -> None:
        store.write_patch_receipt(
            run_id=RUN, consent_id=consent.consent_id, proposal_id=consent.proposal_id,
            admission_id=consent.admission_id, path=path, hash_before=hash_before,
            hash_after=hash_after, validation_command="", kind=consent.kind,
        )

    bridge = ReadOnlyToolBridge(
        (str(tmp_path),),
        patch_authorizer=lambda p, a: registry.authorize_patch(p, RUN),
        on_patch_applied=on_applied,
    )
    bridge.start()
    request = {
        "type": "tool_call",
        "toolName": "openpilot_write",
        "toolCallId": "w1",
        "args": {"path": str(new_file), "content": "hello\n"},
    }
    try:
        denied = _call(bridge, request)
        assert denied["success"] is False
        proposal = registry.propose("create file", str(new_file), kind="write")
        registry.approve(proposal.proposal_id, RUN)
        allowed = _call(bridge, request)
        assert allowed["success"] is True
        assert "created" in allowed["content"]
        assert new_file.read_text(encoding="utf-8") == "hello\n"
        receipts = store.all(run_id=RUN)
        assert len(receipts) == 1
        assert receipts[0].hash_before == "absent"
        assert receipts[0].hash_after != "absent"
    finally:
        bridge.stop()


def test_search_is_free_but_scoped(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("TARGET = 1\n", encoding="utf-8")
    (tmp_path / "b.txt").write_text("TARGET = 2\n", encoding="utf-8")
    outside = tmp_path.parent / "out.txt"
    outside.write_text("TARGET = 3\n", encoding="utf-8")
    bridge = ReadOnlyToolBridge((str(tmp_path),))
    bridge.start()
    try:
        hit = _call(bridge, {"type": "tool_call", "toolName": "openpilot_search", "toolCallId": "s1", "args": {"pattern": "TARGET", "glob": "*.py"}})
        assert hit["success"] is True
        assert "a.py:1" in hit["content"]
        assert "b.txt" not in hit["content"]
        assert "out.txt" not in hit["content"]
    finally:
        bridge.stop()


def test_approve_all_merges_pending(tmp_path: Path) -> None:
    registry = AdmissionRegistry(str(tmp_path))
    p1 = registry.propose("a", str(tmp_path / "f1.txt"))
    p2 = registry.propose_command("b", "echo x")
    consent, ids = registry.approve_all(RUN)
    assert set(ids) == {p1.proposal_id, p2.proposal_id}
    assert str(tmp_path / "f1.txt") in consent.write_paths
    assert "echo x" in consent.command
    assert registry.authorize_patch(str(tmp_path / "f1.txt"), RUN).consent_id == consent.consent_id
    assert registry.authorize_command("echo x", RUN).consent_id == consent.consent_id
    with pytest.raises(AdmissionError):
        registry.approve_all(RUN)
