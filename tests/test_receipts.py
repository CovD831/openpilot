"""L2: durable receipts, validation, and evidence-only closure."""

from __future__ import annotations

import json
import socket
from pathlib import Path

import pytest

from op0.admission import AdmissionRegistry
from op0.bridge import ReadOnlyToolBridge
from op0.receipts import ReceiptStore, decide_closure, file_hash, record_validation

RUN = "run_l2"


def test_receipt_is_durable_and_hash_bound(tmp_path: Path) -> None:
    target = tmp_path / "code.txt"
    target.write_text("line1\n", encoding="utf-8")
    store = ReceiptStore(tmp_path)
    hash_before = file_hash(target)
    target.write_text("line1 patched\n", encoding="utf-8")
    receipt = store.write_patch_receipt(
        run_id=RUN,
        consent_id="con_1",
        proposal_id="prop_1",
        admission_id="adm_1",
        path=str(target),
        hash_before=hash_before,
        hash_after=file_hash(target),
        validation_command="",
    )
    reloaded = store.load(receipt.receipt_id)
    assert reloaded is not None
    assert reloaded.hash_before == hash_before
    assert reloaded.validation_status == "pending"
    assert (tmp_path / ".openpilot" / "receipts").exists()
    assert reloaded.to_json().startswith("{")
    assert json.loads(reloaded.to_json())["hash_after"] == reloaded.hash_after


def test_closure_decisions_ignore_model_self_report(tmp_path: Path) -> None:
    store = ReceiptStore(tmp_path)
    target = tmp_path / "code.txt"
    target.write_text("a\n", encoding="utf-8")
    receipt = store.write_patch_receipt(
        run_id=RUN,
        consent_id="con_1",
        proposal_id="prop_1",
        admission_id="adm_1",
        path=str(target),
        hash_before="x",
        hash_after="y",
        validation_command="",
    )
    assert decide_closure([], saw_model_response=True)[0] == "success"
    assert decide_closure([receipt], saw_model_response=True)[0] == "indeterminate"
    updated, _ = record_validation(store, receipt, command="true", cwd=str(tmp_path))
    assert updated.validation_status == "passed"
    assert decide_closure([updated], saw_model_response=True)[0] == "success"
    failed, _ = record_validation(store, updated, command="false", cwd=str(tmp_path))
    assert failed.validation_status == "failed"
    assert decide_closure([failed], saw_model_response=True)[0] == "failed"


def test_bridge_patch_writes_receipt(tmp_path: Path) -> None:
    target = tmp_path / "code.txt"
    target.write_text("line1\nline2\n", encoding="utf-8")
    registry = AdmissionRegistry(str(tmp_path))
    store = ReceiptStore(tmp_path)
    seen: dict = {}

    def on_applied(path: str, hash_before: str, hash_after: str, consent) -> None:
        seen["consent"] = consent.consent_id
        receipt = store.write_patch_receipt(
            run_id=RUN,
            consent_id=consent.consent_id,
            proposal_id=consent.proposal_id,
            admission_id=consent.admission_id,
            path=path,
            hash_before=hash_before,
            hash_after=hash_after,
            validation_command=consent.validation_command,
        )
        if receipt.validation_command:
            record_validation(store, receipt, command=receipt.validation_command, cwd=str(tmp_path))

    bridge = ReadOnlyToolBridge(
        (str(tmp_path),),
        patch_authorizer=lambda p, a: registry.authorize_patch(p, RUN),
        on_patch_applied=on_applied,
    )
    bridge.start()
    request = {
        "type": "tool_call",
        "toolName": "openpilot_patch",
        "toolCallId": "p9",
        "args": {"path": str(target), "lineStart": 1, "lineEnd": 1, "replacementText": "ONE"},
    }
    try:
        proposal = registry.propose("g", str(target))
        registry.approve(proposal.proposal_id, RUN, validation_command="grep -q ONE " + str(target))
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.settimeout(5.0)
        client.connect(bridge.socket_path)
        client.sendall(json.dumps(request).encode("utf-8") + b"\n")
        buffer = bytearray()
        while b"\n" not in buffer:
            chunk = client.recv(4096)
            if not chunk:
                break
            buffer.extend(chunk)
        response = json.loads(bytes(buffer.split(b"\n", 1)[0]).decode("utf-8"))
        client.close()
        assert response["success"] is True
        assert target.read_text(encoding="utf-8") == "ONE\nline2\n"
        receipts = store.all(run_id=RUN)
        assert len(receipts) == 1
        assert receipts[0].validation_status == "passed"
        assert receipts[0].validation_command.startswith("grep -q ONE")
        assert seen["consent"] == receipts[0].consent_id
    finally:
        bridge.stop()


def test_dismissed_receipt_counts_for_nothing(tmp_path: Path) -> None:
    store = ReceiptStore(tmp_path)
    target = tmp_path / "f.txt"
    target.write_text("a\n", encoding="utf-8")
    receipt = store.write_patch_receipt(
        run_id="r", consent_id="c", proposal_id="p", admission_id="a",
        path=str(target), hash_before="x", hash_after="y", validation_command="",
    )
    retracted = type(receipt)(**{**receipt.__dict__, "validation_status": "dismissed"})
    store.save(retracted)
    from op0.receipts import decide_closure
    status, _ = decide_closure(store.all(run_id="r"), saw_model_response=True)
    assert status == "success"  # dismissed evidence counts for nothing
