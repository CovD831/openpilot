"""Shared parsing and cleanup helpers for pip requirements files."""

from __future__ import annotations

import re
from pathlib import Path

from packaging.requirements import InvalidRequirement, Requirement


_REQUIREMENTS_FILE_PATTERN = re.compile(r"^requirements(?:[-_.].+)?\.txt$", re.IGNORECASE)
_PATH_PREFIXES = (".", "/", "~", "file:")
_VCS_PREFIXES = ("git+", "hg+", "svn+", "bzr+")


def is_requirements_file(path: str | Path) -> bool:
    """Return whether a path names a conventional pip requirements file."""
    return bool(_REQUIREMENTS_FILE_PATTERN.match(Path(path).name))


def invalid_requirement_lines(content: str) -> list[str]:
    """Return non-empty requirements lines that pip cannot reasonably consume."""
    return [
        f"{line_number}: {line.strip()}"
        for line_number, line in enumerate(str(content or "").splitlines(), start=1)
        if not is_supported_requirement_line(line)
    ]


def sanitize_requirements_content(content: str) -> tuple[str, list[str]]:
    """Remove malformed entries while preserving valid pip directives and comments."""
    source_contamination = looks_like_python_source(content)
    if source_contamination:
        removed = [
            f"{line_number}: {line.strip()}"
            for line_number, line in enumerate(str(content or "").splitlines(), start=1)
            if line.strip()
        ]
        return "# OpenPilot removed Python source accidentally written to this requirements file.\n", removed

    removed: list[str] = []
    retained: list[str] = []
    for line_number, line in enumerate(str(content or "").splitlines(keepends=True), start=1):
        if is_supported_requirement_line(line):
            retained.append(line)
            continue
        removed.append(f"{line_number}: {line.strip()}")
    return "".join(retained), removed


def looks_like_python_source(content: str) -> bool:
    """Detect when a dependency file was accidentally populated with Python source."""
    lines = str(content or "").splitlines()
    if any(re.match(r"^#!.*\bpython(?:\d+(?:\.\d+)*)?\b", line.strip()) for line in lines):
        return True
    source_patterns = (
        r"^\s*(?:from\s+\S+\s+import|import\s+\S+)",
        r"^\s*(?:async\s+def|def|class)\s+\w+",
        r"^\s*if\s+__name__\s*==",
    )
    return sum(any(re.match(pattern, line) for pattern in source_patterns) for line in lines) >= 2


def is_supported_requirement_line(line: str) -> bool:
    """Accept PEP 508 requirements plus common pip requirements-file directives."""
    value = str(line or "").strip()
    if not value or value.startswith("#"):
        return True
    if value.startswith(("-", "--")):
        return True
    if value.startswith(_VCS_PREFIXES) or value.startswith(_PATH_PREFIXES):
        return " " not in value
    if "://" in value:
        return " " not in value
    if value.endswith("\\"):
        return True

    requirement = _strip_inline_comment(value)
    if not requirement:
        return True
    try:
        Requirement(requirement)
    except InvalidRequirement:
        return False
    return True


def _strip_inline_comment(value: str) -> str:
    return re.split(r"\s+#", value, maxsplit=1)[0].strip()
