"""Deprecated coding-task fixture built on top of Evidence Core.

This package remains only to replay and validate coding-shaped trajectories.
It is not the product Agent or the Harness implementation; new enterprise
workflows must enter through the shared Harness and producer interfaces.
"""

from coding_agent.act import WorkspaceAdapter, execute_action
from coding_agent.context import CodingContext, build_coding_context
from coding_agent.contract import (
    CodingAction,
    CodingActionKind,
    CodingActionResult,
    CodingRunResult,
    CodingTask,
)
from coding_agent.adapters.openpilot import OpenPilotWorkspaceAdapter
from coding_agent.loop import CodingAgent
from coding_agent.planner import CodingPlanner, RuleBasedPlanner
from coding_agent.verify import SimpleVerifier, VerificationResult, Verifier

__all__ = [
    "CodingAction",
    "CodingActionKind",
    "CodingActionResult",
    "CodingAgent",
    "CodingContext",
    "CodingPlanner",
    "CodingRunResult",
    "CodingTask",
    "OpenPilotWorkspaceAdapter",
    "RuleBasedPlanner",
    "SimpleVerifier",
    "VerificationResult",
    "Verifier",
    "build_coding_context",
    "execute_action",
    "WorkspaceAdapter",
]
