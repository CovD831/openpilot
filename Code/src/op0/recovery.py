"""L3 recovery: reconcile durable receipts against disk after a crash.

The crash window is exactly L2's indeterminate state: a patch touched disk and
wrote its receipt, but validation never ran. Reconciliation is read-only — it
never replays a side effect; replaying or validating is a human decision.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from op0.receipts import Receipt, ReceiptStore, file_hash

APPLIED = "applied"      # disk matches hash_after: the side effect is on disk
COMMAND = "command"      # bash receipt: no file to reconcile against
REVERTED = "reverted"    # disk matches hash_before: the change is gone
MISSING = "missing"      # the file no longer exists
MISMATCH = "mismatch"    # disk changed by something else


@dataclass(frozen=True)
class ReconciledReceipt:
    receipt: Receipt
    disk_state: str
    disk_hash: str

    @property
    def needs_validation(self) -> bool:
        return self.disk_state == APPLIED and self.receipt.validation_status == "pending"


def reconcile_one(store: ReceiptStore, receipt: Receipt) -> ReconciledReceipt:
    """Classify one receipt against disk. Never raises for odd paths."""
    # Bash receipts record a command, not a file: their side effects cannot be
    # hash-reconciled (an honest blind spot). Their validation_status already
    # carries the closure signal.
    if receipt.kind == "bash" or not receipt.path.strip():
        return ReconciledReceipt(receipt, COMMAND, "")
    path = Path(receipt.path)
    if path.is_dir():
        return ReconciledReceipt(receipt, MISMATCH, "")
    if not path.exists():
        return ReconciledReceipt(receipt, MISSING, "")
    disk_hash = file_hash(path)
    if disk_hash == receipt.hash_after:
        state = APPLIED
    elif disk_hash == receipt.hash_before:
        state = REVERTED
    else:
        state = MISMATCH
    return ReconciledReceipt(receipt, state, disk_hash)


def reconcile(store: ReceiptStore, *, run_id: str | None = None) -> list[ReconciledReceipt]:
    """Read-only pass: classify every durable receipt against current disk."""
    return [reconcile_one(store, receipt) for receipt in store.all(run_id=run_id)]


def resume_plan(reconciled: list[ReconciledReceipt]) -> tuple[str, list[str]]:
    """Return (overall status, ordered human actions). Never includes a replay.

    The invariant under recovery: an applied side effect is never applied again.
    A reverted patch is reported, not replayed — the user reruns the task, which
    goes through admission again.
    """
    if not reconciled:
        return "clean", []
    actions: list[str] = []
    file_reconciled = [
        item for item in reconciled
        if item.disk_state != COMMAND and item.receipt.validation_status != "dismissed"
    ]
    if any(item.disk_state == APPLIED and item.receipt.validation_status == "pending" for item in file_reconciled):
        actions.append("run /validate <command> on the pending receipts to close them")
    if any(item.disk_state == APPLIED and item.receipt.validation_status == "failed" for item in file_reconciled):
        actions.append("a receipt failed validation; revert or fix the file, then rerun the task")
    if any(item.disk_state == REVERTED for item in file_reconciled):
        actions.append("a receipt's change is no longer on disk; rerun the task if still wanted")
    if any(item.disk_state in (MISMATCH, MISSING) for item in file_reconciled):
        actions.append("a receipt's file changed outside op0; inspect before trusting closure")
    if not actions:
        return "closed", []
    return "indeterminate", actions
