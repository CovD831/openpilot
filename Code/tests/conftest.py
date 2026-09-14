"""Shared test-suite policy for the openpilot test tree.

Two concerns are handled here.

1. Temporary directories.
   ``pytest``'s ``tmp_path`` fixture derives its base from ``TMPDIR``.  In this
   repository a stale ``pytest-of-root`` / ``pytest-of-unknown`` directory can
   make every fixture setup fail with ``PermissionError: EEXIST``.  Worse, if
   ``TMPDIR`` points *inside* the project, the generated files get picked up by
   the project indexer and pollute ``.openpilot/file_indexes``.

   There is no ``pyproject.toml`` pytest configuration in this repository, so
   the fallback is applied here instead.

2. Orphaned experiment-scaffold tests.
   Four test modules under ``tests/`` exercise a quality-gate helper
   (``_quality_check``) that lives only in ``experiments/`` harness scripts and
   was never promoted into ``Code/src/``.  Their target scripts were removed
   during an experiments rename (``stageNN_*`` -> ``stage_h8r2*``) and were
   never tracked by git, so the modules cannot even be collected.

   The helper's output contract (``forbidden_relations``,
   ``missing_requirements``, ``negative_markers``) appears in zero production
   files.  The tests are therefore skipped with an explicit reason rather than
   deleted, so the assertions remain recoverable if the harness is revived.
   See ``experiments/harness_slimming/SLIMMING_INVENTORY.md`` section 10.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest


# --------------------------------------------------------------------------
# 1. Keep pytest's temporary directory outside the project tree.
# --------------------------------------------------------------------------

def _ensure_tmpdir_outside_project() -> None:
    """Point TMPDIR at a writable location that is not inside the repository."""
    project_root = Path(__file__).resolve().parents[2]
    configured = os.environ.get("TMPDIR", "")
    if configured:
        try:
            resolved = Path(configured).resolve()
        except OSError:
            resolved = None
        # Accept the configured value only if it is writable and outside the repo.
        if resolved is not None and project_root not in resolved.parents:
            if os.access(str(resolved), os.W_OK):
                return

    candidate = Path(tempfile.gettempdir()) / "openpilot-pytest-tmp"
    try:
        candidate.mkdir(parents=True, exist_ok=True)
    except OSError:
        return
    os.environ["TMPDIR"] = str(candidate)


_ensure_tmpdir_outside_project()


# --------------------------------------------------------------------------
# 2. Give pytest a private, freshly created base temp directory.
# --------------------------------------------------------------------------
# ``tmp_path`` derives its base from ``pytest-of-<user>`` under TMPDIR, where
# ``<user>`` comes from ``getpass.getuser()``.  In restricted environments that
# can resolve to ``root`` or ``unknown``, and a pre-existing directory with that
# name (often owned by a different account) makes *every* ``tmp_path`` fixture
# fail with ``PermissionError: EEXIST``.
#
# Creating our own base under TMPDIR with a private name avoids depending on
# ``getpass`` entirely and keeps the directory outside the repository.

def _private_basetemp_root() -> str | None:
    base = Path(tempfile.gettempdir()) / "openpilot-pytest-basetemp"
    try:
        base.mkdir(parents=True, exist_ok=True)
    except OSError:
        return None
    if not os.access(str(base), os.W_OK):
        return None
    return str(base)


def pytest_configure(config) -> None:
    """Force a writable, per-run base temp directory for ``tmp_path``."""
    root = _private_basetemp_root()
    if root is None:
        return
    # ``--basetemp`` also clears the target directory, so nest one level per PID
    # to keep concurrent runs from deleting each other's fixtures.
    target = Path(root) / f"run-{os.getpid()}"
    config.option.basetemp = str(target)


# --------------------------------------------------------------------------
# 2. Skip the orphaned experiment-scaffold tests with a documented reason.
# --------------------------------------------------------------------------

_ORPHANED_EXPERIMENT_TESTS = {
    "test_phase28_quality.py":
        "loads experiments/.../stage25_budget_profile_task_matrix.py, which was "
        "removed in the stageNN_* -> stage_h8r2* experiments rename",
    "test_phase28_fully_scoped_task.py":
        "loads experiments/.../stage28_fully_scoped_task_repetition.py, which was "
        "removed in the stageNN_* -> stage_h8r2* experiments rename",
    "test_phase30_projection_matrix.py":
        "loads experiments/.../stage30_fully_scoped_projection_matrix.py, which was "
        "removed in the stageNN_* -> stage_h8r2* experiments rename",
    "test_phase31_scope_boundary_refusal.py":
        "loads experiments/.../stage31_scope_boundary_refusal.py, which was "
        "removed in the stageNN_* -> stage_h8r2* experiments rename",
}


def pytest_collection_modifyitems(config, items) -> None:
    """Mark orphaned experiment-scaffold tests as skipped, with the reason."""
    for item in items:
        filename = Path(str(item.fspath)).name
        reason = _ORPHANED_EXPERIMENT_TESTS.get(filename)
        if reason is not None:
            item.add_marker(
                pytest.mark.skip(
                    reason=(
                        "orphaned experiment scaffold: this test targets a quality-gate "
                        f"helper that exists only in experiments/, not in Code/src/. {reason}"
                    )
                )
            )


# --------------------------------------------------------------------------
# 3. Ignore the orphaned modules at collection time.
# --------------------------------------------------------------------------
# ``pytest_collection_modifyitems`` runs after a module has been imported, so a
# module-level ``importlib`` load of a missing script aborts collection before
# any skip marker can apply.  These modules are therefore excluded from
# collection entirely; the skip reason above still documents why.

collect_ignore = sorted(_ORPHANED_EXPERIMENT_TESTS)
