"""L1 admission: proposals, consents, and the patch gate."""

from __future__ import annotations

import json
import socket
from pathlib import Path

import pytest

from op0.admission import AdmissionError, AdmissionRegistry
from op0.bridge import ReadOnlyToolBridge

RUN = "run_test_1"


def test_deny_blocks_approval(tmp_path: Path) -> None:
    registry = AdmissionRegistry(str(tmp_path))
    proposal = registry.propose("fix file", str(tmp_path / "a.txt"))
    assert proposal.status == "pending"
    registry.deny(proposal.proposal_id)
    with pytest.raises(AdmissionError):
        registry.approve(proposal.proposal_id, RUN)


def test_approve_binds_consent_and_authorizes_exact_path(tmp_path: Path) -> None:
    registry = AdmissionRegistry(str(tmp_path))
    target = tmp_path / "a.txt"
    proposal = registry.propose("fix file", str(target))
    consent = registry.approve(proposal.proposal_id, RUN)
    assert consent.admission_id == proposal.grant.admission_id
    assert registry.authorize_patch(str(target), RUN).consent_id == consent.consent_id


def test_authorize_rejects_other_path_and_run(tmp_path: Path) -> None:
    registry = AdmissionRegistry(str(tmp_path))
    proposal = registry.propose("fix file", str(tmp_path / "a.txt"))
    registry.approve(proposal.proposal_id, RUN)
    with pytest.raises(PermissionError):
        registry.authorize_patch(str(tmp_path / "b.txt"), RUN)
    with pytest.raises(PermissionError):
        registry.authorize_patch(str(tmp_path / "a.txt"), "run_other")


def test_pending_limit(tmp_path: Path) -> None:
    registry = AdmissionRegistry(str(tmp_path))
    for i in range(3):
        registry.propose(f"goal {i}", str(tmp_path / f"f{i}.txt"))
    with pytest.raises(AdmissionError):
        registry.propose("one too many", str(tmp_path / "x.txt"))


def _bridge_call(bridge: ReadOnlyToolBridge, payload: dict) -> dict:
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    client.settimeout(5.0)
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


def test_patch_flow_denied_then_applied(tmp_path: Path) -> None:
    target = tmp_path / "code.txt"
    target.write_text("line1\nline2\nline3\n", encoding="utf-8")
    registry = AdmissionRegistry(str(tmp_path))
    bridge = ReadOnlyToolBridge((str(tmp_path),), patch_authorizer=lambda p: registry.authorize_patch(p, RUN))
    bridge.start()
    patch_request = {
        "type": "tool_call",
        "toolName": "openpilot_patch",
        "toolCallId": "p1",
        "args": {"path": str(target), "lineStart": 2, "lineEnd": 2, "replacementText": "LINE-TWO"},
    }
    try:
        denied = _bridge_call(bridge, patch_request)
        assert denied["success"] is False
        assert target.read_text(encoding="utf-8") == "line1\nline2\nline3\n"

        proposal = registry.propose("fix line 2", str(target))
        registry.approve(proposal.proposal_id, RUN)

        allowed = _bridge_call(bridge, patch_request)
        assert allowed["success"] is True
        assert "patch applied" in allowed["content"]
        assert target.read_text(encoding="utf-8") == "line1\nLINE-TWO\nline3\n"
    finally:
        bridge.stop()
