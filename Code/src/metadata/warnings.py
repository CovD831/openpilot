"""Metadata contracts for runtime warning assessment."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from metadata.base import MetadataBase, MetadataKind


class WarningItemMetadata(MetadataBase):
    kind: Literal[MetadataKind.WARNING_ITEM] = MetadataKind.WARNING_ITEM
    warning_text: str
    warning_source: str = ""
    category: str = "runtime_warning"
    severity: str = "info"
    affects_user_experience: bool = False
    requires_fix: bool = False
    reason: str = ""


class WarningCheckResultMetadata(MetadataBase):
    kind: Literal[MetadataKind.WARNING_CHECK_RESULT] = MetadataKind.WARNING_CHECK_RESULT
    command: str = ""
    cwd: str = ""
    warnings: list[WarningItemMetadata] = Field(default_factory=list)
    ignored_warnings: list[WarningItemMetadata] = Field(default_factory=list)
    requires_fix: bool = False
    reason: str = ""
    recommended_fix: str = ""
