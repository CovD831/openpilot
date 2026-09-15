"""No-follow file identity snapshots for admitted mutations.

The helpers deliberately use filesystem identity and timestamps rather than a
content digest.  A mutation admission owns the immutable snapshot; callers use
this module only to capture or verify that the same regular file remains in
place immediately before a side effect.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

from metadata import FileMutationPrecondition


class FileMutationPreconditionError(PermissionError):
    """Raised when a mutation target is missing, unsafe, or has drifted."""


def capture_file_mutation_precondition(path: str | Path) -> FileMutationPrecondition:
    """Capture one existing regular file without following a final symlink."""

    target = _absolute_path(path)
    try:
        observed = os.stat(target, follow_symlinks=False)
    except OSError as exc:
        raise FileMutationPreconditionError(
            f"cannot capture file mutation precondition for {target}: {exc}"
        ) from exc
    return file_mutation_precondition_from_stat(target, observed)


def file_mutation_precondition_from_stat(
    path: str | Path,
    observed: os.stat_result,
) -> FileMutationPrecondition:
    """Build a snapshot from an already-open descriptor's ``fstat`` result."""

    target = _absolute_path(path)
    _require_regular_file(target, observed)
    return FileMutationPrecondition(
        path=str(target),
        device=int(observed.st_dev),
        inode=int(observed.st_ino),
        size_bytes=int(observed.st_size),
        mtime_ns=int(observed.st_mtime_ns),
    )


def assert_file_mutation_precondition(
    path: str | Path,
    expected: FileMutationPrecondition,
    *,
    observed: os.stat_result | None = None,
) -> None:
    """Fail closed unless ``path`` still matches an admitted snapshot."""

    target = _absolute_path(path)
    if str(target) != expected.path:
        raise FileMutationPreconditionError(
            "file mutation precondition path does not match the admitted target"
        )
    if observed is None:
        try:
            observed = os.stat(target, follow_symlinks=False)
        except OSError as exc:
            raise FileMutationPreconditionError(
                f"file mutation precondition target is unavailable: {target}"
            ) from exc
    actual = file_mutation_precondition_from_stat(target, observed)
    if actual != expected:
        raise FileMutationPreconditionError(
            f"file mutation precondition changed since admission: {target}"
        )


def _absolute_path(path: str | Path) -> Path:
    return Path(path).expanduser().absolute()


def _require_regular_file(path: Path, observed: os.stat_result) -> None:
    if stat.S_ISLNK(observed.st_mode):
        raise FileMutationPreconditionError(
            f"file mutation target must not be a symbolic link: {path}"
        )
    if not stat.S_ISREG(observed.st_mode):
        raise FileMutationPreconditionError(
            f"file mutation target must be an existing regular file: {path}"
        )


__all__ = [
    "FileMutationPreconditionError",
    "assert_file_mutation_precondition",
    "capture_file_mutation_precondition",
    "file_mutation_precondition_from_stat",
]
