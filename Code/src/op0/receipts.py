"""L2 durable receipts and closure.

A patch that touched disk produces a durable receipt (file hashes before and
after) under <project>/.openpilot/receipts/. A run closes only on validation
evidence: passed -> success, failed -> failed, receipt without validation ->
indeterminate. What the model says about its own work is never evidence.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

RECEIPTS_DIRNAME = "receipts"


@dataclass(frozen=True)
class Receipt:
    receipt_id: str
    run_id: str
    consent_id: str
    proposal_id: str
    admission_id: str
    path: str
    hash_before: str
    hash_after: str
    created_at: str
    validation_command: str = ""
    validation_status: str = "pending"  # pending | passed | failed
    validation_detail: str = ""
    validation_at: str = ""
    kind: str = "patch"  # patch | write | bash
    command: str = ""    # bash receipts carry the exact command
    exit_code: int | None = None
    output_tail: str = ""

    def to_json(self) -> str:
        return json.dumps(
            {k: getattr(self, k) for k in self.__dataclass_fields__},
            ensure_ascii=False,
            indent=2,
        )


def file_hash(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class ReceiptStore:
    """Durable receipt storage; the file on disk is the authority, not memory."""

    def __init__(self, project_root: str | Path) -> None:
        self.dir = Path(project_root).expanduser().resolve() / ".openpilot" / RECEIPTS_DIRNAME
        self.dir.mkdir(parents=True, exist_ok=True)

    def _path(self, receipt_id: str) -> Path:
        return self.dir / f"{receipt_id}.json"

    def write_patch_receipt(
        self,
        *,
        run_id: str,
        consent_id: str,
        proposal_id: str,
        admission_id: str,
        path: str,
        hash_before: str,
        hash_after: str,
        validation_command: str,
        kind: str = "patch",
    ) -> Receipt:
        receipt = Receipt(
            receipt_id=f"rcp_{uuid4().hex[:12]}",
            run_id=run_id,
            consent_id=consent_id,
            proposal_id=proposal_id,
            admission_id=admission_id,
            path=str(path),
            hash_before=hash_before,
            hash_after=hash_after,
            created_at=datetime.now(UTC).isoformat(),
            validation_command=validation_command,
            validation_status="pending",
            kind=kind,
        )
        self._path(receipt.receipt_id).write_text(receipt.to_json(), encoding="utf-8")
        return receipt

    def write_bash_receipt(
        self,
        *,
        run_id: str,
        consent_id: str,
        proposal_id: str,
        admission_id: str,
        command: str,
        exit_code: int,
        output_tail: str,
    ) -> Receipt:
        receipt = Receipt(
            receipt_id=f"rcp_{uuid4().hex[:12]}",
            run_id=run_id,
            consent_id=consent_id,
            proposal_id=proposal_id,
            admission_id=admission_id,
            path="",
            hash_before="n/a",
            hash_after="n/a",
            created_at=datetime.now(UTC).isoformat(),
            validation_status="passed" if exit_code == 0 else "pending",
            kind="bash",
            command=command,
            exit_code=exit_code,
            output_tail=output_tail[-2000:],
        )
        self._path(receipt.receipt_id).write_text(receipt.to_json(), encoding="utf-8")
        return receipt

    def load(self, receipt_id: str) -> Receipt | None:
        path = self._path(receipt_id)
        if not path.exists():
            return None
        raw = json.loads(path.read_text(encoding="utf-8"))
        return Receipt(**raw)

    def save(self, receipt: Receipt) -> None:
        self._path(receipt.receipt_id).write_text(receipt.to_json(), encoding="utf-8")

    def all(self, *, run_id: str | None = None) -> list[Receipt]:
        receipts: list[Receipt] = []
        for path in sorted(self.dir.glob("rcp_*.json")):
            try:
                receipt = Receipt(**json.loads(path.read_text(encoding="utf-8")))
            except (json.JSONDecodeError, TypeError):
                continue
            if run_id is None or receipt.run_id == run_id:
                receipts.append(receipt)
        return receipts

    def pending_for_run(self, run_id: str) -> list[Receipt]:
        return [r for r in self.all(run_id=run_id) if r.validation_status == "pending"]


def record_validation(
    store: ReceiptStore,
    receipt: Receipt,
    *,
    command: str,
    timeout_seconds: float = 120.0,
    cwd: str | None = None,
) -> tuple[Receipt, subprocess.CompletedProcess[str]]:
    """Run the exact validation command once and write the outcome durably."""
    completed = subprocess.run(
        command,
        shell=True,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        cwd=cwd,
    )
    updated = Receipt(
        **{
            **receipt.__dict__,
            "validation_command": command,
            "validation_status": "passed" if completed.returncode == 0 else "failed",
            "validation_detail": (completed.stdout or completed.stderr or "")[-2000:],
            "validation_at": datetime.now(UTC).isoformat(),
        }
    )
    store.save(updated)
    return updated, completed


def decide_closure(receipts: list[Receipt], *, saw_model_response: bool) -> tuple[str, str]:
    """Closure decision from evidence only; saw_model_response never upgrades it."""
    if not receipts:
        if saw_model_response:
            return "success", "read-only run with an observed model response"
        return "blocked", "no model response and no receipts"
    statuses = {receipt.validation_status for receipt in receipts}
    if "failed" in statuses:
        return "failed", "a durable receipt's validation failed"
    if "pending" in statuses:
        return "indeterminate", "durable receipt without validation; reconcile with /validate"
    return "success", "all durable receipts validated"
