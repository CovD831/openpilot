"""Bundle helpers for copying a run into a portable directory."""

from __future__ import annotations

import shutil
from pathlib import Path


def copy_run_bundle(run_dir: str | Path, target_dir: str | Path) -> Path:
    source = Path(run_dir)
    if not source.exists():
        raise FileNotFoundError(source)
    target_root = Path(target_dir)
    target = target_root / source.name
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True, exist_ok=True)

    for name in ("run.json", "events.jsonl", "summary.json", "artifacts.jsonl"):
        candidate = source / name
        if candidate.exists():
            shutil.copy2(candidate, target / name)

    artifacts_source = source / "artifacts"
    if artifacts_source.exists():
        shutil.copytree(artifacts_source, target / "artifacts")

    return target
