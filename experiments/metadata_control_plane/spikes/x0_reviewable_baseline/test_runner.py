from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("runner.py")
SPEC = importlib.util.spec_from_file_location("x0_runner", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
RUNNER = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = RUNNER
SPEC.loader.exec_module(RUNNER)


def test_collection_for_uses_path_boundary() -> None:
    collections = [RUNNER.ProtectedCollection(path="experiments/evidence", owner="owner")]
    assert RUNNER.collection_for("experiments/evidence/a.json", collections) == collections[0]
    assert RUNNER.collection_for("experiments/evidence_other/a.json", collections) is None


def test_parse_status_preserves_status_and_paths() -> None:
    rows = RUNNER.parse_status([" M Code/src/core/a.py", "?? docs/new file.md"])
    assert rows == [
        {"status": " M", "path": "Code/src/core/a.py"},
        {"status": "??", "path": "docs/new file.md"},
    ]


def test_git_invocation_allowlist_rejects_mutation() -> None:
    RUNNER.require_read_only_git_invocation(("status", "--porcelain=v1", "-z"))
    try:
        RUNNER.require_read_only_git_invocation(("restore", "experiments/evidence"))
    except ValueError as exc:
        assert "refuses non-allowlisted" in str(exc)
    else:
        raise AssertionError("mutation-capable git invocation was not rejected")


def test_build_analysis_blocks_unresolved_protected_deletions() -> None:
    result = RUNNER.build_analysis(
        {
            "protected_deleted_count": 2,
            "dirty_path_count": 5,
            "deletion_adjudication": [],
            "collection_references": {},
        }
    )
    assert result["verdict"] == "blocked_pending_owner_adjudication"
    assert result["development_package_release_allowed"] is False
    assert result["historical_evidence_mutations_performed"] == 0


def test_build_analysis_requires_explicit_b1_pin_after_adjudication() -> None:
    result = RUNNER.build_analysis(
        {
            "protected_deleted_count": 0,
            "dirty_path_count": 0,
            "deletion_adjudication": [],
            "collection_references": {},
        }
    )
    assert result["verdict"] == "blocked_pending_b1_pin"
    assert result["development_package_release_allowed"] is False
    assert result["b1_baseline_status"] == "clean_head_candidate"


def test_build_analysis_accepts_pinned_commit_and_excludes_dirty_worktree() -> None:
    baseline_pin = {
        "baseline_id": "B1-openpilot-pi-only-v1",
        "pin_type": "git_commit",
        "source_commit": "a" * 40,
        "working_tree_included": False,
        "dirty_worktree_policy": "excluded",
    }
    result = RUNNER.build_analysis(
        {
            "protected_deleted_count": 0,
            "dirty_path_count": 5,
            "deletion_adjudication": [],
            "collection_references": {},
        },
        baseline_pin=baseline_pin,
    )
    assert result["verdict"] == "reviewable_baseline_ready"
    assert result["development_package_release_allowed"] is True
    assert result["b1_baseline_status"] == "pinned_commit_dirty_worktree_excluded"
    assert result["b1_baseline_commit"] == "a" * 40
    assert result["b1_working_tree_included"] is False


def test_load_baseline_pin_rejects_non_commit_or_worktree_inclusion(tmp_path: Path) -> None:
    pin_path = tmp_path / "b1_baseline.json"
    pin_path.write_text(
        """{
  "baseline_id": "B1-openpilot-pi-only-v1",
  "pin_type": "git_commit",
  "source_commit": "not-a-commit",
  "working_tree_included": true,
  "dirty_worktree_policy": "included"
}
""",
        encoding="utf-8",
    )
    try:
        RUNNER.load_baseline_pin(pin_path)
    except ValueError as exc:
        assert "full Git commit" in str(exc)
    else:
        raise AssertionError("invalid baseline pin was not rejected")


def test_load_baseline_pin_rejects_dirty_worktree_inclusion(tmp_path: Path) -> None:
    pin_path = tmp_path / "b1_baseline.json"
    pin_path.write_text(
        f"""{{
  "baseline_id": "B1-openpilot-pi-only-v1",
  "pin_type": "git_commit",
  "source_commit": "{'a' * 40}",
  "working_tree_included": true,
  "dirty_worktree_policy": "included"
}}
""",
        encoding="utf-8",
    )
    try:
        RUNNER.load_baseline_pin(pin_path)
    except ValueError as exc:
        assert "exclude the working tree" in str(exc)
    else:
        raise AssertionError("dirty-worktree baseline pin was not rejected")


def test_reference_scan_records_file_and_line(tmp_path: Path) -> None:
    (tmp_path / "API.md").write_text(
        "see experiments/example_collection and experiments/example_collection/a.json\n",
        encoding="utf-8",
    )
    results = RUNNER.scan_references(
        tmp_path,
        {"experiments/example_collection", "experiments/example_collection/a.json"},
    )
    assert results["experiments/example_collection"] == [{"file": "API.md", "line": 1}]
    assert results["experiments/example_collection/a.json"] == [
        {"file": "API.md", "line": 1}
    ]
