"""Pi sidecar protocol boundary, process adapter, and deterministic fake."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
import json
import os
from pathlib import Path
import selectors
import socket
import subprocess
import tempfile
import threading
import time
import uuid
import queue
from typing import Any, Callable, Mapping

from autonomous_iteration.run_coordinator import RunCoordinator, RunHandle


class PiSidecarState(StrEnum):
    CREATED = "created"
    RUNNING = "running"
    STOPPED = "stopped"
    CRASHED = "crashed"


PI_PACKAGE_VERSION = "0.84.3"
_MAX_TOOL_BRIDGE_REQUEST_BYTES = 1_000_000
_MAX_TOOL_BRIDGE_CONTENT_BYTES = 16_384
_MAX_PI_RPC_RECORD_BYTES = 1_000_000
_TOOL_BRIDGE_CONNECTION_TIMEOUT_SECONDS = 1.0
_PROVIDER_CREDENTIAL_ENV = (
    "ANTHROPIC_AUTH_TOKEN",
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_OAUTH_TOKEN",
    "OPENAI_API_KEY",
    "AZURE_OPENAI_API_KEY",
    "AZURE_OPENAI_BASE_URL",
    "AZURE_OPENAI_RESOURCE_NAME",
    "AZURE_OPENAI_API_VERSION",
    "AZURE_OPENAI_DEPLOYMENT_NAME_MAP",
    "GEMINI_API_KEY",
    "DEEPSEEK_API_KEY",
    "GROQ_API_KEY",
    "CEREBRAS_API_KEY",
    "OPENROUTER_API_KEY",
    "MISTRAL_API_KEY",
    "MINIMAX_API_KEY",
    "MOONSHOT_API_KEY",
    "QWEN_TOKEN_PLAN_API_KEY",
    "QWEN_TOKEN_PLAN_CN_API_KEY",
)


def _default_pi_command() -> tuple[str, ...]:
    configured = str(os.environ.get("OPENPILOT_PI_COMMAND") or "").strip()
    if configured:
        return (configured,)
    code_root = Path(__file__).resolve().parents[3]
    local_pi = code_root / "pi_sidecar" / "node_modules" / ".bin" / "pi"
    return (str(local_pi),) if local_pi.exists() else ("pi",)


@dataclass(frozen=True)
class PiMessage:
    protocol_version: str
    message_type: str
    run_id: str
    engine_session_id: str
    turn_id: str = ""
    call_id: str = ""
    message_id: str = ""
    requires_ack: bool = True
    payload: dict[str, Any] | None = None


@dataclass(frozen=True)
class PiSidecarConfig:
    command: tuple[str, ...] = field(default_factory=_default_pi_command)
    provider: str = ""
    model: str = ""
    timeout_seconds: float = 120.0
    cwd: str = ""
    enable_read_tool: bool = False
    enable_mutation_tools: bool = False
    extension_path: str = ""

    def argv(self) -> list[str]:
        argv = [
            *self.command,
            "--mode", "rpc",
            "--no-session",
            "--no-extensions",
            "--no-skills",
            "--no-prompt-templates",
            "--no-themes",
            "--no-context-files",
            "--no-approve",
        ]
        if self.enable_read_tool or self.enable_mutation_tools:
            extension = self.extension_path or str(
                Path(__file__).resolve().parents[3]
                / "pi_sidecar"
                / "openpilot_tool_bridge.ts"
            )
            tools = "openpilot_read"
            if self.enable_mutation_tools:
                tools = "openpilot_read,openpilot_patch,openpilot_validate"
            argv.extend(("--no-builtin-tools", "--extension", extension, "--tools", tools))
        else:
            argv.append("--no-tools")
        if self.provider:
            argv.extend(("--provider", self.provider))
        if self.model:
            argv.extend(("--model", self.model))
        return argv


class PiRpcEngine:
    """Own one Pi RPC subprocess for one root Run.

    The process is model-only: all Pi tools and project resources are disabled.
    OpenPilot remains the sole authority for tool admission and side effects.
    """

    protocol_version = "pi-rpc-v1"

    def __init__(
        self,
        coordinator: RunCoordinator,
        config: PiSidecarConfig | None = None,
        *,
        environment: Mapping[str, str] | None = None,
        engine_session_id: str | None = None,
    ) -> None:
        self.coordinator = coordinator
        self.config = config or PiSidecarConfig()
        self.environment = dict(environment or {})
        self.engine_session_id = engine_session_id or uuid.uuid4().hex
        self.state = PiSidecarState.CREATED
        self._message_index = 0
        self._stdout_buffer = bytearray()
        self._message_lock = threading.Lock()

    def run_once(
        self,
        run: RunHandle,
        *,
        prompt: str,
        action_handler: Callable[[dict[str, Any]], Any] | None = None,
    ) -> list[PiMessage]:
        process: subprocess.Popen[bytes] | None = None
        bridge: _PiToolSocketBridge | None = None
        messages: list[PiMessage] = []
        deadline = time.monotonic() + max(0.1, self.config.timeout_seconds)
        self._stdout_buffer.clear()
        try:
            if self.config.enable_read_tool or self.config.enable_mutation_tools:
                if action_handler is None:
                    raise ValueError("Pi read tool requires an OpenPilot action handler")
                bridge = _PiToolSocketBridge(
                    action_handler,
                    on_request=lambda payload: self._persist(run, "tool_call", payload),
                    on_result=lambda payload: self._persist(run, "tool_result", payload),
                )
                bridge.start()
            process = subprocess.Popen(
                self.config.argv(),
                cwd=self.config.cwd or None,
                env=self._sidecar_environment(bridge),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=False,
                bufsize=0,
            )
            self.state = PiSidecarState.RUNNING
            messages.append(self._persist(run, "engine_started", {"pid": process.pid}))
            request_id = f"prompt:{self.engine_session_id}"
            self._write_record(process, {"id": request_id, "type": "prompt", "message": prompt})
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
                    messages.append(self._persist(run, "model_request", {"accepted": True}))
                    continue
                event_type = str(record.get("type") or "")
                mapped = self._map_event_type(event_type)
                if mapped:
                    messages.append(self._persist(run, mapped, record))
                ended = event_type == "agent_end"
            if not accepted:
                raise RuntimeError("Pi completed without accepting the prompt")
            self.state = PiSidecarState.STOPPED
            messages.append(self._persist(run, "engine_stopped", {}))
            return messages
        except (EOFError, TimeoutError, RuntimeError, OSError, ValueError) as exc:
            self.state = PiSidecarState.CRASHED
            messages.append(
                self._persist(
                    run,
                    "engine_crashed",
                    {
                        "error_type": type(exc).__name__,
                        "message": "Pi sidecar failed before a durable stop",
                    },
                )
            )
            return messages
        finally:
            self._stop_process(process)
            if bridge is not None:
                bridge.stop()

    def _sidecar_environment(self, bridge: "_PiToolSocketBridge | None" = None) -> dict[str, str]:
        inherited = {
            key: value
            for key in (
                "PATH", "HOME", "TMPDIR", "LANG", "LC_ALL",
                "SSL_CERT_FILE", "HTTPS_PROXY", "HTTP_PROXY", "NO_PROXY",
                *_PROVIDER_CREDENTIAL_ENV,
            )
            if (value := os.environ.get(key)) is not None
        }
        inherited.update(self.environment)
        if bridge is not None:
            inherited["OPENPILOT_PI_TOOL_SOCKET"] = bridge.socket_path
        return inherited

    @staticmethod
    def _write_record(process: subprocess.Popen[bytes], payload: dict[str, Any]) -> None:
        if process.stdin is None:
            raise RuntimeError("Pi sidecar stdin is unavailable")
        process.stdin.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n")
        process.stdin.flush()

    def _read_record(self, process: subprocess.Popen[bytes], deadline: float) -> dict[str, Any] | None:
        if process.stdout is None:
            raise RuntimeError("Pi sidecar stdout is unavailable")
        selector = selectors.DefaultSelector()
        selector.register(process.stdout, selectors.EVENT_READ)
        try:
            while time.monotonic() < deadline:
                newline = self._stdout_buffer.find(b"\n")
                if newline >= 0:
                    raw = bytes(self._stdout_buffer[:newline]).rstrip(b"\r")
                    del self._stdout_buffer[: newline + 1]
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
                self._stdout_buffer.extend(chunk)
                if len(self._stdout_buffer) > _MAX_PI_RPC_RECORD_BYTES:
                    raise ValueError("Pi RPC record exceeds the configured bound")
            return None
        finally:
            selector.close()

    @staticmethod
    def _stop_process(process: subprocess.Popen[bytes] | None) -> None:
        if process is None or process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=2.0)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=2.0)

    @staticmethod
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

    def _persist(self, run: RunHandle, event_type: str, payload: dict[str, Any]) -> PiMessage:
        with self._message_lock:
            self._message_index += 1
            message_id = f"{self.engine_session_id}:{self._message_index}"
        call_id = str(payload.get("toolCallId") or payload.get("call_id") or "")
        turn_id = str(payload.get("turnId") or payload.get("turn_id") or "")
        message = PiMessage(
            protocol_version=self.protocol_version,
            message_type=event_type,
            run_id=run.run_id,
            engine_session_id=self.engine_session_id,
            turn_id=turn_id,
            call_id=call_id,
            message_id=message_id,
            requires_ack=True,
            payload=payload,
        )
        self.coordinator.record_observation(
            run,
            event_type=event_type,
            payload=payload,
            producer="pi",
            call_id=call_id,
            idempotency_key=message_id,
        )
        return message


class _PiToolSocketBridge:
    """Private LF-JSONL Unix-socket bridge from Pi tools to Action Gateway."""

    def __init__(
        self,
        handler: Callable[[dict[str, Any]], Any],
        *,
        on_request: Callable[[dict[str, Any]], Any],
        on_result: Callable[[dict[str, Any]], Any],
        handler_timeout_seconds: float = 30.0,
    ) -> None:
        self.handler = handler
        self.on_request = on_request
        self.on_result = on_result
        self.handler_timeout_seconds = max(0.01, handler_timeout_seconds)
        self._temporary: tempfile.TemporaryDirectory[str] | None = None
        self._server: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self.socket_path = ""

    def start(self) -> None:
        self._temporary = tempfile.TemporaryDirectory(prefix="openpilot-pi-tool-")
        self.socket_path = str(Path(self._temporary.name) / "gateway.sock")
        self._server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._server.bind(self.socket_path)
        self._server.listen(8)
        self._server.settimeout(0.1)
        self._thread = threading.Thread(target=self._serve, name="openpilot-pi-tool-bridge", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._server is not None:
            self._server.close()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        if self._temporary is not None:
            self._temporary.cleanup()

    def _serve(self) -> None:
        assert self._server is not None
        while not self._stop.is_set():
            try:
                connection, _ = self._server.accept()
            except TimeoutError:
                continue
            except OSError:
                return
            with connection:
                connection.settimeout(_TOOL_BRIDGE_CONNECTION_TIMEOUT_SECONDS)
                try:
                    response = self._handle(self._read_record(connection))
                except Exception as exc:
                    response = self._failure_response("", exc)
                try:
                    connection.sendall(
                        json.dumps(response, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n"
                    )
                except OSError:
                    continue

    @staticmethod
    def _read_record(connection: socket.socket) -> dict[str, Any]:
        buffer = bytearray()
        while b"\n" not in buffer:
            chunk = connection.recv(4096)
            if not chunk:
                raise EOFError("tool bridge client disconnected")
            buffer.extend(chunk)
            if len(buffer) > _MAX_TOOL_BRIDGE_REQUEST_BYTES:
                raise ValueError("tool bridge request is too large")
        decoded = json.loads(bytes(buffer.split(b"\n", 1)[0]).decode("utf-8"))
        if not isinstance(decoded, dict):
            raise ValueError("tool bridge request must be a JSON object")
        return decoded

    def _handle(self, request: dict[str, Any]) -> dict[str, Any]:
        call_id = str(request.get("toolCallId") or "")
        try:
            if request.get("toolName") not in {
                "openpilot_read",
                "openpilot_patch",
                "openpilot_validate",
            } or not call_id:
                raise ValueError("invalid OpenPilot tool request")
            self.on_request(request)
            result = self._invoke_handler(request)
            response = {
                "toolCallId": call_id,
                "success": True,
                "content": self._bounded_content(
                    result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)
                ),
            }
        except Exception as exc:
            response = self._failure_response(call_id, exc)
        indeterminate = bool(response.get("indeterminate"))
        try:
            self.on_result(
                {
                    "toolCallId": call_id,
                    "success": response["success"],
                    **({"indeterminate": True} if indeterminate else {}),
                }
            )
        except Exception as exc:
            response = self._failure_response(call_id, exc, context="evidence commit")
        return response

    def _invoke_handler(self, request: dict[str, Any]) -> Any:
        completed: queue.Queue[tuple[bool, Any]] = queue.Queue(maxsize=1)

        def invoke() -> None:
            try:
                completed.put((True, self.handler(request)))
            except Exception as exc:
                completed.put((False, exc))

        worker = threading.Thread(
            target=invoke,
            name="openpilot-pi-tool-handler",
            daemon=True,
        )
        worker.start()
        try:
            succeeded, value = completed.get(timeout=self.handler_timeout_seconds)
        except queue.Empty as exc:
            raise TimeoutError("OpenPilot action handler timed out") from exc
        if not succeeded:
            raise value
        return value

    @staticmethod
    def _bounded_content(content: str) -> str:
        encoded = content.encode("utf-8")
        if len(encoded) <= _MAX_TOOL_BRIDGE_CONTENT_BYTES:
            return content
        marker = "<truncated>"
        budget = _MAX_TOOL_BRIDGE_CONTENT_BYTES - len(marker.encode("utf-8"))
        return encoded[:budget].decode("utf-8", errors="ignore") + marker

    @staticmethod
    def _failure_response(
        call_id: str,
        exc: Exception,
        *,
        context: str = "request",
    ) -> dict[str, Any]:
        response = {
            "toolCallId": call_id,
            "success": False,
            "content": f"OpenPilot tool {context} failed ({type(exc).__name__})",
        }
        if isinstance(exc, TimeoutError):
            response["indeterminate"] = True
        return response


class FakePiEngine:
    """Fake Pi used for protocol and crash tests; it never executes tools."""

    protocol_version = "pi-v1"

    def __init__(self, coordinator: RunCoordinator, *, engine_session_id: str = "fake-engine"):
        self.coordinator = coordinator
        self.engine_session_id = engine_session_id
        self.state = PiSidecarState.CREATED

    def run_once(self, run: RunHandle, *, prompt: str, crash: bool = False, on_tool_request: Callable[[dict[str, Any]], Any] | None = None, action_handler: Callable[[dict[str, Any]], Any] | None = None) -> list[PiMessage]:
        self.state = PiSidecarState.RUNNING
        messages: list[PiMessage] = []
        messages.append(self._emit(run, "engine_started", payload={"engine": "fake-pi"}))
        messages.append(self._emit(run, "turn_started", turn_id="turn-1", payload={"prompt": prompt}))
        if crash:
            self.state = PiSidecarState.CRASHED
            messages.append(self._emit(run, "engine_crashed", turn_id="turn-1", payload={"reason": "sidecar crash"}))
            return messages
        request = {"tool_name": "none", "call_id": "call-1"}
        messages.append(self._emit(run, "model_response", turn_id="turn-1", call_id="call-1", payload={"text": "done"}))
        callback = action_handler or on_tool_request
        if callback:
            callback(request)
        messages.append(self._emit(run, "turn_finished", turn_id="turn-1", payload={"agent_end": True}))
        self.state = PiSidecarState.STOPPED
        messages.append(self._emit(run, "engine_stopped", payload={}))
        return messages

    def _emit(self, run: RunHandle, message_type: str, *, turn_id: str = "", call_id: str = "", payload: dict[str, Any] | None = None) -> PiMessage:
        message = PiMessage(self.protocol_version, message_type, run.run_id, self.engine_session_id, turn_id, call_id, f"{message_type}:{turn_id}:{call_id}", True, payload)
        self.coordinator.record_observation(run, event_type=message_type, payload=payload or {}, producer="pi", call_id=call_id, idempotency_key=message.message_id)
        return message
