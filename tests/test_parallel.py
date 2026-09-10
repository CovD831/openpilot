"""Phase 2: parallel delegation primitives — worktree lifecycle, registry races."""

from __future__ import annotations

import subprocess
import threading
from pathlib import Path

from op0.admission import AdmissionRegistry
from op0.cli import dispose_worktree, make_worktree


def _git_repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.email", "e@x"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "t"], check=True)
    (tmp_path / "seed.txt").write_text("seed\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-qm", "seed"], check=True)
    return tmp_path


def test_worktree_clean_checkout_is_removed(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path / "repo")
    path, branch = make_worktree(str(repo))
    assert Path(path).is_dir()
    kept = dispose_worktree(str(repo), path, branch)
    assert kept == ""  # clean checkout: removed, branch dropped
    assert not Path(path).exists()
    branches = subprocess.run(["git", "-C", str(repo), "branch", "--list", branch],
                              capture_output=True, text=True).stdout
    assert branch not in branches


def test_worktree_dirty_is_kept_for_human_review(tmp_path: Path) -> None:
    repo = _git_repo(tmp_path / "repo")
    path, branch = make_worktree(str(repo))
    (Path(path) / "work.txt").write_text("changed\n", encoding="utf-8")
    kept = dispose_worktree(str(repo), path, branch)
    assert path in kept and branch in kept  # merge or drop: a human decision
    assert Path(path).exists()  # kept
    subprocess.run(["git", "-C", str(repo), "worktree", "remove", "--force", path], check=True)


def test_registry_survives_parallel_proposals(tmp_path: Path) -> None:
    registry = AdmissionRegistry(str(tmp_path))
    ids: list[str] = []
    lock = threading.Lock()

    def propose_many(thread: int) -> None:
        for i in range(20):
            proposal = registry.propose(f"goal {thread}", str(tmp_path / f"f{thread}-{i}"),
                                        (str(tmp_path),), kind="write")
            registry.approve(proposal.proposal_id, f"run-{thread}-{i}")  # keep pending under MAX_PENDING
            with lock:
                ids.append(proposal.proposal_id)

    threads = [threading.Thread(target=propose_many, args=(t,)) for t in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(ids) == 160 and len(set(ids)) == 160  # no id collisions, no lost proposals
