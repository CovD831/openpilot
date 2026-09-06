"""L3: reconciliation after a crash; side effects are never replayed."""

from __future__ import annotations

from pathlib import Path

from op0.receipts import ReceiptStore, decide_closure, file_hash, record_validation
from op0.recovery import MISMATCH, MISSING, APPLIED, REVERTED, reconcile, reconcile_one, resume_plan

RUN = "run_l3"


def _seed(target: Path, store: ReceiptStore, *, content_before: str, content_after: str) -> None:
    target.write_text(content_before, encoding="utf-8")
    hash_before = file_hash(target)
    target.write_text(content_after, encoding="utf-8")
    store.write_patch_receipt(
        run_id=RUN,
        consent_id="c",
        proposal_id="p",
        admission_id="a",
        path=str(target),
        hash_before=hash_before,
        hash_after=file_hash(target),
        validation_command="",
    )


def test_reconcile_applied_reverted_mismatch_missing(tmp_path: Path) -> None:
    store = ReceiptStore(tmp_path)
    applied = tmp_path / "applied.txt"
    reverted = tmp_path / "reverted.txt"
    mismatched = tmp_path / "mismatch.txt"
    missing = tmp_path / "missing.txt"
    _seed(applied, store, content_before="a\n", content_after="b\n")
    _seed(reverted, store, content_before="a\n", content_after="b\n")
    reverted.write_text("a\n", encoding="utf-8")
    _seed(mismatched, store, content_before="a\n", content_after="b\n")
    mismatched.write_text("c\n", encoding="utf-8")
    _seed(missing, store, content_before="a\n", content_after="b\n")
    missing.unlink()

    by_state = {item.receipt.path: item.disk_state for item in reconcile(store)}
    assert by_state[str(applied)] == APPLIED
    assert by_state[str(reverted)] == REVERTED
    assert by_state[str(mismatched)] == MISMATCH
    assert by_state[str(missing)] == MISSING


def test_crash_window_resume_never_replays(tmp_path: Path) -> None:
    target = tmp_path / "code.txt"
    target.write_text("VALUE = 555\n", encoding="utf-8")
    store = ReceiptStore(tmp_path)
    _seed(target, store, content_before="VALUE = 555\n", content_after="VALUE = 777\n")

    fresh_store = ReceiptStore(tmp_path)
    reconciled = reconcile(fresh_store, run_id=RUN)
    assert reconciled[0].disk_state == APPLIED
    status, actions = resume_plan(reconciled)
    assert status == "indeterminate"
    assert any("validate" in action for action in actions)
    assert not any("replay" in action or "re-apply" in action for action in actions)

    disk_unchanged = file_hash(target)
    receipt = reconciled[0].receipt
    updated, _ = record_validation(fresh_store, receipt, command="true", cwd=str(tmp_path))
    assert file_hash(target) == disk_unchanged
    assert decide_closure(fresh_store.all(run_id=RUN), saw_model_response=True)[0] == "success"
    assert updated.validation_status == "passed"


def test_resume_plan_closed_when_all_validated(tmp_path: Path) -> None:
    store = ReceiptStore(tmp_path)
    target = tmp_path / "f.txt"
    _seed(target, store, content_before="a\n", content_after="b\n")
    reconciled = reconcile(store, run_id=RUN)
    record_validation(store, reconciled[0].receipt, command="true", cwd=str(tmp_path))
    reconciled = reconcile(store, run_id=RUN)
    status, actions = resume_plan(reconciled)
    assert status == "closed"
    assert actions == []
    assert reconciled[0].needs_validation is False
    assert reconcile_one(store, reconciled[0].receipt).disk_state == APPLIED


def test_bash_receipt_and_directory_paths_never_crash_reconcile(tmp_path: Path) -> None:
    """Regression: a bash receipt has path='' (resolves to '.'); a write receipt
    may point at a directory. Reconciliation must classify, not raise."""
    store = ReceiptStore(tmp_path)
    store.write_bash_receipt(
        run_id=RUN, consent_id="c", proposal_id="p", admission_id="a",
        command="echo hi", exit_code=0, output_tail="hi",
    )
    store.write_patch_receipt(
        run_id=RUN, consent_id="c2", proposal_id="p2", admission_id="a2",
        path=str(tmp_path), hash_before="x", hash_after="y", validation_command="",
    )
    reconciled = reconcile(store, run_id=RUN)
    by_state = {item.disk_state for item in reconciled}
    assert "command" in by_state
    assert "mismatch" in by_state
    status, _ = resume_plan(reconciled)
    assert status in ("indeterminate", "closed", "clean")
