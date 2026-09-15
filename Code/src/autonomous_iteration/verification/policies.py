"""Typed Harness policy profiles with phase-scoped Pi affordances."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class HarnessPolicyKind(StrEnum):
    READ_ONLY = "read_only"
    DEVELOPER = "developer"
    WORKFLOW = "workflow"
    APPROVAL_REQUIRED = "approval_required"


class HarnessPhase(StrEnum):
    PLAN = "plan"
    ACT = "act"
    VERIFY = "verify"


@dataclass(frozen=True)
class HarnessPolicyProfile:
    kind: HarnessPolicyKind
    mutation_allowed: bool
    approval_required: bool

    def tools_for(self, phase: HarnessPhase | str) -> tuple[str, ...]:
        current = HarnessPhase(phase)
        if self.kind is HarnessPolicyKind.READ_ONLY:
            return ("openpilot_read",)
        if current is HarnessPhase.PLAN:
            return ("openpilot_read",)
        if current is HarnessPhase.VERIFY:
            return ("openpilot_read", "openpilot_validate")
        if self.mutation_allowed:
            return ("openpilot_read", "openpilot_patch")
        return ("openpilot_read", "openpilot_validate")


def policy_profile(kind: HarnessPolicyKind | str) -> HarnessPolicyProfile:
    selected = HarnessPolicyKind(kind)
    return HarnessPolicyProfile(
        kind=selected,
        mutation_allowed=selected in {
            HarnessPolicyKind.DEVELOPER,
            HarnessPolicyKind.APPROVAL_REQUIRED,
        },
        approval_required=selected is HarnessPolicyKind.APPROVAL_REQUIRED,
    )
