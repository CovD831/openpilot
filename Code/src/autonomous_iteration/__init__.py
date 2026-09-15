"""Autonomous Iteration module aligned with instructions/openpilot."""

from __future__ import annotations

from autonomous_iteration.runtime_controller import (
    AgentRuntimeController,
    EditGuard,
    RuntimeVerifier,
    StateUpdater,
    ToolRouter,
)
from autonomous_iteration.application import EngineKind, HarnessApplication
from autonomous_iteration.ports import ApplicationPort, ActionPort, EnginePort, EvidencePort, SupervisorPort, VerificationPort
from autonomous_iteration.run_coordinator import RunCoordinator, RunHandle
from autonomous_iteration.action_gateway import ActionGateway, ActionRequest, ActionResult
from autonomous_iteration.supervisor import SupervisorSession
from autonomous_iteration.verification import CompletionDecision, CompletionProfile, evaluate_completion
from autonomous_iteration.engines import FakePiEngine, PiMessage, PiRpcEngine, PiSidecarConfig, PiSidecarState

__all__ = [
    "AgentRuntimeController",
    "EditGuard",
    "RuntimeVerifier",
    "StateUpdater",
    "ToolRouter",
    "HarnessApplication",
    "EngineKind",
    "ApplicationPort",
    "ActionPort",
    "EnginePort",
    "EvidencePort",
    "SupervisorPort",
    "VerificationPort",
    "RunCoordinator",
    "RunHandle",
    "ActionGateway",
    "ActionRequest",
    "ActionResult",
    "SupervisorSession",
    "CompletionDecision",
    "CompletionProfile",
    "evaluate_completion",
    "FakePiEngine",
    "PiMessage",
    "PiRpcEngine",
    "PiSidecarConfig",
    "PiSidecarState",
    "agents",
    "improvement_context",
    "intelligent_autopilot",
    "models",
    "pipeline",
    "project_iteration",
    "project_improvement_runtime",
    "runtime_controller",
    "task_executor",
    "task_models",
    "tool",
    "tool_io",
]
