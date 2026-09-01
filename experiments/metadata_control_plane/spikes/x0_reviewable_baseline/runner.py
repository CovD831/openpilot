from __future__ import annotations

import argparse
import json
import re
import subprocess
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


RUNNER_VERSION = "x0-reviewable-baseline-v2"
DEFAULT_DECISION = "needs_owner_decision"
BASELINE_PIN_FILENAME = "b1_baseline.json"
FULL_COMMIT_PATTERN = re.compile(r"[0-9a-f]{40}")
REFERENCE_ROOTS = (
    "AGENTS.md",
    "API.md",
    "README.md",
    "Code/README.md",
    "docs",
)
SKIP_PARTS = {".git", ".venv", "node_modules", "tmp", "runs"}
ALLOWED_GIT_INVOCATIONS = {
    ("status", "--porcelain=v1", "-z"),
    ("ls-files", "--deleted", "-z"),
    ("branch", "--show-current"),
    ("rev-parse", "HEAD"),
}


@dataclass(frozen=True)
class ProtectedCollection:
    path: str
    owner: str


def repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def require_read_only_git_invocation(args: tuple[str, ...]) -> None:
    if args not in ALLOWED_GIT_INVOCATIONS:
        raise ValueError(f"X0 refuses non-allowlisted git invocation: {args!r}")


def run_git(root: Path, *args: str) -> str:
    require_read_only_git_invocation(args)
    completed = subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return completed.stdout.strip()


def run_git_z(root: Path, *args: str) -> list[str]:
    require_read_only_git_invocation(args)
    completed = subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return [item.decode("utf-8", errors="surrogateescape") for item in completed.stdout.split(b"\0") if item]


def load_collections(path: Path) -> list[ProtectedCollection]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return [ProtectedCollection(**item) for item in payload["collections"]]


def load_baseline_pin(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    required = {
        "baseline_id",
        "pin_type",
        "source_commit",
        "working_tree_included",
        "dirty_worktree_policy",
    }
    missing = sorted(required - set(payload))
    if missing:
        raise ValueError(f"B1 baseline pin missing fields: {missing}")
    commit = payload["source_commit"]
    if not isinstance(commit, str) or FULL_COMMIT_PATTERN.fullmatch(commit) is None:
        raise ValueError("B1 source_commit must be a full Git commit identity")
    if payload["pin_type"] != "git_commit":
        raise ValueError("B1 pin_type must be git_commit")
    if payload["working_tree_included"] is not False:
        raise ValueError("B1 must exclude the working tree")
    if payload["dirty_worktree_policy"] != "excluded":
        raise ValueError("B1 dirty_worktree_policy must be excluded")
    return payload


def verify_baseline_commit(root: Path, commit: str) -> None:
    if FULL_COMMIT_PATTERN.fullmatch(commit) is None:
        raise ValueError("B1 source_commit must be a full Git commit identity")
    subprocess.run(
        ["git", "cat-file", "-e", f"{commit}^{{commit}}"],
        cwd=root,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def collection_for(path: str, collections: Iterable[ProtectedCollection]) -> ProtectedCollection | None:
    normalized = path.rstrip("/")
    for collection in collections:
        prefix = collection.path.rstrip("/")
        if normalized == prefix or normalized.startswith(prefix + "/"):
            return collection
    return None


def parse_status(entries: list[str]) -> list[dict[str, str]]:
    parsed: list[dict[str, str]] = []
    index = 0
    while index < len(entries):
        item = entries[index]
        status = item[:2]
        path = item[3:]
        record = {"status": status, "path": path}
        if "R" in status or "C" in status:
            index += 1
            if index >= len(entries):
                raise ValueError("rename/copy status is missing its source path")
            record["source_path"] = entries[index]
        parsed.append(record)
        index += 1
    return parsed


def module_owner(path: str) -> str:
    prefixes = (
        ("Code/src/metadata/", "metadata"),
        ("Code/src/autonomous_iteration/", "autonomous_iteration"),
        ("Code/src/memory/", "memory"),
        ("Code/src/core/", "core"),
        ("Code/src/tools/", "tools"),
        ("Code/src/ui/", "ui"),
        ("Code/src/utils/", "utils"),
    )
    for prefix, owner in prefixes:
        if path.startswith(prefix):
            return owner
    return "other_or_unclassified"


def iter_reference_files(root: Path) -> Iterable[Path]:
    for relative in REFERENCE_ROOTS:
        candidate = root / relative
        if candidate.is_file():
            yield candidate
            continue
        if not candidate.is_dir():
            continue
        for path in candidate.rglob("*"):
            if not path.is_file() or any(part in SKIP_PARTS for part in path.parts):
                continue
            if path.stat().st_size > 2_000_000:
                continue
            yield path


def scan_references(root: Path, needles: set[str]) -> dict[str, list[dict[str, object]]]:
    results = {needle: [] for needle in needles}
    if not needles:
        return results
    for path in iter_reference_files(root):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (UnicodeDecodeError, OSError):
            continue
        relative = path.relative_to(root).as_posix()
        for line_number, line in enumerate(lines, start=1):
            for needle in needles:
                if needle in line:
                    results[needle].append(
                        {"file": relative, "line": line_number}
                    )
    return results


def build_snapshot(root: Path, collections: list[ProtectedCollection]) -> dict[str, object]:
    status_entries = parse_status(run_git_z(root, "status", "--porcelain=v1", "-z"))
    deleted_tracked = sorted(run_git_z(root, "ls-files", "--deleted", "-z"))
    protected_deleted = [
        path for path in deleted_tracked if collection_for(path, collections) is not None
    ]
    collection_needles = {collection.path for collection in collections}
    reference_map = scan_references(root, set(protected_deleted) | collection_needles)

    adjudication: list[dict[str, object]] = []
    for path in protected_deleted:
        collection = collection_for(path, collections)
        assert collection is not None
        adjudication.append(
            {
                "path": path,
                "collection": collection.path,
                "owner": collection.owner,
                "decision": DEFAULT_DECISION,
                "replacement_path": None,
                "references": reference_map.get(path, []),
                "collection_references": reference_map.get(collection.path, []),
            }
        )

    status_counts = Counter(entry["status"] for entry in status_entries)
    source_changes = [
        {**entry, "owner": module_owner(entry["path"])}
        for entry in status_entries
        if entry["path"].startswith("Code/src/")
    ]
    collection_counts = Counter(item["collection"] for item in adjudication)
    return {
        "branch": run_git(root, "branch", "--show-current"),
        "head_commit": run_git(root, "rev-parse", "HEAD"),
        "status_counts": dict(sorted(status_counts.items())),
        "dirty_path_count": len(status_entries),
        "status_entries": status_entries,
        "source_changes": source_changes,
        "deleted_tracked_count": len(deleted_tracked),
        "deleted_tracked_paths": deleted_tracked,
        "protected_deleted_count": len(protected_deleted),
        "protected_deleted_by_collection": dict(sorted(collection_counts.items())),
        "deletion_adjudication": adjudication,
        "collection_references": {
            collection.path: reference_map.get(collection.path, [])
            for collection in collections
        },
    }


def build_analysis(
    snapshot: dict[str, object],
    baseline_pin: dict[str, object] | None = None,
) -> dict[str, object]:
    unresolved = int(snapshot["protected_deleted_count"])
    baseline_pinned = baseline_pin is not None
    adjudication = list(snapshot.get("deletion_adjudication", []))
    exact_reference_count = sum(len(item["references"]) for item in adjudication)
    collection_reference_count = sum(
        len(items) for items in dict(snapshot.get("collection_references", {})).values()
    )
    current_authority_files = {"AGENTS.md", "API.md", "README.md", "Code/README.md"}
    current_authority_references = sorted(
        {
            reference["file"]
            for item in adjudication
            for reference in [*item["references"], *item["collection_references"]]
            if reference["file"] in current_authority_files
        }
    )
    if unresolved:
        verdict = "blocked_pending_owner_adjudication"
    elif not baseline_pinned:
        verdict = "blocked_pending_b1_pin"
    else:
        verdict = "reviewable_baseline_ready"
    if baseline_pinned:
        b1_status = (
            "pinned_commit_dirty_worktree_excluded"
            if int(snapshot["dirty_path_count"])
            else "pinned_commit_clean_worktree"
        )
    else:
        b1_status = (
            "unfrozen_dirty_worktree"
            if int(snapshot["dirty_path_count"])
            else "clean_head_candidate"
        )
    if unresolved:
        next_action = "owner_adjudication_restore_or_H4"
    elif not baseline_pinned:
        next_action = "owner_review_and_pin_b1_commit"
    else:
        next_action = "review_package_without_broad_staging"
    return {
        "verdict": verdict,
        "development_package_release_allowed": unresolved == 0 and baseline_pinned,
        "b1_baseline_status": b1_status,
        "b1_baseline_id": baseline_pin.get("baseline_id") if baseline_pin else None,
        "b1_baseline_commit": baseline_pin.get("source_commit") if baseline_pin else None,
        "b1_working_tree_included": (
            baseline_pin.get("working_tree_included") if baseline_pin else None
        ),
        "unresolved_protected_deletions": unresolved,
        "exact_deleted_path_reference_count": exact_reference_count,
        "protected_collection_reference_count": collection_reference_count,
        "current_authority_reference_files": current_authority_references,
        "current_authority_conflict_detected": bool(current_authority_references),
        "historical_evidence_mutations_performed": 0,
        "provider_calls": 0,
        "network_calls": 0,
        "required_next_action": next_action,
    }


def write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def write_run(output: Path, snapshot: dict[str, object], analysis: dict[str, object]) -> None:
    if output.exists():
        raise FileExistsError(f"refusing to overwrite existing X0 run: {output}")
    output.mkdir(parents=True)
    generated_at = datetime.now(timezone.utc).isoformat()
    preflight = {
        "runner_version": RUNNER_VERSION,
        "generated_at": generated_at,
        "read_only_git_commands": True,
        "b1_baseline_id": analysis["b1_baseline_id"],
        "b1_baseline_commit": analysis["b1_baseline_commit"],
        "b1_working_tree_included": analysis["b1_working_tree_included"],
        "provider_calls": 0,
        "network_calls": 0,
        "historical_evidence_mutations": 0,
    }
    inventory = {key: value for key, value in snapshot.items() if key != "deletion_adjudication"}
    write_json(output / "preflight.json", preflight)
    write_json(output / "inventory.json", inventory)
    write_json(output / "deletion_adjudication.json", snapshot["deletion_adjudication"])
    write_json(output / "analysis.json", analysis)
    adjudication = list(snapshot["deletion_adjudication"])
    collection_rows: dict[str, dict[str, object]] = {}
    for item in adjudication:
        row = collection_rows.setdefault(
            item["collection"],
            {
                "owner": item["owner"],
                "deleted": 0,
                "exact_references": 0,
                "collection_references": len(item["collection_references"]),
            },
        )
        row["deleted"] = int(row["deleted"]) + 1
        row["exact_references"] = int(row["exact_references"]) + len(item["references"])
    decision_lines = [
        "# X0 Historical Evidence Owner Decision",
        "",
        f"- Verdict: `{analysis['verdict']}`",
        f"- Protected tracked deletions: `{snapshot['protected_deleted_count']}`",
        f"- Current-authority conflict: `{analysis['current_authority_conflict_detected']}`",
        "- Mutation performed by X0: `0`",
        "",
        "| Collection | Owner | Deleted | Exact path refs | Collection refs | Decision |",
        "| --- | --- | ---: | ---: | ---: | --- |",
    ]
    for collection, row in sorted(collection_rows.items()):
        decision_lines.append(
            f"| `{collection}` | `{row['owner']}` | {row['deleted']} | "
            f"{row['exact_references']} | {row['collection_references']} | "
            f"`{DEFAULT_DECISION}` |"
        )
    if collection_rows:
        decision_lines.extend(
            [
                "",
                "## Required owner decision",
                "",
                "逐路径明细见 `deletion_adjudication.json`。用户/owner 必须明确选择 "
                "`restore_from_head`、`retain_intentional_deletion_pending_H4` 或 "
                "`replaced_by_new_collection`；在此之前 package release 保持阻塞。",
                "",
                "X0 不执行 restore/delete/stage，也不把当前 dirty HEAD 自动批准为 B1。",
                "",
            ]
        )
    else:
        decision_lines.extend(
            [
                "",
                "## Resolution",
                "",
                "当前没有 protected tracked deletion；本 run 不再要求删除项 owner 裁决。",
                "历史 restore/replacement/H4 动作仍由独立 adjudication evidence 记录。",
                "",
            ]
        )
    (output / "OWNER_DECISION_CN.md").write_text(
        "\n".join(decision_lines), encoding="utf-8"
    )
    note = f"""# X0 Run Note

- Verdict: `{analysis['verdict']}`
- Branch: `{snapshot['branch']}`
- Dirty paths: `{snapshot['dirty_path_count']}`
- Tracked deletions: `{snapshot['deleted_tracked_count']}`
- Protected tracked deletions: `{snapshot['protected_deleted_count']}`
- B1 baseline status: `{analysis['b1_baseline_status']}`
- B1 baseline ID: `{analysis['b1_baseline_id']}`
- B1 commit: `{analysis['b1_baseline_commit']}`
- Working tree included in B1: `{analysis['b1_working_tree_included']}`
- Historical evidence mutations performed: `0`
- Provider/network calls: `0/0`

本 run 只记录 Git/path/reference evidence，不执行恢复、删除、暂存或覆盖。B1 只能来自
owner-reviewed commit pin；当前 dirty worktree 不属于 B1。
"""
    (output / "RUN_NOTE_CN.md").write_text(note, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--baseline-pin", type=Path)
    args = parser.parse_args()
    root = repo_root()
    collections = load_collections(Path(__file__).with_name("protected_collections.json"))
    baseline_path = args.baseline_pin or Path(__file__).with_name(BASELINE_PIN_FILENAME)
    if not baseline_path.is_absolute():
        baseline_path = root / baseline_path
    baseline_pin = load_baseline_pin(baseline_path) if baseline_path.exists() else None
    if baseline_pin is not None:
        verify_baseline_commit(root, str(baseline_pin["source_commit"]))
    snapshot = build_snapshot(root, collections)
    analysis = build_analysis(snapshot, baseline_pin=baseline_pin)
    if args.output is not None:
        output = args.output if args.output.is_absolute() else root / args.output
        write_run(output, snapshot, analysis)
    print(json.dumps(analysis, ensure_ascii=False, sort_keys=True))
    if args.check and not analysis["development_package_release_allowed"]:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
