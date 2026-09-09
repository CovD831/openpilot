"""Pi RPC engine: own one Pi subprocess per run over NDJSON stdio."""

from __future__ import annotations

import json
import os
import selectors
import subprocess
import threading
import time
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from op0.bridge import ReadOnlyToolBridge
from op0.compaction import build_projection, estimate_usage, should_compact
from op0.contracts import TaskSpec
from op0.response import error_message_from_payload
from op0.session import Session

_MAX_RPC_RECORD_BYTES = 1_000_000
_CREDENTIAL_ENV = (
    "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_API_KEY", "ANTHROPIC_OAUTH_TOKEN",
    "OPENAI_API_KEY", "AZURE_OPENAI_API_KEY", "AZURE_OPENAI_BASE_URL",
    "AZURE_OPENAI_RESOURCE_NAME", "AZURE_OPENAI_API_VERSION",
    "AZURE_OPENAI_DEPLOYMENT_NAME_MAP", "GEMINI_API_KEY", "DEEPSEEK_API_KEY",
    "GROQ_API_KEY", "CEREBRAS_API_KEY", "OPENROUTER_API_KEY", "MISTRAL_API_KEY",
    "MINIMAX_API_KEY", "MOONSHOT_API_KEY", "QWEN_TOKEN_PLAN_API_KEY",
    "QWEN_TOKEN_PLAN_CN_API_KEY",
)


class EngineState(StrEnum):
    CREATED = "created"
    RUNNING = "running"
    STOPPED = "stopped"
    CRASHED = "crashed"


def _default_pi_command() -> tuple[str, ...]:
    configured = str(os.environ.get("OP0_PI_COMMAND") or "").strip()
    if configured:
        return (configured,)
    code_root = Path(__file__).resolve().parents[2]
    local_pi = code_root / "pi_sidecar" / "node_modules" / ".bin" / "pi"
    return (str(local_pi),) if local_pi.exists() else ("pi",)


@dataclass(frozen=True)
class EngineConfig:
    command: tuple[str, ...] = field(default_factory=_default_pi_command)
    provider: str = ""
    model: str = ""
    cwd: str = ""
    timeout_seconds: float = 180.0
    enable_read_tool: bool = True
    context_budget_tokens: int = 0  # 0 disables compaction (safe default)
    observations_dir: str = ""

    def argv(self) -> list[str]:
        argv = [
            *self.command,
            "--mode", "rpc",
            "--no-session", "--no-extensions", "--no-skills",
            "--no-prompt-templates", "--no-themes", "--no-context-files",
            "--no-approve",
        ]
        if self.enable_read_tool:
            extension = str(Path(__file__).resolve().parents[2] / "pi_sidecar" / "openpilot_tool_bridge.ts")
            argv.extend(
                ("--no-builtin-tools", "--extension", extension, "--tools", "openpilot_read,openpilot_patch,openpilot_write,openpilot_bash,openpilot_search,openpilot_obs")
            )
        else:
            argv.append("--no-tools")
        if self.provider:
            argv.extend(("--provider", self.provider))
        if self.model:
            argv.extend(("--model", self.model))
        return argv


class Engine:
    """Own one long-lived Pi subprocess; ask() runs one turn per prompt.

    The in-process conversation survives across ask() calls (Pi keeps the
    message history in memory; --no-session only disables persistence), so a
    REPL session maps to one engine process. Every turn's protocol events land
    in the trajectory.
    """

    def __init__(self, session: Session, config: EngineConfig) -> None:
        self.session = session
        self.config = config
        self.state = EngineState.CREATED
        self._buffer = bytearray()
        self._lock = threading.Lock()
        self._process: subprocess.Popen[bytes] | None = None
        self._bridge: ReadOnlyToolBridge | None = None
        self._turns = 0
        self._context = ""  # projection to deliver with the next first-turn prompt

    def start(self, bridge: ReadOnlyToolBridge | None = None) -> None:
        if self.state is EngineState.RUNNING:
            return
        if self.config.enable_read_tool and bridge is None:
            raise ValueError("read tool requires a bridge")
        if bridge is not None and not bridge.socket_path:
            # Defensive: spawning Pi without the socket env makes every tool
            # call fail with "OPENPILOT_PI_TOOL_SOCKET is not configured".
            bridge.start()
        self._bridge = bridge
        self._process = subprocess.Popen(
            self.config.argv(),
            cwd=self.config.cwd or None,
            env=self._environment(bridge),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=False,
            bufsize=0,
        )
        self.state = EngineState.RUNNING
        self.session.record("engine_started", {"pid": self._process.pid}, producer="pi")

    def stop(self) -> None:
        if self.state is EngineState.RUNNING:
            self.session.record("engine_stopped", {}, producer="pi")
            self.state = EngineState.STOPPED
        _stop_process(self._process)
        self._process = None

    def restart(self) -> None:
        """Fresh Pi process; the next first-turn prompt carries the projection."""
        self.stop()
        self.start(self._bridge)

    def inject_recovery_projection(self) -> None:
        """Crash-recovery hand-off: continue with context, not amnesia."""
        if self.config.context_budget_tokens <= 0 or self._context:
            return
        projection = build_projection(
            self.session.load_events(), self.config.observations_dir or None
        )
        if projection:
            self._context = projection

    def _maybe_compact(self) -> None:
        """Fold at the turn boundary when real usage crosses the budget."""
        if self.config.context_budget_tokens <= 0:
            return
        events = self.session.load_events()
        usage = estimate_usage(events)
        if not should_compact(usage, self.config.context_budget_tokens):
            return
        projection = build_projection(events, self.config.observations_dir or None)
        if not projection:
            return  # fail-closed: nothing foldable, stay on the verbatim path
        self.session.record(
            "compaction",
            {
                "policy": "mask-v2",
                "usage_estimate": usage,
                "budget_tokens": self.config.context_budget_tokens,
            },
            producer="compaction",
        )
        self.restart()
        self._context = projection

    def ask(self, prompt: str, *, first_turn: bool = False, _retry: bool = True) -> str:
        """Run one conversation turn against the live process."""
        if self.state is not EngineState.RUNNING or self._process is None:
            raise RuntimeError("engine is not running")
        self._maybe_compact()
        if self.state is not EngineState.RUNNING or self._process is None:
            raise RuntimeError("engine failed to restart for compaction")
        self._turns += 1
        turn_id = f"turn-{self._turns}"
        self._buffer.clear()
        self.session.record("turn_started", {"prompt": prompt, "turn_id": turn_id}, producer="pi")
        try:
            assert self._process.stdin is not None
            request_id = f"prompt:{self.session.run_id}:{self._turns}"
            if first_turn or self._context:
                message = compose_turn_message(prompt, self._context)
                self._context = ""
            else:
                message = prompt
            self._write_record(
                self._process, {"id": request_id, "type": "prompt", "message": message}
            )
            accepted = False
            ended = False
            error = ""
            # idle-based timeout, not a wall-clock turn cap: a blocking
            # tool-call approval gate produces no RPC records by design, and
            # a legitimately long turn keeps emitting deltas.
            last_activity = time.monotonic()
            while not ended:
                deadline = last_activity + max(0.1, self.config.timeout_seconds)
                record = self._read_record(self._process, deadline)
                if record is None:
                    if self._process.poll() is not None:
                        raise EOFError("Pi sidecar exited before agent_end")
                    raise TimeoutError("Pi sidecar idle timeout — no RPC activity")
                last_activity = time.monotonic()
                record_type = str(record.get("type") or "")
                if record_type == "response" and record.get("id") == request_id:
                    if not bool(record.get("success")):
                        raise RuntimeError("Pi rejected the prompt")
                    accepted = True
                    self.session.record("model_request", {"accepted": True}, producer="pi")
                    continue
                mapped = _map_event_type(record_type)
                if mapped:
                    self.session.record(mapped, record, producer="pi")
                if record_type == "message_end":
                    error = error_message_from_payload(record) or error
                ended = record_type == "agent_end"
            if not accepted:
                raise RuntimeError("Pi completed without accepting the prompt")
            if error and _retry:
                return self.ask(prompt, first_turn=first_turn, _retry=False)
        except (EOFError, TimeoutError, RuntimeError, OSError, ValueError) as exc:
            self.state = EngineState.CRASHED
            self.session.record(
                "engine_crashed",
                {"error_type": type(exc).__name__, "message": "Pi sidecar failed before a durable stop"},
                producer="pi",
            )
            _stop_process(self._process)
            self._process = None
        return self.session.last_model_response()

    def run_once(self, spec: TaskSpec, *, bridge: ReadOnlyToolBridge | None = None) -> str:
        """Single-shot compatibility path used by --once and acceptance runs."""
        self.start(bridge)
        try:
            return self.ask(spec.goal, first_turn=True)
        finally:
            self.stop()

    def _environment(self, bridge: ReadOnlyToolBridge | None) -> dict[str, str]:
        inherited = {
            key: value
            for key in ("PATH", "HOME", "TMPDIR", "LANG", "LC_ALL", "SSL_CERT_FILE",
                        "HTTPS_PROXY", "HTTP_PROXY", "NO_PROXY", *_CREDENTIAL_ENV)
            if (value := os.environ.get(key)) is not None
        }
        if bridge is not None:
            inherited["OPENPILOT_PI_TOOL_SOCKET"] = bridge.socket_path
        return inherited

    def _write_record(self, process: subprocess.Popen[bytes], payload: dict[str, Any]) -> None:
        if process.stdin is None:
            raise RuntimeError("Pi sidecar stdin is unavailable")
        process.stdin.write(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n"
        )
        process.stdin.flush()

    def _read_record(self, process: subprocess.Popen[bytes], deadline: float) -> dict[str, Any] | None:
        if process.stdout is None:
            raise RuntimeError("Pi sidecar stdout is unavailable")
        selector = selectors.DefaultSelector()
        selector.register(process.stdout, selectors.EVENT_READ)
        try:
            while time.monotonic() < deadline:
                newline = self._buffer.find(b"\n")
                if newline >= 0:
                    raw = bytes(self._buffer[:newline]).rstrip(b"\r")
                    del self._buffer[: newline + 1]
                    if not raw:
                        continue
                    decoded = json.loads(raw.decode("utf-8"))
                    if not isinstance(decoded, dict):
                        raise ValueError("Pi RPC record must be a JSON object")
                    return decoded
                ready = selector.select(max(0.0, deadline - time.monotonic()))
                if not ready:
                    return None
                chunk = os.read(process.stdout.fileno(), 4096)
                if not chunk:
                    return None
                self._buffer.extend(chunk)
                if len(self._buffer) > _MAX_RPC_RECORD_BYTES:
                    raise ValueError("Pi RPC record exceeds the configured bound")
            return None
        finally:
            selector.close()


def _map_event_type(event_type: str) -> str:
    return {
        "agent_start": "engine_started",
        "turn_start": "turn_started",
        "message_start": "model_response_started",
        "message_update": "model_response_delta",
        "message_end": "model_response",
        "turn_end": "turn_finished",
        "agent_end": "agent_end",
        "tool_execution_start": "tool_call",
        "tool_execution_end": "tool_result",
    }.get(event_type, "")


def compose_turn_message(prompt: str, context: str = "") -> str:
    """First-turn message: pin the tool contract for the whole session (L4
    surface); `context` carries the compaction projection after a fold or a
    crash-recovery restart."""
    message = (
        "You are op0, working inside the user's project through the OpenPilot "
        "gateway. Tools: openpilot_read (read a project file), openpilot_search "
        "(search file contents), openpilot_patch (replace lines of an existing "
        "file), openpilot_write (create or overwrite a file), openpilot_bash "
        "(run one shell command in the project root), openpilot_obs (retrieve "
        "the full text of a stored observation by id). Reads and search run "
        "freely. A patch, write, or bash call may pause until the human "
        "approves it: when approved, the same call executes and returns its "
        "result normally; when denied you will see a denial — do not retry "
        "the same call, briefly acknowledge the denial and ask the human what "
        "to do differently, then stop that line of work. Use project-relative "
        "paths. Reply concisely and never re-quote file contents verbatim — "
        "summarize or point at them instead. This contract holds for every "
        "later turn in this conversation.\n\n"
    )
    if context:
        message += (
            "Context from earlier turns: one line per folded turn (user "
            "intent, assistant gist, tool-call count); recent turns are "
            "verbatim. Tool outputs from folded turns were stored outside "
            "the context and are retrievable by id with openpilot_obs."
            "\n\n" + context + "\n\n"
        )
    return message + "User task:\n" + prompt


def _stop_process(process: subprocess.Popen[bytes] | None) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=2.0)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=2.0)
