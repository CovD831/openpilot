"""Evaluation models for project-level iterative improvement."""

from __future__ import annotations

from pydantic import BaseModel, Field


class EvaluationResult(BaseModel):
    """Project quality evaluation result."""

    approved: bool
    satisfaction_score: float = Field(ge=0.0, le=1.0)
    summary: str
    issues: list[str] = Field(default_factory=list)
    improvement_opportunities: list[str] = Field(default_factory=list)
    recommended_actions: list[str] = Field(default_factory=list)
    next_iteration_goal: str | None = None


class IterationResult(BaseModel):
    """One improvement iteration result."""

    iteration: int
    before_score: float
    after_score: float | None = None
    applied_actions: list[str] = Field(default_factory=list)
    changed_files: list[str] = Field(default_factory=list)
    success: bool
    error: str | None = None
