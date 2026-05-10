"""Interactive openpilot validation session."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, TextIO
from uuid import uuid4

from openpilot.clarifier import ClarificationAnswer, Clarifier, TaskBrief
from openpilot.openpilot_log import OpenPilotLogger
from openpilot.config import LLMSettings
from openpilot.exceptions import OpenPilotError
from openpilot.planner import TaskPlanner
from openpilot.planner_models import ExecutionPlan
from openpilot.reminder_models import ReminderPlan
from openpilot.reminder_scheduler import ReminderScheduler
from openpilot.memory_store import MemoryStore
from openpilot.memory_models import MemoryType, MemoryRecord
from openpilot.autonomy_controller import AutonomyController
from openpilot.autonomy_models import AutonomyDecision

if TYPE_CHECKING:
    from openpilot.terminal_ui import TerminalUI

EXIT_COMMANDS = {"exit", "quit", ":q"}


@dataclass(frozen=True)
class OpenPilotTurnResult:
    """Outcome for one openpilot planning turn."""

    ok: bool
    session_id: str
    turn_id: int
    log_file: Path
    error: str | None = None
    plan: ExecutionPlan | None = None
    task_brief: TaskBrief | None = None
    reminder_plan: ReminderPlan | None = None
    memory_reuse_notes: str | None = None
    autonomy_decisions: list[AutonomyDecision] | None = None


class OpenPilotSession:
    """Run goals through the planner and log the decomposition process."""

    def __init__(
        self,
        planner: TaskPlanner,
        logger: OpenPilotLogger,
        constraints: list[str] | None = None,
        session_id: str | None = None,
        settings: LLMSettings | None = None,
        ui: "TerminalUI | None" = None,
        clarifier: Clarifier | None = None,
        reminder_scheduler: ReminderScheduler | None = None,
        memory_store: MemoryStore | None = None,
        enable_memory: bool = True,
        enable_autonomy: bool = True,
    ) -> None:
        self.planner = planner
        self.logger = logger
        self.constraints = constraints or []
        self.session_id = session_id or str(uuid4())
        self.turn_id = 0
        self.settings = settings or LLMSettings()
        self.ui = ui
        self.clarifier = clarifier or Clarifier()
        self.reminder_scheduler = reminder_scheduler or ReminderScheduler()
        self.memory_store = memory_store or MemoryStore()
        self.enable_memory = enable_memory
        self.enable_autonomy = enable_autonomy
        self.autonomy_controller = AutonomyController(memory_store=memory_store) if enable_autonomy else None

    def handle_goal(
        self,
        goal: str,
        task_brief: TaskBrief | None = None,
        assume_defaults: bool = False,
    ) -> OpenPilotTurnResult:
        """Plan one goal and write trace events to the log file."""

        self.turn_id += 1
        current_turn = self.turn_id
        clean_goal = goal.strip()

        if self.ui:
            with self.ui.status("Reading goal"):
                self._log_goal_received(clean_goal, current_turn)
            if task_brief is None:
                with self.ui.status("Checking missing details"):
                    if assume_defaults:
                        task_brief = self._build_default_brief(clean_goal, current_turn)
            elif assume_defaults:
                with self.ui.status("Checking missing details"):
                    task_brief = self._build_default_brief(clean_goal, current_turn)
            with self.ui.status("Calling planner"):
                result = self._plan_goal(clean_goal, current_turn, task_brief)
            if result.ok and result.plan:
                with self.ui.status("Validating risk policy"):
                    pass
                with self.ui.status("Writing audit log"):
                    pass
                with self.ui.status("Preparing reminders, timeline and step list"):
                    pass
                if result.task_brief:
                    self.ui.show_task_brief(result.task_brief)
                self.ui.show_plan_summary(result.plan)
                if result.reminder_plan:
                    self.ui.show_reminder_plan(result.reminder_plan)
            self.ui.show_turn_result(result)
            return result

        self._log_goal_received(clean_goal, current_turn)
        if task_brief is None and assume_defaults:
            task_brief = self._build_default_brief(clean_goal, current_turn)
        return self._plan_goal(clean_goal, current_turn, task_brief)

    def _log_goal_received(self, clean_goal: str, current_turn: int) -> None:
        self.logger.log_event(
            "goal_received",
            {"goal": clean_goal, "constraints": self.constraints},
            session_id=self.session_id,
            turn_id=current_turn,
        )

    def _plan_goal(
        self,
        clean_goal: str,
        current_turn: int,
        task_brief: TaskBrief | None = None,
    ) -> OpenPilotTurnResult:
        # Retrieve relevant memories before planning
        memory_reuse_notes = None
        retrieved_memories = []
        if self.enable_memory:
            retrieved_memories, memory_reuse_notes = self._retrieve_memories(clean_goal, task_brief)
            if retrieved_memories:
                self.logger.log_event(
                    "memory_retrieved",
                    {
                        "goal": clean_goal,
                        "memory_count": len(retrieved_memories),
                        "memories": [
                            {
                                "id": mem.id,
                                "type": mem.memory_type.value,
                                "content": mem.content,
                                "confidence": mem.confidence,
                                "tags": mem.tags,
                            }
                            for mem in retrieved_memories
                        ],
                        "reuse_notes": memory_reuse_notes,
                    },
                    session_id=self.session_id,
                    turn_id=current_turn,
                )

        planning_constraints = self._planning_constraints(task_brief, retrieved_memories)
        self.logger.log_event(
            "planner_started",
            {
                "goal": clean_goal,
                "constraints": planning_constraints,
                "task_brief": _brief_log_payload(task_brief),
                "memory_enhanced": len(retrieved_memories) > 0,
            },
            session_id=self.session_id,
            turn_id=current_turn,
        )

        try:
            plan = self.planner.plan(clean_goal, constraints=planning_constraints)
        except OpenPilotError as exc:
            error_payload = {
                "error_type": type(exc).__name__,
                "message": str(exc),
                "goal": clean_goal,
                "task_brief": _brief_log_payload(task_brief),
            }
            self.logger.log_event(
                "planner_failed",
                error_payload,
                session_id=self.session_id,
                turn_id=current_turn,
            )
            return OpenPilotTurnResult(
                ok=False,
                session_id=self.session_id,
                turn_id=current_turn,
                log_file=self.logger.log_file,
                error=str(exc),
                task_brief=task_brief,
            )

        # Update memory usage counts
        if self.enable_memory and retrieved_memories:
            for memory in retrieved_memories:
                self.memory_store.update_usage(memory.id, memory.memory_type)

        # Make autonomy decisions for each step
        autonomy_decisions = []
        if self.enable_autonomy and self.autonomy_controller:
            for step in plan.steps:
                decision = self.autonomy_controller.decide_autonomy(
                    step=step,
                    task_card=plan.task_card,
                    goal=clean_goal,
                )
                autonomy_decisions.append(decision)
                self.logger.log_event(
                    "autonomy_decision",
                    {
                        "step_id": step.id,
                        "should_ask_user": decision.should_ask_user,
                        "autonomy_level": decision.autonomy_level.value,
                        "confidence": decision.confidence,
                        "decision_reason": decision.decision_reason,
                        "intervention_reason": decision.intervention_reason,
                    },
                    session_id=self.session_id,
                    turn_id=current_turn,
                )

        reminder_plan = self.reminder_scheduler.build(plan)
        self.logger.log_event(
            "planner_succeeded",
            _plan_log_payload(plan, task_brief, reminder_plan, memory_reuse_notes, autonomy_decisions),
            session_id=self.session_id,
            turn_id=current_turn,
        )
        self.logger.log_event(
            "reminders_planned",
            reminder_plan.model_dump(mode="json"),
            session_id=self.session_id,
            turn_id=current_turn,
        )
        return OpenPilotTurnResult(
            ok=True,
            session_id=self.session_id,
            turn_id=current_turn,
            log_file=self.logger.log_file,
            plan=plan,
            task_brief=task_brief,
            reminder_plan=reminder_plan,
            memory_reuse_notes=memory_reuse_notes,
            autonomy_decisions=autonomy_decisions if autonomy_decisions else None,
        )

    def _planning_constraints(
        self, task_brief: TaskBrief | None, retrieved_memories: list[MemoryRecord] | None = None
    ) -> list[str]:
        base_constraints = list(self.constraints)
        if task_brief is not None:
            base_constraints = task_brief.planning_constraints()

        # Add memory-derived constraints
        if retrieved_memories:
            for memory in retrieved_memories:
                # Only add high-confidence preferences as constraints
                if memory.confidence >= 0.7:
                    base_constraints.append(f"[Preference from history]: {memory.content}")

        return base_constraints

    def _build_default_brief(self, clean_goal: str, current_turn: int) -> TaskBrief:
        questions = self.clarifier.detect(clean_goal, self.constraints)
        if questions:
            self.logger.log_event(
                "clarification_started",
                {
                    "goal": clean_goal,
                    "questions": [question.model_dump(mode="json") for question in questions],
                    "mode": "defaults",
                },
                session_id=self.session_id,
                turn_id=current_turn,
            )
        task_brief = self.clarifier.build_brief(
            clean_goal,
            self.constraints,
            assume_defaults=True,
        )
        if task_brief.assumptions:
            self.logger.log_event(
                "clarification_completed",
                {
                    "goal": clean_goal,
                    "task_brief": task_brief.model_dump(mode="json"),
                    "mode": "defaults",
                },
                session_id=self.session_id,
                turn_id=current_turn,
            )
        return task_brief

    def _retrieve_memories(
        self, goal: str, task_brief: TaskBrief | None = None
    ) -> tuple[list[MemoryRecord], str | None]:
        """Retrieve relevant memories and generate reuse notes.

        Returns:
            Tuple of (retrieved_memories, reuse_notes)
        """
        # Build search query from goal and task type
        search_query = goal
        if task_brief and hasattr(task_brief, "task_type"):
            search_query = f"{goal} {task_brief.task_type}"

        # Query long-term preferences and task memories
        query_result = self.memory_store.query(
            query=search_query,
            memory_types=[MemoryType.LONG_TERM, MemoryType.TASK],
            limit=5,
        )

        if not query_result.memories:
            return [], None

        # Generate reuse notes
        high_confidence = [m for m in query_result.memories if m.confidence >= 0.7]
        low_confidence = [m for m in query_result.memories if m.confidence < 0.7]

        notes_parts = []
        if high_confidence:
            notes_parts.append(
                f"Applied {len(high_confidence)} high-confidence preference(s) from your history"
            )
        if low_confidence:
            notes_parts.append(
                f"Found {len(low_confidence)} related preference(s) with lower confidence (not auto-applied)"
            )

        reuse_notes = "; ".join(notes_parts) if notes_parts else None

        return query_result.memories, reuse_notes

    def run(
        self,
        input_stream: TextIO | None = None,
        output_stream: TextIO | None = None,
    ) -> int:
        """Run a simple REPL until an exit command or EOF is received."""

        input_stream = input_stream or sys.stdin
        if output_stream is None and self.ui:
            return self._run_rich_loop(input_stream)

        output_stream = output_stream or sys.stdout
        self.show_onboarding(output_stream)
        output_stream.write(f"openpilot log: {self.logger.log_file}\n")

        while True:
            self.write_config_warning(output_stream)
            output_stream.write("openpilot > ")
            output_stream.flush()
            line = input_stream.readline()
            if line == "":
                output_stream.write("\n")
                return 0

            goal = line.strip()
            if not goal:
                continue
            if goal.lower() in EXIT_COMMANDS:
                output_stream.write("bye\n")
                return 0

            current_turn = self.turn_id + 1
            task_brief = self._collect_plain_task_brief(
                goal,
                current_turn,
                input_stream,
                output_stream,
            )
            result = self.handle_goal(goal, task_brief=task_brief)
            if result.ok:
                output_stream.write(
                    f"planned and logged: {result.session_id} turn={result.turn_id}\n"
                )
            else:
                output_stream.write(
                    f"planning failed and logged: {result.session_id} "
                    f"turn={result.turn_id}\n"
                )

    def _run_rich_loop(self, input_stream: TextIO) -> int:
        if self.ui is None:
            return 0
        self.ui.show_welcome(self.settings, self.logger.log_file)
        while True:
            self.ui.warn_missing_config(self.settings)
            goal = self.ui.prompt() if input_stream is sys.stdin else input_stream.readline().strip()
            if goal == "" and input_stream is not sys.stdin:
                self.ui.console.print()
                return 0
            if not goal:
                continue
            if goal.lower() in EXIT_COMMANDS:
                self.ui.console.print("bye", style="dim")
                return 0
            current_turn = self.turn_id + 1
            self.ui.console.print("[dim]> Checking missing details[/dim]")
            task_brief = self._collect_rich_task_brief(goal, current_turn, input_stream)
            self.handle_goal(goal, task_brief=task_brief)

    def show_onboarding(self, output_stream: TextIO) -> None:
        """Show non-secret API setup guidance when openpilot starts."""

        base_url_status = "set" if self.settings.base_url.strip() else "missing"
        api_key_status = "set" if self.settings.api_key and self.settings.api_key.strip() else "missing"
        output_stream.write("OpenPilot API setup\n")
        output_stream.write(f"- provider: {self.settings.provider}\n")
        output_stream.write(f"- base_url: {base_url_status}\n")
        output_stream.write(f"- model: {self.settings.model}\n")
        output_stream.write(f"- api_key: {api_key_status}\n")
        output_stream.write("Configure API access in Code/.env or environment variables:\n")
        output_stream.write("- OPENPILOT_LLM_BASE_URL=https://your-provider.example/v1\n")
        output_stream.write("- OPENPILOT_LLM_API_KEY=your-secret-key\n")
        output_stream.write("- OPENPILOT_LLM_MODEL=your-model-name\n")
        output_stream.write("Do not commit real API keys.\n")

    def write_config_warning(self, output_stream: TextIO) -> None:
        """Warn when required LLM settings are not ready."""

        missing = self.settings.missing_fields()
        if missing:
            output_stream.write(
                f"WARNING: LLM config incomplete: {', '.join(missing)}\n"
            )

    def _collect_plain_task_brief(
        self,
        goal: str,
        current_turn: int,
        input_stream: TextIO,
        output_stream: TextIO,
    ) -> TaskBrief | None:
        questions = self.clarifier.detect(goal, self.constraints)
        if not questions:
            return None

        self.logger.log_event(
            "clarification_started",
            {
                "goal": goal,
                "questions": [question.model_dump(mode="json") for question in questions],
                "mode": "interactive",
            },
            session_id=self.session_id,
            turn_id=current_turn,
        )
        output_stream.write("OpenPilot needs a few details before planning.\n")
        answers: list[ClarificationAnswer] = []
        for question in questions:
            output_stream.write(f"{question.prompt} ")
            output_stream.flush()
            line = input_stream.readline()
            answer_text = line.strip() if line else question.default_assumption
            answer = ClarificationAnswer(field=question.field, answer=answer_text)
            answers.append(answer)
            self.logger.log_event(
                "clarification_answered",
                {
                    "field": question.field,
                    "answer": answer_text,
                    "used_default": not bool(line),
                },
                session_id=self.session_id,
                turn_id=current_turn,
            )

        task_brief = self.clarifier.build_brief(
            goal,
            self.constraints,
            answers=answers,
        )
        self.logger.log_event(
            "clarification_completed",
            {"goal": goal, "task_brief": task_brief.model_dump(mode="json")},
            session_id=self.session_id,
            turn_id=current_turn,
        )
        return task_brief

    def _collect_rich_task_brief(
        self,
        goal: str,
        current_turn: int,
        input_stream: TextIO,
    ) -> TaskBrief | None:
        questions = self.clarifier.detect(goal, self.constraints)
        if not questions:
            return None

        self.logger.log_event(
            "clarification_started",
            {
                "goal": goal,
                "questions": [question.model_dump(mode="json") for question in questions],
                "mode": "interactive",
            },
            session_id=self.session_id,
            turn_id=current_turn,
        )
        answers: list[ClarificationAnswer] = []
        for question in questions:
            if self.ui is not None and input_stream is sys.stdin:
                answer_text = self.ui.ask_clarification(question.prompt)
            else:
                answer_text = input_stream.readline().strip()
            if not answer_text:
                answer_text = question.default_assumption
            answer = ClarificationAnswer(field=question.field, answer=answer_text)
            answers.append(answer)
            self.logger.log_event(
                "clarification_answered",
                {
                    "field": question.field,
                    "answer": answer_text,
                    "used_default": answer_text == question.default_assumption,
                },
                session_id=self.session_id,
                turn_id=current_turn,
            )

        task_brief = self.clarifier.build_brief(
            goal,
            self.constraints,
            answers=answers,
        )
        self.logger.log_event(
            "clarification_completed",
            {"goal": goal, "task_brief": task_brief.model_dump(mode="json")},
            session_id=self.session_id,
            turn_id=current_turn,
        )
        return task_brief


def _plan_log_payload(
    plan: ExecutionPlan,
    task_brief: TaskBrief | None = None,
    reminder_plan: ReminderPlan | None = None,
    memory_reuse_notes: str | None = None,
    autonomy_decisions: list[AutonomyDecision] | None = None,
) -> dict:
    payload = {
        "task_card": plan.task_card.model_dump(mode="json"),
        "steps": [step.model_dump(mode="json") for step in plan.steps],
        "timeline": plan.timeline.model_dump(mode="json") if plan.timeline else None,
        "reminder_plan": reminder_plan.model_dump(mode="json") if reminder_plan else None,
        "task_brief": _brief_log_payload(task_brief),
        "assumptions": task_brief.assumptions if task_brief else [],
        "risk_level": plan.task_card.risk_level.value,
        "risk_policy": "deterministic safeguards applied by TaskPlanner",
        "confirmation_points": plan.confirmation_points,
        "fallbacks": plan.fallbacks,
        "success_criteria": plan.success_criteria,
    }
    if memory_reuse_notes:
        payload["memory_reuse_notes"] = memory_reuse_notes
    if autonomy_decisions:
        payload["autonomy_decisions"] = [
            decision.model_dump(mode="json") for decision in autonomy_decisions
        ]
    return payload


def _brief_log_payload(task_brief: TaskBrief | None) -> dict | None:
    if task_brief is None:
        return None
    return task_brief.model_dump(mode="json")
