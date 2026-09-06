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
from op0.contracts import TaskSpec
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
            argv.extend(("--no-builtin-tools", "--extension", extension, "--tools", "openpilot_read"))
        else:
            argv.append("--no-tools")
        if self.provider:
            argv.extend(("--provider", self.provider))
        if self.model:
            argv.extend(("--model", self.model))
        return argv


class Engine:
    """Run one prompt through Pi; every protocol event lands in the trajectory."""

    def __init__(self, session: Session, config: EngineConfig) -> None:
        self.session = session
        self.config = config
        self.state = EngineState.CREATED
        self._buffer = bytearray()
        self._lock = threading.Lock()

    def run_once(self, spec: TaskSpec, *, bridge: ReadOnlyToolBridge | None = None) -> str:
        process: subprocess.Popen[bytes] | None = None
        deadline = time.monotonic() + max(0.1, self.config.timeout_seconds)
        self._buffer.clear()
        try:
            if self.config.enable_read_tool and bridge is None:
                raise ValueError("read tool requires a bridge")
            process = subprocess.Popen(
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
            self.session.record("engine_started", {"pid": process.pid}, producer="pi")
            request_id = f"prompt:{self.session.run_id}"
            self._write_record(process, {"id": request_id, "type": "prompt", "message": spec.goal})
            accepted = False
            ended = False
            while not ended:
                record = self._read_record(process, deadline)
                if record is None:
                    if process.poll() is not None:
                        raise EOFError("Pi sidecar exited before agent_end")
                    raise TimeoutError("Pi sidecar response timed out")
                if record.get("type") == "response" and record.get("id") == request_id:
                    if not bool(record.get("success")):
                        raise RuntimeError("Pi rejected the prompt")
                    accepted = True
                    self.session.record("model_request", {"accepted": True}, producer="pi")
                    continue
                mapped = _map_event_type(str(record.get("type") or ""))
                if mapped:
                    self.session.record(mapped, record, producer="pi")
                ended = str(record.get("type") or "") == "agent_end"
            if not accepted:
                raise RuntimeError("Pi completed without accepting the prompt")
            self.state = EngineState.STOPPED
            self.session.record("engine_stopped", {}, producer="pi")
        except (EOFError, TimeoutError, RuntimeError, OSError, ValueError) as exc:
            self.state = EngineState.CRASHED
            self.session.record(
                "engine_crashed",
                {"error_type": type(exc).__name__, "message": "Pi sidecar failed before a durable stop"},
                producer="pi",
            )
        finally:
            _stop_process(process)
            if bridge is not None:
                bridge.stop()
        return self.session.last_model_response()

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


def _stop_process(process: subprocess.Popen[bytes] | None) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=2.0)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=2.0)
