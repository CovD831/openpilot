"""Routing metadata contracts for OpenPilot execution entry points."""

from __future__ import annotations

from typing import Literal

from metadata.base import MetadataBase, MetadataKind


ExecutionRoute = Literal["agent_generator", "autonomous_iteration"]


class TaskRouteMetadata(MetadataBase):
    kind: Literal[MetadataKind.TASK_ROUTE] = MetadataKind.TASK_ROUTE
    route: ExecutionRoute
    confidence: float
    reason: str
