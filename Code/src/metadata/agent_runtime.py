"""Agent runtime state contracts for phase-driven execution."""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import Field

from metadata.base import JsonValue, MetadataBase, MetadataKind


class AgentPhase(str, Enum):
    """High-level runtime phases used to drive tool and edit decisions."""

    UNDERSTAND_TASK = "understand_task"
    UNDERSTAND_PROJECT = "understand_project"
    DIAGNOSE = "diagnose"
    PLAN = "plan"
    EXECUTE = "execute"
    VERIFY = "verify"
    RECOVER = "recover"
    REPLAN = "replan"
    ASK_USER = "ask_user"
    SUMMARIZE = "summarize"
    BLOCKED = "blocked"


class RuntimeBudgetMetadata(MetadataBase):
    """Mutable runtime budgets that bound exploration and recovery loops."""

    kind: Literal[MetadataKind.RUNTIME_BUDGET] = MetadataKind.RUNTIME_BUDGET
    max_tool_calls: int = 20
    max_file_reads: int = 30
    max_file_edits: int = 3
    max_verification_attempts: int = 3
    max_recovery_rounds: int = 3
    max_replan_rounds: int = 3
    tool_calls_used: int = 0
    file_reads_used: int = 0
    file_edits_used: int = 0
    verification_attempts_used: int = 0
    recovery_rounds_used: int = 0
    replan_rounds_used: int = 0

    @property
    def tool_calls_remaining(self) -> int:
        return max(0, self.max_tool_calls - self.tool_calls_used)

    @property
    def file_reads_remaining(self) -> int:
        return max(0, self.max_file_reads - self.file_reads_used)

    @property
    def file_edits_remaining(self) -> int:
        return max(0, self.max_file_edits - self.file_edits_used)

    @property
    def verification_attempts_remaining(self) -> int:
        return max(0, self.max_verification_attempts - self.verification_attempts_used)

    @property
    def recovery_rounds_remaining(self) -> int:
        return max(0, self.max_recovery_rounds - self.recovery_rounds_used)

    @property
    def replan_rounds_remaining(self) -> int:
        return max(0, self.max_replan_rounds - self.replan_rounds_used)

    def has_tool_budget(self, *, reads: int = 0, edits: int = 0) -> bool:
        return (
            self.tool_calls_used < self.max_tool_calls
            and self.file_reads_used + reads <= self.max_file_reads
            and self.file_edits_used + edits <= self.max_file_edits
        )

    def consume_tool_call(self, *, file_read: bool = False, file_edit: bool = False) -> None:
        self.tool_calls_used += 1
        if file_read:
            self.file_reads_used += 1
        if file_edit:
            self.file_edits_used += 1

    def consume_verification_attempt(self) -> None:
        self.verification_attempts_used += 1

    def consume_recovery_round(self) -> None:
        self.recovery_rounds_used += 1

    def consume_replan_round(self) -> None:
        self.replan_rounds_used += 1

    def exhausted_reasons(self) -> list[str]:
        reasons: list[str] = []
        if self.tool_calls_used >= self.max_tool_calls:
            reasons.append("tool call budget exhausted")
        if self.file_reads_used >= self.max_file_reads:
            reasons.append("file read budget exhausted")
        if self.file_edits_used >= self.max_file_edits:
            reasons.append("file edit budget exhausted")
        if self.verification_attempts_used >= self.max_verification_attempts:
            reasons.append("verification budget exhausted")
        if self.recovery_rounds_used >= self.max_recovery_rounds:
            reasons.append("recovery budget exhausted")
        if self.replan_rounds_used >= self.max_replan_rounds:
            reasons.append("replan budget exhausted")
        return reasons


class EditPlanMetadata(MetadataBase):
    """Evidence-backed edit request approved before any write operation."""

    kind: Literal[MetadataKind.EDIT_PLAN] = MetadataKind.EDIT_PLAN
    subgoal: str
    target_files: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    allowed_changes: list[str] = Field(default_factory=list)
    forbidden_changes: list[str] = Field(default_factory=list)
    risk_level: str = "medium"
    verification: list[str] = Field(default_factory=list)
    attributes: dict[str, JsonValue] = Field(default_factory=dict)


class VerificationPlanMetadata(MetadataBase):
    """Verification plan selected after a write or other risky action."""

    kind: Literal[MetadataKind.VERIFICATION_PLAN] = MetadataKind.VERIFICATION_PLAN
    reason: str
    commands: list[str] = Field(default_factory=list)
    target_files: list[str] = Field(default_factory=list)
    fallback_checks: list[str] = Field(default_factory=list)
    required: bool = True
    attributes: dict[str, JsonValue] = Field(default_factory=dict)


class DecisionNeedMetadata(MetadataBase):
    """Model- or controller-raised information need consumed by ToolRouter."""

    kind: Literal[MetadataKind.DECISION_NEED] = MetadataKind.DECISION_NEED
    need_type: str
    question: str
    phase: AgentPhase = AgentPhase.UNDERSTAND_TASK
    target_path: str | None = None
    candidate_paths: list[str] = Field(default_factory=list)
    operation_kind: str | None = None
    target_scope: str | None = None
    symbol_name: str | None = None
    symbol_type: str | None = None
    insertion_hint: str | None = None
    patch_mode: str | None = None
    query: str | None = None
    command: str | None = None
    decision_to_unlock: str | None = None
    expected_state_change: str | None = None
    cost_hint: str = "low"
    risk_level: str = "low"
    attributes: dict[str, JsonValue] = Field(default_factory=dict)


class ToolDecisionMetadata(MetadataBase):
    """Explanation for a routed tool selection."""

    kind: Literal[MetadataKind.TOOL_DECISION] = MetadataKind.TOOL_DECISION
    need_type: str
    question: str
    selected_tool: str
    phase: AgentPhase = AgentPhase.UNDERSTAND_TASK
    reason: str
    alternatives_considered: list[str] = Field(default_factory=list)
    expected_state_change: str | None = None
    risk_level: str = "low"
    cost_hint: str = "low"
    requires_confirmation: bool = False
    attributes: dict[str, JsonValue] = Field(default_factory=dict)


class GuardDecisionMetadata(MetadataBase):
    """Deterministic approval result for an edit plan."""

    kind: Literal[MetadataKind.GUARD_DECISION] = MetadataKind.GUARD_DECISION
    approved: bool
    reason: str
    risk_level: str = "medium"
    blocked_files: list[str] = Field(default_factory=list)
    required_evidence: list[str] = Field(default_factory=list)
    required_verification: list[str] = Field(default_factory=list)
    attributes: dict[str, JsonValue] = Field(default_factory=dict)


class RuntimeStateMetadata(MetadataBase):
    """Explicit task state that drives phase transitions and tool decisions."""

    kind: Literal[MetadataKind.RUNTIME_STATE] = MetadataKind.RUNTIME_STATE
    goal: str
    phase: AgentPhase = AgentPhase.UNDERSTAND_TASK
    known_facts: list[str] = Field(default_factory=list)
    unknowns: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    resolved_questions: list[str] = Field(default_factory=list)
    candidate_files: dict[str, list[str]] = Field(default_factory=dict)
    selected_files: dict[str, list[str]] = Field(default_factory=dict)
    planned_edits: list[EditPlanMetadata] = Field(default_factory=list)
    modified_files: list[str] = Field(default_factory=list)
    tool_history: list[dict[str, JsonValue]] = Field(default_factory=list)
    decision_history: list[ToolDecisionMetadata] = Field(default_factory=list)
    verification_status: str = "not_started"
    risk_level: str = "low"
    budget: RuntimeBudgetMetadata = Field(default_factory=RuntimeBudgetMetadata)
    replan_count: int = 0
    no_progress_rounds: int = 0
    completion_reason: str | None = None

    def add_fact(self, fact: str) -> None:
        fact = fact.strip()
        if fact and fact not in self.known_facts:
            self.known_facts.append(fact)

    def add_unknown(self, question: str) -> None:
        question = question.strip()
        if question and question not in self.unknowns:
            self.unknowns.append(question)

    def resolve_unknown(self, question: str) -> None:
        if question in self.unknowns:
            self.unknowns.remove(question)
        question = question.strip()
        if question and question not in self.resolved_questions:
            self.resolved_questions.append(question)

    def add_assumption(self, assumption: str) -> None:
        assumption = assumption.strip()
        if assumption and assumption not in self.assumptions:
            self.assumptions.append(assumption)

    def add_candidate_file(self, file_path: str, evidence: str) -> None:
        if not file_path:
            return
        evidence_list = self.candidate_files.setdefault(file_path, [])
        if evidence and evidence not in evidence_list:
            evidence_list.append(evidence)

    def select_file(self, file_path: str, evidence: str) -> None:
        if not file_path:
            return
        self.add_candidate_file(file_path, evidence)
        evidence_list = self.selected_files.setdefault(file_path, [])
        if evidence and evidence not in evidence_list:
            evidence_list.append(evidence)

    def add_modified_file(self, file_path: str) -> None:
        if file_path and file_path not in self.modified_files:
            self.modified_files.append(file_path)

    def record_tool_event(self, event: dict[str, JsonValue]) -> None:
        self.tool_history.append(event)

    def record_tool_decision(self, decision: ToolDecisionMetadata) -> None:
        self.decision_history.append(decision)

    def request_replan(self, reason: str) -> None:
        if self.budget.replan_rounds_used >= self.budget.max_replan_rounds:
            self.block("replan budget exhausted")
            return
        self.replan_count += 1
        self.budget.consume_replan_round()
        self.phase = AgentPhase.REPLAN
        self.add_unknown(reason)

    def block(self, reason: str) -> None:
        self.phase = AgentPhase.BLOCKED
        self.completion_reason = reason


class RuntimeReportMetadata(MetadataBase):
    """Final auditable runtime report derived from runtime state."""

    kind: Literal[MetadataKind.RUNTIME_REPORT] = MetadataKind.RUNTIME_REPORT
    goal: str
    phase: AgentPhase
    completion_reason: str | None = None
    known_facts: list[str] = Field(default_factory=list)
    unresolved_questions: list[str] = Field(default_factory=list)
    selected_files: dict[str, list[str]] = Field(default_factory=dict)
    modified_files: list[str] = Field(default_factory=list)
    planned_edits: list[EditPlanMetadata] = Field(default_factory=list)
    verification_status: str = "not_started"
    risk_level: str = "low"
    tool_decisions: list[ToolDecisionMetadata] = Field(default_factory=list)
    tool_history: list[dict[str, JsonValue]] = Field(default_factory=list)
    residual_risks: list[str] = Field(default_factory=list)
