"""Read-only tool bridge: Pi tool calls -> scoped file reads (LF-JSONL unix socket)."""

from __future__ import annotations

import json
import socket
import tempfile
import threading
from pathlib import Path
from typing import Any, Callable

_MAX_REQUEST_BYTES = 1_000_000
_MAX_CONTENT_BYTES = 16_384
_CONNECTION_TIMEOUT_SECONDS = 5.0
_ALLOWED_TOOLS = frozenset({"openpilot_read"})


class ReadOnlyToolBridge:
    """Serves exactly one tool (openpilot_read) against the declared read scope.

    The scope is a set of roots: a request path is served only when it resolves
    inside one of the roots (or equals a file root). L0 defaults the scope to
    the whole project; L1 admission narrows it.
    """

    def __init__(
        self,
        scoped_roots: tuple[str, ...],
        *,
        on_request: Callable[[dict[str, Any]], None] | None = None,
        on_result: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self.scoped_roots = tuple(Path(root).expanduser().resolve(strict=False) for root in scoped_roots)
        self.on_request = on_request
        self.on_result = on_result
        self._temporary: tempfile.TemporaryDirectory[str] | None = None
        self._server: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self.socket_path = ""

    def start(self) -> None:
        self._temporary = tempfile.TemporaryDirectory(prefix="op0-tool-")
        self.socket_path = str(Path(self._temporary.name) / "bridge.sock")
        self._server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._server.bind(self.socket_path)
        self._server.listen(8)
        self._server.settimeout(0.1)
        self._thread = threading.Thread(target=self._serve, name="op0-tool-bridge", daemon=True)
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
        while not self._stop.is_set():
            try:
                connection, _ = self._server.accept()
            except TimeoutError:
                continue
            except OSError:
                return
            with connection:
                connection.settimeout(_CONNECTION_TIMEOUT_SECONDS)
                request = self._read_request(connection)
                response = self._handle(request)
                try:
                    connection.sendall(
                        json.dumps(response, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
                        + b"\n"
                    )
                except OSError:
                    continue

    @staticmethod
    def _read_request(connection: socket.socket) -> dict[str, Any]:
        buffer = bytearray()
        while b"\n" not in buffer:
            chunk = connection.recv(4096)
            if not chunk:
                raise EOFError("tool bridge client disconnected")
            buffer.extend(chunk)
            if len(buffer) > _MAX_REQUEST_BYTES:
                raise ValueError("tool bridge request is too large")
        decoded = json.loads(bytes(buffer.split(b"\n", 1)[0]).decode("utf-8"))
        if not isinstance(decoded, dict):
            raise ValueError("tool bridge request must be a JSON object")
        return decoded

    def _handle(self, request: dict[str, Any]) -> dict[str, Any]:
        call_id = str(request.get("toolCallId") or "")
        try:
            if request.get("toolName") not in _ALLOWED_TOOLS or not call_id:
                raise ValueError("invalid OpenPilot tool request")
            if self.on_request is not None:
                self.on_request(request)
            content = self._read_scoped(str((request.get("args") or {}).get("path") or ""))
            response: dict[str, Any] = {
                "toolCallId": call_id,
                "success": True,
                "content": _bounded_content(content),
            }
        except Exception as exc:  # noqa: BLE001
            response = {
                "toolCallId": call_id,
                "success": False,
                "content": f"OpenPilot tool request failed ({type(exc).__name__})",
            }
        if self.on_result is not None:
            try:
                self.on_result({"toolCallId": call_id, "success": response["success"]})
            except Exception:  # noqa: BLE001
                pass
        return response

    def _read_scoped(self, raw_path: str) -> str:
        if not raw_path:
            raise ValueError("openpilot_read requires a path")
        path = Path(raw_path).expanduser()
        if not path.is_absolute() and self.scoped_roots:
            path = self.scoped_roots[0] / path
        resolved = path.resolve(strict=False)
        if not self._in_scope(resolved):
            raise PermissionError("path is outside the declared read scope")
        if not resolved.is_file():
            raise FileNotFoundError(f"path is not a regular file: {raw_path}")
        return resolved.read_text(encoding="utf-8", errors="replace")

    def _in_scope(self, resolved: Path) -> bool:
        for root in self.scoped_roots:
            if resolved == root:
                return True
            if root.is_dir() and root in resolved.parents:
                return True
        return False


def _bounded_content(content: str) -> str:
    encoded = content.encode("utf-8")
    if len(encoded) <= _MAX_CONTENT_BYTES:
        return content
    marker = "<truncated>"
    budget = _MAX_CONTENT_BYTES - len(marker.encode("utf-8"))
    return encoded[:budget].decode("utf-8", errors="ignore") + marker
