"""Shared Python import-name and distribution-name helpers."""

from __future__ import annotations

import re


IMPORT_TO_DISTRIBUTION = {
    "pygame": "pygame",
    "PIL": "Pillow",
    "cv2": "opencv-python",
    "yaml": "PyYAML",
    "sklearn": "scikit-learn",
    "speech_recognition": "SpeechRecognition",
}


def distribution_for_import(import_name: str) -> str:
    """Return the installable distribution for a top-level Python import."""
    return IMPORT_TO_DISTRIBUTION.get(str(import_name or "").strip(), str(import_name or "").strip())


def canonical_distribution_name(value: str) -> str:
    """Normalize a package name using the comparison form defined by Python packaging."""
    return re.sub(r"[-_.]+", "-", str(value or "").strip()).lower()


def compact_distribution_name(value: str) -> str:
    """Normalize separators away when comparing import names with distribution names."""
    return re.sub(r"[-_.]+", "", str(value or "").strip()).lower()


def requirement_name(requirement: str) -> str:
    """Extract the distribution name from a simple requirements.txt entry."""
    match = re.match(r"^\s*([A-Za-z0-9][A-Za-z0-9_.-]*)", str(requirement or ""))
    return match.group(1) if match else ""


def replace_requirement_name(requirement: str, replacement: str) -> str:
    """Replace only the distribution name, preserving extras, versions, markers, and comments."""
    return re.sub(
        r"^(\s*)[A-Za-z0-9][A-Za-z0-9_.-]*",
        rf"\g<1>{replacement}",
        str(requirement or ""),
        count=1,
    )


def plausible_distribution_alias(source: str, candidate: str) -> bool:
    """Accept conservative aliases that differ only by packaging separators or a known import mapping."""
    source_name = requirement_name(source) or str(source or "").strip()
    candidate_name = requirement_name(candidate) or str(candidate or "").strip()
    if not source_name or not candidate_name:
        return False
    known_distribution = distribution_for_import(source_name)
    return (
        canonical_distribution_name(source_name) == canonical_distribution_name(candidate_name)
        or compact_distribution_name(source_name) == compact_distribution_name(candidate_name)
        or canonical_distribution_name(known_distribution) == canonical_distribution_name(candidate_name)
    )
