"""op0 TUI: full-screen layout with a fixed bottom input bar.

Layout mirrors the claude-code shape (learned from the CCB source):
  - top:   scrolling transcript — a read-only projection of the trajectory
           (tool calls folded claude-code style, responses as markdown text)
  - bottom: a fixed input bar, always visible, with a status line above it.

The UI owns no facts: everything rendered comes from the session, registry,
and receipt store; input is the only thing the UI produces.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

from prompt_toolkit.application import Application
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.formatted_text import ANSI
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import HSplit, Layout, VSplit
from prompt_toolkit.layout.controls import BufferControl, FormattedTextControl
from prompt_toolkit.layout.containers import Window

from op0 import ui
from op0.admission import AdmissionRegistry
from op0.receipts import ReceiptStore
from op0.session import Session

_MAX_HISTORY_BLOCKS = 400
_SPINNER_FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"


def _tui_style() -> "Style":
    """Colors aligned with the claude-code look: dim rounded frame, orange accents."""
    from prompt_toolkit.styles import Style as PTStyle

    return PTStyle.from_dict(
        {
            "border": "#ff8c38",
            "border-dim": "#7a4a28",
            "prompt": "#ff8c38 bold",
            "hint": "#6f6d66",
            "status": "#ff8c38",
        }
    )



def _rich_to_ansi(markup: str) -> str:
    """Render rich markup to real ANSI escape codes for prompt_toolkit."""
    import io

    from rich.console import Console as RichConsole

    width = ui.console.width
    buf = io.StringIO()
    console = RichConsole(file=buf, force_terminal=True, color_system="truecolor", width=width)
    console.print(markup, markup=True, highlight=False)
    return buf.getvalue().rstrip("\n")



class TuiSession:
    """Owns the full-screen app: transcript above, fixed input bar below."""

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
    ) -> None:
        self.project_root = project_root
        self.traj = traj
        self.registry = registry
        self.store = store
        self.bridge = bridge
        self.engine = engine
        self.version = version
        self.on_command = on_command  # (text) -> None, runs in worker thread
        self.state = state

        self.blocks: list[str] = []
        self.mode = "idle"            # idle | working | exiting
        self.status_text = ""
        self.spinner_index = 0
        self.queue: list[str] = []
        self.approval_hint = ""

        self.input_buffer = Buffer(multiline=False, accept_handler=self._accept)
        self._history_window = Window(
            content=FormattedTextControl(self._get_history, focusable=False),
            always_hide_cursor=True,
        )
        self._status_window = Window(
            content=FormattedTextControl(self._get_status, focusable=False),
            height=1,
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
                    self._status_window,
                    edge("╭", "╮"),
                    VSplit(
                        [
                            Window(width=1, char="│", style="class:border"),
                            Window(
                                width=2,
                                content=FormattedTextControl("> "),
                                dont_extend_height=True,
                            ),
                            Window(
                                content=BufferControl(buffer=self.input_buffer),
                                dont_extend_height=True,
                            ),
                            Window(width=1, char="│", style="class:border"),
                        ],
                        height=1,
                    ),
                    edge("╰", "╯"),
                    self._hint_window,
                ]
            ),
            focused_element=self.input_buffer,
        )
        kb = KeyBindings()
        kb.add("c-c")(lambda event: self._exit())
        kb.add("c-q")(lambda event: self._exit())
        self.app: Application = Application(
            layout=layout,
            key_bindings=kb,
            full_screen=True,
            mouse_support=False,
            style=_tui_style(),
        )

    # -- transcript projection ------------------------------------------

    def append_block(self, markup_text: str) -> None:
        """Accept rich markup; store it as real ANSI (projection is rendered once)."""
        self.blocks.append(_rich_to_ansi(markup_text))
        if len(self.blocks) > _MAX_HISTORY_BLOCKS:
            self.blocks = self.blocks[-_MAX_HISTORY_BLOCKS:]
        self._scroll_bottom()
        self.app.invalidate()

    def _get_history(self):
        from prompt_toolkit.formatted_text import ANSI as FTANSI

        return FTANSI("\n".join(self.blocks) + "\n")

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
        if self.registry.pending():
            ids = ", ".join(p.proposal_id for p in self.registry.pending())
            return ANSI(_rich_to_ansi(f"[yellow]approval pending: {ids} — type y / n / a[/yellow]"))
        if self.approval_hint:
            return ANSI(_rich_to_ansi(f"[dim]{self.approval_hint}[/dim]"))
        return ANSI(_rich_to_ansi("[dim]type a task · /help · /exit[/dim]"))

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
        if self.registry.pending():
            self._handle_approval_input(text)
            return
        self.state["goal"] = text
        self.traj.record("task_received", {"goal": text})
        self._run_goal(text, first_turn=True)
        self._post_turn()

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
            import io

            from rich.console import Console as RichConsole

            capture = RichConsole(file=io.StringIO(), force_terminal=True, width=ui.console.width)
            old_console = ui.console
            ui.console = capture
            try:
                ui.render_turn_tools(events[turn_start:], verbose=self.state["verbose"])
            finally:
                ui.console = old_console
            self.append_block(capture.file.getvalue())
        response = response_holder.get("response", "")
        if response:
            self.state["saw_response"] = True
        self.traj.record("run_finished", {"response_chars": len(response)})
        capture = ui.render_markdown_to_str(response)
        self.append_block(capture)
        from op0.receipts import decide_closure

        status, reason = decide_closure(
            self.store.all(run_id=self.traj.run_id),
            saw_model_response=self.state["saw_response"],
        )
        self.append_block(ui.render_closure_to_str(status, reason))

    def _post_turn(self) -> None:
        if self.engine.state.value == "crashed":
            self.bridge.start()
            self.append_block("[yellow](engine crashed; restarting)[/yellow]")
        # approval IS the continue (bounded)
        retries = 0
        while self.registry.pending() and retries < 8:
            self.mode = "idle"
            pending = self.registry.pending()
            import io

            from rich.console import Console as RichConsole

            width = ui.console.width
            buf = io.StringIO()
            previous_console = ui.console
            ui.console = RichConsole(file=buf, force_terminal=True, width=width)
            try:
                ui.proposal_panel(pending[0], verbose=self.state["verbose"])
            finally:
                ui.console = previous_console
            self.append_block(buf.getvalue())
            self.approval_hint = "approve pending proposal — type y / n / a"
            self._refresh()
            self.mode = "waiting-approval"
            answer_holder: dict[str, str] = {}
            done = threading.Event()

            original_accept = self.input_buffer.accept_handler

            def approval_accept(buffer: Buffer) -> bool:
                answer_holder["answer"] = buffer.text.strip().lower()
                buffer.reset()
                done.set()
                return False

            self.input_buffer.accept_handler = approval_accept
            done.wait(timeout=300)
            self.input_buffer.accept_handler = original_accept
            answer = answer_holder.get("answer", "")
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
                self.append_block("[dim]waiting for y/n/a — say continue to re-prompt[/dim]")
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
