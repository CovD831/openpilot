"""op0 TUI: full-screen layout with a fixed bottom input bar.

Layout mirrors the claude-code shape (studied from the CCB source):
  - top:   scrolling transcript — a read-only projection of the trajectory
           (tool calls folded claude-code style, responses as markdown text);
           approval questions render inline here, in the flow
  - bottom: a fixed input bar, always visible, constant height.

The UI owns no facts: everything rendered comes from the session, registry,
and receipt store; input is the only thing the UI produces. Approval keys
(y/n/a, 1/2/3, esc) live on the focused BufferControl so they beat character
insertion while an approval is pending. The layout reserves no rows for a
card: dynamic heights leave redraw residue outside full-screen mode, so the
question goes to the transcript instead (prompt_toolkit floats cannot escape
the app area in non-fullscreen rendering — measured, not assumed).
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
from rich.markup import escape

from op0 import ui
from op0.admission import AdmissionRegistry
from op0.receipts import ReceiptStore
from op0.session import Session

_MAX_HISTORY_BLOCKS = 400
_SPINNER_FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"


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
        self._approval: dict | None = None
        self._deny_prompt = False  # after "No": invite typed feedback, cc-style
        self._thinking_shown: set[int] = set()  # event indexes already surfaced

        self.input_buffer = Buffer(multiline=False, accept_handler=self._accept)
        self.input_buffer_control = None  # set once the layout is built

        # -- approval bindings live on the focused control: they beat the
        #    buffer's character insertion, so 'y' approves instead of typing.
        #    The card itself is printed into the transcript (claude-code
        #    shape: question in the flow, no reserved rows in the layout).
        approving = Condition(lambda: self.mode == "waiting-approval")
        approval_kb = KeyBindings()

        def _submit(answer: str):
            def handler(event) -> None:
                if self._approval is not None and self._approval.get("answer") is None:
                    self._approval["answer"] = answer
                    done = self._approval.get("done")
                    if done is not None:
                        done.set()  # wakes a tool-call-time approval gate, if any
                    self.input_buffer.reset()
                    self._refresh()
            return handler

        approval_kb.add("escape", filter=approving)(_submit("n"))
        for key, answer in (("y", "y"), ("n", "n"), ("a", "a"), ("1", "y"), ("2", "a"), ("3", "n")):
            approval_kb.add(key, filter=approving)(_submit(answer))

        self._status_window = Window(
            content=FormattedTextControl(self._get_status, focusable=False),
            height=1,
        )
        self._hint_window = Window(
            content=FormattedTextControl("  ? shortcuts · /help · /exit"),
            style="class:hint",
            height=1,
        )

        # claude-code input: a thin divider rule above a "❯ " prompt — no
        # bordered box (side borders wrap-misalign exactly like a panel).
        layout = Layout(
            HSplit(
                [
                    Window(height=1, char="─", style="class:border-dim"),
                    VSplit(
                        [
                            Window(width=2, content=FormattedTextControl([("class:prompt", "❯ ")]), dont_extend_height=True),
                            Window(
                                content=BufferControl(buffer=self.input_buffer, key_bindings=approval_kb),
                                dont_extend_height=True,
                            ),
                        ],
                        height=1,
                    ),
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
            full_screen=False,
            mouse_support=False,
            style=_tui_style(),
            input=input,
            output=output,
        )
        self.app.key_bindings.bindings.extend(approval_kb.bindings)
        kb = KeyBindings()
        kb.add("c-c")(lambda event: self._exit())
        kb.add("c-q")(lambda event: self._exit())
        idle = Condition(lambda: self.mode == "idle")
        kb.add("s-tab", filter=idle)(lambda event: self._toggle_mode())
        self.app.key_bindings.bindings.extend(kb.bindings)

    # -- transcript projection ------------------------------------------

    def append_block(self, markup_text: str) -> None:
        """Accept rich markup; render to ANSI and print into the terminal
        scrollback (patch_stdout inserts it above the input bar, in order)."""
        print(_rich_to_ansi(markup_text), flush=True)

    def _get_status(self):
        if self.mode == "working":
            frame = _SPINNER_FRAMES[self.spinner_index % len(_SPINNER_FRAMES)]
            text = f"{frame} {self.status_text or 'working…'}"
            if self.queue:
                text += f"  [dim]{len(self.queue)} queued[/dim]"
            return ANSI(_rich_to_ansi(text))
        if self.mode == "waiting-approval":
            return ANSI(_rich_to_ansi("[yellow]approval pending — y / a / n (or 1/2/3)[/yellow]"))
        if self._deny_prompt:
            return ANSI(_rich_to_ansi("[yellow]tell the model what to do differently (type below)[/yellow]"))
        mode = self.state.get("approval_mode", "ask")
        mode_text = (
            "[yellow]auto-approve on[/yellow] (shift+tab to switch)"
            if mode == "auto"
            else "[dim]ask mode · shift+tab to auto-approve[/dim]"
        )
        return ANSI(_rich_to_ansi(f"[dim]type a task · /help · /exit · [/dim]{mode_text}"))

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
                mapped = {"y": "y", "yes": "y", "1": "y", "a": "a", "all": "a", "2": "a",
                          "n": "n", "no": "n", "3": "n"}.get(answer)
                if mapped:
                    self._approval["answer"] = mapped
                else:
                    self.append_block("[dim]approval pending — answer y / a / n (or 1/2/3)[/dim]")
            return
        self.append_block(f"[bold on #262626] ❯ {escape(text)} [/]")
        self._deny_prompt = False
        self.state["goal"] = text
        self.traj.record("task_received", {"goal": text})
        self._crash_retries = 0
        self._run_goal(text, first_turn=True)
        self._post_turn()
        # a crashed engine restarts and CONTINUES the task (bounded) —
        # auto mode means the user should never have to nudge it back alive
        while (
            self.engine.state.value == "crashed"
            and self._crash_retries < 3
            and self.state["goal"]
        ):
            self._crash_retries += 1
            self.bridge.start()  # fresh socket first, then a fresh Pi process
            self.engine.start(self.bridge)
            self.append_block(
                f"[yellow](engine crashed; restarting — continuing the task, "
                f"attempt {self._crash_retries}/3)[/yellow]"
            )
            self._run_goal(self.state["goal"], first_turn=False)
            self._post_turn()
        if self.engine.state.value == "crashed":
            self.append_block(
                "[red]engine crashed 3 times — task paused. Check /recover, then re-send the task.[/red]"
            )

    # -- task execution ----------------------------------------------------

    def _run_goal(self, goal: str, *, first_turn: bool) -> None:
        self.mode = "working"
        started = time.monotonic()
        self._refresh()
        response_holder: dict[str, str] = {}

        def worker() -> None:
            try:
                response_holder["response"] = self.engine.ask(goal, first_turn=first_turn)
            except Exception as exc:  # noqa: BLE001
                response_holder["response"] = ""
                response_holder["error"] = f"{type(exc).__name__}: {exc}"

        events_at_start = len(self.traj.load_events())
        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        shown_calls: set[str] = set()
        while thread.is_alive():
            self.spinner_index += 1
            self.status_text = f"✻ thinking… {int(time.monotonic() - started)}s"
            self._stream_events(events_at_start, shown_calls)
            self._print_new_thinking(events_at_start)
            self._refresh()
            time.sleep(0.12)
        thread.join()
        self._print_new_thinking(events_at_start)

        if response_holder.get("error"):
            self.append_block(f"[red]turn error:[/red] {escape(response_holder['error'])}")
        if self.engine.state.value == "crashed":
            # never claim closure for a turn the engine did not finish
            self.traj.record("run_finished", {"response_chars": 0, "crashed": True})
            self.append_block("[yellow](turn interrupted by engine crash — restarting and continuing)[/yellow]")
            return
        response = response_holder.get("response", "")
        if response:
            self.state["saw_response"] = True
        self.traj.record("run_finished", {"response_chars": len(response)})
        error = "" if response else self.traj.last_model_error()
        self.append_block(ui.model_error_markup(error) if error else ui.render_markdown_to_str(response))
        from op0.receipts import decide_closure

        status, reason = decide_closure(
            self.store.all(run_id=self.traj.run_id),
            saw_model_response=self.state["saw_response"],
        )
        self.append_block(ui.render_closure_to_str(status, reason))

    def _stream_events(self, start_index: int, shown_calls: set[str]) -> None:
        """Print tool calls the moment they happen (claude-code streaming)."""
        events = self.traj.load_events()
        for event in events[start_index:]:
            if event.producer != "bridge":
                continue
            payload = event.payload or {}
            call_id = str(payload.get("toolCallId") or "")
            if event.event_type == "tool_call" and call_id not in shown_calls:
                shown_calls.add(call_id)
                tool = str(payload.get("toolName") or "").replace("openpilot_", "").title()
                args = dict(payload.get("args") or {})
                if tool == "Bash":
                    detail = str(args.get("command") or "")[:80]
                elif "lineStart" in args:
                    detail = f"{Path(str(args.get('path') or '')).name} L{args.get('lineStart')}-{args.get('lineEnd')}"
                elif tool == "Search":
                    detail = f"{args.get('pattern', '')!r}"
                else:
                    detail = Path(str(args.get("path") or "")).name
                print(f"  \033[32m●\033[0m \033[1m{tool}\033[0m \033[2m{detail}\033[0m", flush=True)
            elif event.event_type == "tool_result" and call_id:
                key = f"result:{call_id}"
                if key not in shown_calls:
                    shown_calls.add(key)
                    preview = str(payload.get("preview") or "").splitlines()
                    first = preview[0][:90] if preview else ""
                    mark = "\033[2m⎿\033[0m" if payload.get("success") else "\033[31m⎿\033[0m"
                    print(f"    {mark} \033[2m{first}\033[0m", flush=True)

    def _print_new_thinking(self, start_index: int) -> None:
        """Live thinking visibility (claude-code style, low-key): a dim ✻ line
        the moment a thinking block STARTS (deltas stream as model_response_delta
        events) and one with its snippet when the completed message lands. Long
        reasoning must never read as a frozen spinner."""
        events = self.traj.load_events()
        for index in range(start_index, len(events)):
            if index in self._thinking_shown:
                continue
            event = events[index]
            payload = event.payload or {}
            if event.event_type == "model_response_delta":
                stream_event = payload.get("assistantMessageEvent") or {}
                if stream_event.get("type") == "thinking_start":
                    self._thinking_shown.add(index)
                    print("  \033[2m✻ (thinking…)\033[0m", flush=True)
            elif event.event_type == "model_response":
                message = payload.get("message") or {}
                if message.get("role") != "assistant":
                    continue
                for item in message.get("content") or []:
                    if isinstance(item, dict) and item.get("type") == "thinking":
                        thought = str(item.get("thinking") or "").strip().replace("\n", " ")
                        if thought:
                            self._thinking_shown.add(index)
                            print(f"  \033[2m✻ {thought[:100]}…\033[0m", flush=True)
                        break

    def approval_gate(self, proposal) -> bool:
        """Called from the bridge tool thread when a side effect needs a
        decision: surface the card in the flow NOW and block the tool call
        until the human answers (claude-code semantics — the agent pauses at
        the tool call instead of flailing on refusals). True = approved."""
        done = threading.Event()
        self._approval = {"proposal": proposal, "answer": None, "done": done}
        self.mode = "waiting-approval"
        self.append_block(ui.render_proposal_to_str(proposal))
        self._refresh()
        done.wait()
        answer = self._approval["answer"] if self._approval else ""
        self._approval = None
        self.mode = "working"  # the turn is still running; the spinner resumes
        self._refresh()
        return answer in ("y", "a")

    def _post_turn(self) -> None:
        retries = 0
        while self.registry.pending() and retries < 8:
            pending = self.registry.pending()
            # claude-code shape: the question lives in the transcript flow,
            # the bottom bar stays constant-height (no reserved card rows).
            self.append_block(ui.render_proposal_to_str(pending[0]))
            if len(pending) > 1:
                self.append_block(f"[dim]{len(pending)} proposals pending — '2' approves all[/dim]")
            self._approval = {"proposal": pending[0], "answer": None, "done": threading.Event()}
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
                    self.append_block(f"[red]approval failed:[/red] {escape(exc)}")
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
                    self.append_block(f"[red]approval failed:[/red] {escape(exc)}")
                    break
            elif answer in ("n", "no"):
                pending = self.registry.pending()
                if pending:
                    denied = self.registry.deny(pending[0].proposal_id)
                    self.append_block(f"[red]denied[/red] {denied.proposal_id}")
                self._deny_prompt = True  # option 3: invite typed feedback
                break
            else:
                break
            retries += 1
            self._run_goal(self.state["goal"], first_turn=False)
        self.mode = "idle"
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
        if self._approval is not None and self._approval.get("done") is not None:
            self._approval["done"].set()  # unblock a tool-call-time approval gate
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
        from prompt_toolkit.patch_stdout import patch_stdout

        # raw=True: print() carries real ANSI escape codes (tool colors);
        # without it patch_stdout escapes them into literal '?[32m' garbage.
        with patch_stdout(raw=True):
            self.app.run()
        return 0


def _capture_turn_tools(events, *, verbose: bool) -> str:
    from rich.console import Console as RichConsole

    capture = RichConsole(
        file=io.StringIO(), force_terminal=True, color_system="truecolor", width=ui.console.width
    )
    ui.render_turn_tools(events, verbose=verbose, console=capture)
    return capture.file.getvalue()
