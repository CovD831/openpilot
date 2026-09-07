"""op0 TUI: full-screen layout with a fixed bottom input bar.

Layout mirrors the claude-code shape (studied from the CCB source):
  - top:   scrolling transcript — a read-only projection of the trajectory
           (tool calls folded claude-code style, responses as markdown text)
  - middle: a live status line, and a live approval card when the model
            requests a side effect
  - bottom: a fixed input bar, always visible.

The UI owns no facts: everything rendered comes from the session, registry,
and receipt store; input is the only thing the UI produces. Approval keys
(y/n/a, 1/2/3, arrows, enter, esc) live on the focused BufferControl so
they beat character insertion while the card is up.
"""

from __future__ import annotations

import io
import json
import threading
import time
from pathlib import Path

from prompt_toolkit.application import Application
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.filters import Condition
from prompt_toolkit.formatted_text import ANSI
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import HSplit, Layout, VSplit
from prompt_toolkit.layout.containers import Window
from prompt_toolkit.layout.controls import BufferControl, FormattedTextControl
from prompt_toolkit.layout.dimension import D
from prompt_toolkit.styles import Style as PTStyle

from op0 import ui
from op0.admission import AdmissionRegistry
from op0.receipts import ReceiptStore
from op0.session import Session

_MAX_HISTORY_BLOCKS = 400
_SPINNER_FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

_APPROVAL_OPTIONS = [
    ("Yes", "approve and continue"),
    ("Yes to all", "approve every pending proposal"),
    ("No", "deny — tell the model what to do instead"),
]

_NAME_TO_ANSWER = {"Yes": "y", "Yes to all": "a", "No": "n"}


def _diff_stat(diff_preview: str) -> str:
    lines = diff_preview.splitlines()
    added = sum(1 for line in lines if line.startswith("+") and not line.startswith("+++"))
    removed = sum(1 for line in lines if line.startswith("-") and not line.startswith("---"))
    return f"+{added} −{removed} lines"


def _rich_to_ansi(markup: str) -> str:
    """Render rich markup to real ANSI escape codes for prompt_toolkit."""
    width = ui.console.width
    buf = io.StringIO()
    console = __import__("rich.console", fromlist=["Console"]).Console(
        file=buf, force_terminal=True, color_system="truecolor", width=width
    )
    console.print(markup, markup=True, highlight=False)
    return buf.getvalue().rstrip("\n")


def _tui_style() -> PTStyle:
    """Colors aligned with the claude-code look: dim rounded frame, orange accents."""
    return PTStyle.from_dict(
        {
            "border": "#ff8c38",
            "border-dim": "#7a4a28",
            "prompt": "#ff8c38 bold",
            "hint": "#6f6d66",
            "approval": "#ff8c38",
        }
    )


class TuiSession:
    def __init__(
        self,
        project_root: Path,
        traj: Session,
        registry: AdmissionRegistry,
        store: ReceiptStore,
        bridge,
        engine,
        *,
        version: str,
        on_command,
        state: dict,
        input=None,
        output=None,
    ) -> None:
        self.project_root = project_root
        self.traj = traj
        self.registry = registry
        self.store = store
        self.bridge = bridge
        self.engine = engine
        self.version = version
        self.on_command = on_command
        self.state = state

        self.blocks: list[str] = []
        self.mode = "idle"  # idle | working | waiting-approval | exiting
        self.status_text = ""
        self.spinner_index = 0
        self.queue: list[str] = []
        self.approval_hint = ""
        self._approval: dict | None = None

        self.input_buffer = Buffer(multiline=False, accept_handler=self._accept)
        self.input_buffer_control = None  # set once the layout is built

        # -- approval bindings live on the focused control: they beat the
        #    buffer's character insertion, so 'y' approves instead of typing.
        approving = Condition(lambda: self.mode == "waiting-approval")
        approval_kb = KeyBindings()

        def _submit(answer: str):
            def handler(event) -> None:
                if self._approval is not None and self._approval.get("answer") is None:
                    self._approval["answer"] = answer
                    self.input_buffer.reset()
                    self._refresh()
            return handler

        def _move(delta: int):
            def handler(event) -> None:
                if self._approval is not None:
                    count = len(_APPROVAL_OPTIONS)
                    self._approval["selected"] = (self._approval["selected"] + delta) % count
                    self._refresh()
            return handler

        approval_kb.add("up", filter=approving)(_move(-1))
        approval_kb.add("down", filter=approving)(_move(1))
        approval_kb.add("enter", filter=approving)(
            lambda event: _submit(_NAME_TO_ANSWER[_APPROVAL_OPTIONS[self._approval["selected"]][0]])(event)
        )
        approval_kb.add("escape", filter=approving)(_submit("n"))
        for key, answer in (("y", "y"), ("n", "n"), ("a", "a")):
            approval_kb.add(key, filter=approving)(_submit(answer))
        for key, answer in (("1", "y"), ("2", "a"), ("3", "n")):
            approval_kb.add(key, filter=approving)(_submit(answer))

        self._history_window = Window(
            content=FormattedTextControl(self._get_history, focusable=False),
            always_hide_cursor=True,
        )
        self._status_window = Window(
            content=FormattedTextControl(self._get_status, focusable=False),
            height=1,
        )
        self._approval_window = Window(
            content=FormattedTextControl(self._get_approval_card, focusable=False),
            height=D(min=0, max=14),
            style="class:approval",
        )
        self._hint_window = Window(
            content=FormattedTextControl("  ? shortcuts · /help · /exit"),
            style="class:hint",
            height=1,
        )

        def edge(left: str, right: str) -> Window:
            return VSplit(
                [
                    Window(width=1, content=FormattedTextControl(left), style="class:border", dont_extend_height=True),
                    Window(char="─", style="class:border-dim"),
                    Window(width=1, content=FormattedTextControl(right), style="class:border", dont_extend_height=True),
                ],
                height=1,
            )

        layout = Layout(
            HSplit(
                [
                    self._history_window,
                    self._approval_window,
                    edge("╭", "╮"),
                    VSplit(
                        [
                            Window(width=1, char="│", style="class:border"),
                            Window(width=2, content=FormattedTextControl("> "), dont_extend_height=True),
                            Window(
                                content=BufferControl(buffer=self.input_buffer, key_bindings=approval_kb),
                                dont_extend_height=True,
                            ),
                            Window(width=1, char="│", style="class:border"),
                        ],
                        height=1,
                    ),
                    edge("╰", "╯"),
                    self._status_window,
                    self._hint_window,
                ]
            ),
            focused_element=self.input_buffer,
        )
        def _find_buffer_control(container):
            if isinstance(container, Window) and isinstance(container.content, BufferControl):
                return container.content
            for child in getattr(container, "children", []) or []:
                found = _find_buffer_control(child)
                if found is not None:
                    return found
            return None

        self.input_buffer_control = _find_buffer_control(layout.container)

        self.app: Application = Application(
            layout=layout,
            key_bindings=KeyBindings(),
            full_screen=True,
            mouse_support=False,
            style=_tui_style(),
            input=input,
            output=output,
        )
        self.app.key_bindings.bindings.extend(
            [
                b
                for b in approval_kb.bindings
            ]
        )
        kb = KeyBindings()
        kb.add("c-c")(lambda event: self._exit())
        kb.add("c-q")(lambda event: self._exit())
        idle = Condition(lambda: self.mode == "idle")
        kb.add("s-tab", filter=idle)(lambda event: self._toggle_mode())
        self.app.key_bindings.bindings.extend(kb.bindings)

    # -- transcript projection ------------------------------------------

    def append_block(self, markup_text: str) -> None:
        """Accept rich markup; store it as real ANSI (rendered once)."""
        self.blocks.append(_rich_to_ansi(markup_text))
        if len(self.blocks) > _MAX_HISTORY_BLOCKS:
            self.blocks = self.blocks[-_MAX_HISTORY_BLOCKS:]
        self._trim_to_terminal()
        self._scroll_bottom()
        self._refresh()

    def _trim_to_terminal(self) -> None:
        """Keep only the tail of the transcript that fits on screen.

        vertical_scroll alone is not enough (some terminals reset it on
        resize); clipping whole blocks guarantees the newest content is
        always visible without manual resizing.
        """
        import shutil

        keep_rows = max(shutil.get_terminal_size().lines - 6, 10)
        total = 0
        cut = 0
        for i in range(len(self.blocks) - 1, -1, -1):
            total += self.blocks[i].count("\n") + 1
            if total > keep_rows:
                cut = i + 1
                break
        if cut > 0:
            self.blocks = self.blocks[cut:]

    def _get_history(self):
        return ANSI("\n".join(self.blocks) + "\n")

    def _scroll_bottom(self) -> None:
        try:
            self._history_window.vertical_scroll = 10**9
        except Exception:  # noqa: BLE001
            pass

    def _get_status(self):
        if self.mode == "working":
            frame = _SPINNER_FRAMES[self.spinner_index % len(_SPINNER_FRAMES)]
            text = f"{frame} {self.status_text or 'working…'}"
            if self.queue:
                text += f"  [dim]{len(self.queue)} queued[/dim]"
            return ANSI(_rich_to_ansi(text))
        if self.approval_hint:
            return ANSI(_rich_to_ansi(f"[dim]{self.approval_hint}[/dim]"))
        mode = self.state.get("approval_mode", "ask")
        mode_text = (
            "[yellow]auto-approve on[/yellow] (shift+tab to switch)"
            if mode == "auto"
            else "[dim]ask mode · shift+tab to auto-approve[/dim]"
        )
        return ANSI(_rich_to_ansi(f"[dim]type a task · /help · /exit · [/dim]{mode_text}"))

    def _get_approval_card(self):
        """The live approval card (claude-code shape): summary + selectable options."""
        approval = self._approval
        if not approval:
            return ""
        proposal = approval["proposal"]
        grant = proposal.grant
        lines: list[str] = []
        label = {"patch": "Patch", "write": "Write", "bash": "Bash"}.get(grant.kind, grant.kind.title())
        lines.append(f"[bold]● {label} — approval required[/bold]")
        if grant.command:
            lines.append(f"[cyan]$ {grant.command}[/cyan]")
        for path in grant.write_paths:
            lines.append(f"[cyan]{path}[/cyan]")
        if grant.diff_preview.strip():
            lines.append(f"[dim]changes: {_diff_stat(grant.diff_preview)} (verbose expands)[/dim]")
        lines.append("")
        for index, (name, description) in enumerate(_APPROVAL_OPTIONS):
            chosen = index == approval["selected"]
            marker = "❯" if chosen else " "
            style = "bold" if chosen else "dim"
            lines.append(f"{marker} {index + 1}. {name}  [dim]— {description}[/dim]")
        lines.append("[dim]↑↓ move · enter confirm · y/n/a keys[/dim]")
        return ANSI(_rich_to_ansi("\n".join(lines)))

    # -- input ------------------------------------------------------------

    def _accept(self, buffer: Buffer) -> bool:
        text = buffer.text.strip()
        buffer.reset()
        if not text:
            return False
        if self.mode == "working":
            self.queue.append(text)
            self._refresh()
            return False
        if text in ("/exit", "/quit", "exit", "quit", ":q"):
            self._exit()
            return False
        threading.Thread(target=self._dispatch, args=(text,), daemon=True).start()
        return False

    def _dispatch(self, text: str) -> None:
        if text.startswith("/"):
            self.on_command(text)
            return
        if self.registry.pending() and self.mode == "waiting-approval":
            if self._approval is not None and self._approval.get("answer") is None:
                answer = text.strip().lower()
                self._approval["answer"] = {"y": "y", "a": "a", "n": "n"}.get(answer, "n")
            return
        self.append_block(f"[bold]> {text}[/bold]")
        self.state["goal"] = text
        self.traj.record("task_received", {"goal": text})
        self._run_goal(text, first_turn=True)
        self._post_turn()

    # -- task execution ----------------------------------------------------

    def _run_goal(self, goal: str, *, first_turn: bool) -> None:
        self.mode = "working"
        self.status_text = "thinking…"
        self._refresh()
        response_holder: dict[str, str] = {}

        def worker() -> None:
            try:
                response_holder["response"] = self.engine.ask(goal, first_turn=first_turn)
            except Exception as exc:  # noqa: BLE001
                response_holder["response"] = ""
                response_holder["error"] = f"{type(exc).__name__}: {exc}"

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        while thread.is_alive():
            self.spinner_index += 1
            self._refresh()
            time.sleep(0.12)
        thread.join()

        if response_holder.get("error"):
            self.append_block(f"[red]turn error:[/red] {response_holder['error']}")
        events = self.traj.load_events()
        turn_start = max(
            (i for i, e in enumerate(events) if e.event_type == "turn_started"), default=None
        )
        if turn_start is not None:
            self.append_block(_capture_turn_tools(events[turn_start:], verbose=self.state["verbose"]))
        response = response_holder.get("response", "")
        if response:
            self.state["saw_response"] = True
        self.traj.record("run_finished", {"response_chars": len(response)})
        self.append_block(ui.render_markdown_to_str(response))
        from op0.receipts import decide_closure

        status, reason = decide_closure(
            self.store.all(run_id=self.traj.run_id),
            saw_model_response=self.state["saw_response"],
        )
        self.append_block(ui.render_closure_to_str(status, reason))

    def _post_turn(self) -> None:
        if self.engine.state.value == "crashed":
            self.bridge.start()  # fresh socket first, then a fresh Pi process
            self.engine.start(self.bridge)
            self.append_block("[yellow](engine crashed; restarting)[/yellow]")
        retries = 0
        while self.registry.pending() and retries < 8:
            pending = self.registry.pending()
            self._approval = {
                "proposal": pending[0],
                "pending_count": len(pending),
                "selected": 0,
                "answer": None,
            }
            self.mode = "waiting-approval"
            self._refresh()
            while self._approval["answer"] is None and self.mode == "waiting-approval":
                self.spinner_index += 1
                self._refresh()
                time.sleep(0.1)
            answer = self._approval["answer"] or ""
            self._approval = None
            self.mode = "idle"
            if answer in ("y", "yes"):
                try:
                    pending = self.registry.pending()
                    consent = self.registry.approve(pending[0].proposal_id, self.traj.run_id)
                    self.traj.record(
                        "consent_bound",
                        {"consent_id": consent.consent_id, "proposal_id": consent.proposal_id},
                        producer="admission",
                    )
                    self.append_block(f"[green]approved[/green] {consent.consent_id}")
                except Exception as exc:  # noqa: BLE001
                    self.append_block(f"[red]approval failed:[/red] {exc}")
                    break
            elif answer in ("a", "all"):
                try:
                    consent, ids = self.registry.approve_all(self.traj.run_id)
                    self.traj.record(
                        "consent_bound",
                        {"consent_id": consent.consent_id, "proposal_ids": list(ids), "batch": True},
                        producer="admission",
                    )
                    self.append_block(f"[green]approved {len(ids)} proposal(s)[/green]")
                except Exception as exc:  # noqa: BLE001
                    self.append_block(f"[red]approval failed:[/red] {exc}")
                    break
            elif answer in ("n", "no"):
                pending = self.registry.pending()
                if pending:
                    denied = self.registry.deny(pending[0].proposal_id)
                    self.append_block(f"[red]denied[/red] {denied.proposal_id}")
                break
            else:
                break
            retries += 1
            self._run_goal(self.state["goal"], first_turn=False)
        self.mode = "idle"
        self.approval_hint = ""
        self._drain_queue()

    def _drain_queue(self) -> None:
        while self.queue and self.mode == "idle":
            text = self.queue.pop(0)
            self._dispatch(text)

    # -- plumbing ---------------------------------------------------------

    def _refresh(self) -> None:
        try:
            self.app.invalidate()
        except Exception:  # noqa: BLE001
            pass

    def _toggle_mode(self) -> None:
        new_mode = "auto" if self.state.get("approval_mode", "ask") == "ask" else "ask"
        self.state["approval_mode"] = new_mode
        self.traj.record("approval_mode_changed", {"mode": new_mode}, producer="tui")
        if new_mode == "auto" and self.registry.pending():
            consent, ids = self.registry.approve_all(self.traj.run_id)
            self.traj.record(
                "consent_bound",
                {"consent_id": consent.consent_id, "proposal_ids": list(ids), "batch": True, "auto": True},
                producer="admission",
            )
            self.append_block(f"[yellow]auto-approve on — cleared {len(ids)} pending proposal(s)[/yellow]")
        self.append_block(
            f"[yellow]approval mode: {new_mode}[/yellow]"
            if new_mode == "auto"
            else "[dim]approval mode: ask[/dim]"
        )
        self._refresh()

    def _exit(self) -> None:
        self.mode = "exiting"
        try:
            self.engine.stop()
            self.bridge.stop()
        except Exception:  # noqa: BLE001
            pass
        self.app.exit()

    def run(self) -> int:
        self.append_block(f"[dim]◆ op0 v{self.version} — governed coding agent[/dim]")
        self.append_block(f"[dim]project: {self.project_root}[/dim]")
        self.append_block("[dim]type a task · /help · /exit[/dim]")
        self.app.run()
        return 0


def _capture_turn_tools(events, *, verbose: bool) -> str:
    from rich.console import Console as RichConsole

    capture = RichConsole(
        file=io.StringIO(), force_terminal=True, color_system="truecolor", width=ui.console.width
    )
    ui.render_turn_tools(events, verbose=verbose, console=capture)
    return capture.file.getvalue()
