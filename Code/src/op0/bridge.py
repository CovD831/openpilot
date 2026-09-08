"""Tool bridge: Pi tool calls -> op0-adjudicated side effects (LF-JSONL unix socket).

Reads and search serve paths inside the declared scope. Patches and writes
require a consent covering the exact path; every bash command needs its own
approved consent. The consent decision lives in op0.admission, never in the
model or in Pi.
"""

from __future__ import annotations

import fnmatch
import json
import os
import re
import socket
import subprocess
import tempfile
import threading
from pathlib import Path
from typing import Any, Callable

_MAX_REQUEST_BYTES = 1_000_000
_MAX_CONTENT_BYTES = 16_384
_MAX_OUTPUT_BYTES = 8_000
_SEARCH_HIT_LIMIT = 60
_BASH_TIMEOUT_SECONDS = 60.0
_CONNECTION_TIMEOUT_SECONDS = 5.0
_SKIPPED_DIRS = {".git", ".openpilot", ".venv", "node_modules", "__pycache__", ".pytest_cache", "runs"}
_ALLOWED_TOOLS = frozenset(
    {"openpilot_read", "openpilot_patch", "openpilot_write", "openpilot_bash", "openpilot_search"}
)




def _bounded(text: str, limit: int) -> str:
    data = text.encode("utf-8", errors="replace")
    if len(data) <= limit:
        return text
    return data[:limit].decode("utf-8", errors="ignore") + "\n[truncated]"



def patched_text(old_text: str, line_start: int, line_end: int, replacement: str) -> str:
    """Pure line-range replacement; also used to render approval diffs."""
    lines = old_text.splitlines(keepends=True)
    if line_end > len(lines):
        raise ValueError(f"line range {line_start}-{line_end} exceeds file length {len(lines)}")
    before = "".join(lines[line_start - 1 : line_end])
    newline_style = "\r\n" if before.endswith("\r\n") else "\n"
    had_trailing_newline = before.endswith(("\n", "\r\n"))
    if replacement.endswith(("\n", "\r\n")) or not replacement:
        body = replacement.splitlines(keepends=True)
    elif had_trailing_newline:
        body = [line + newline_style for line in replacement.splitlines()]
    else:
        body = [replacement]
    lines[line_start - 1 : line_end] = body
    return "".join(lines)


class ReadOnlyToolBridge:
    """Serves reads/search (scope-checked) and patch/write/bash (consent-checked)."""

    def __init__(
        self,
        scoped_roots: tuple[str, ...],
        *,
        patch_authorizer: Callable[[str, dict[str, Any]], Any] | None = None,
        command_authorizer: Callable[[str, dict[str, Any]], Any] | None = None,
        on_patch_applied: Callable[[str, str, str, Any], None] | None = None,
        on_bash_executed: Callable[[str, int, str, Any], None] | None = None,
        on_request: Callable[[dict[str, Any]], None] | None = None,
        on_result: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self.scoped_roots = tuple(Path(root).expanduser().resolve(strict=False) for root in scoped_roots)
        self.patch_authorizer = patch_authorizer
        self.command_authorizer = command_authorizer
        self.on_patch_applied = on_patch_applied
        self.on_bash_executed = on_bash_executed
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
            # One thread per connection: an approval gate may hold this tool
            # call for a long time, and that must never stall other calls
            # (a blocked _serve here deadlocked the whole gateway once).
            threading.Thread(target=self._serve_connection, args=(connection,), daemon=True).start()

    def _serve_connection(self, connection: socket.socket) -> None:
        with connection:
            connection.settimeout(_CONNECTION_TIMEOUT_SECONDS)
            try:
                request = self._read_request(connection)
                response = self._handle(request)
            except (EOFError, ValueError, OSError):
                return
            try:
                connection.sendall(
                    json.dumps(response, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n"
                )
            except OSError:
                pass

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
            tool = request.get("toolName")
            if tool not in _ALLOWED_TOOLS or not call_id:
                raise ValueError("invalid OpenPilot tool request")
            if self.on_request is not None:
                self.on_request(request)
            args = dict(request.get("args") or {})
            if tool == "openpilot_read":
                content = self._read_scoped(str(args.get("path") or ""), args)
            elif tool == "openpilot_patch":
                content = self._apply_patch(args)
            elif tool == "openpilot_write":
                content = self._apply_write(args)
            elif tool == "openpilot_bash":
                content = self._run_bash(args)
            else:
                content = self._search(args)
            response: dict[str, Any] = {
                "toolCallId": call_id,
                "success": True,
                "content": _bounded_content(content),
            }
        except Exception as exc:  # noqa: BLE001
            response = {
                "toolCallId": call_id,
                "success": False,
                "content": _bounded_content(str(exc) or type(exc).__name__),
            }
        if self.on_result is not None:
            try:
                self.on_result(
                    {
                        "toolCallId": call_id,
                        "success": response["success"],
                        "preview": str(response.get("content") or "")[:240],
                    }
                )
            except Exception:  # noqa: BLE001
                pass
        return response

    # -- read ------------------------------------------------------------

    def _read_scoped(self, raw_path: str, args: dict[str, Any] | None = None) -> str:
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
        text = resolved.read_text(encoding="utf-8", errors="replace")
        # claude-code-style paging: 1-based offset, line-numbered output, so
        # big files are read in slices instead of pushing the model toward
        # bash workarounds.
        lines = text.splitlines()
        total = len(lines)
        offset = max(int((args or {}).get("offset") or 1), 1)
        limit = min(int((args or {}).get("limit") or 400), 800)
        start = min(offset - 1, total)
        end = min(start + limit, total)
        numbered = "\n".join(f"{n + 1:>6}\t{lines[n]}" for n in range(start, end))
        numbered = _bounded_content(numbered)
        if end < total:
            numbered += f"\n[showing lines {start + 1}-{end} of {total}; pass offset={end + 1} for the next page]"
        return numbered

    def _in_scope(self, resolved: Path) -> bool:
        for root in self.scoped_roots:
            if resolved == root:
                return True
            if root.is_dir() and root in resolved.parents:
                return True
        return False

    # -- patch -----------------------------------------------------------

    def _apply_patch(self, args: dict[str, Any]) -> str:
        if self.patch_authorizer is None:
            raise PermissionError("patching is not enabled in this session")
        raw_path = str(args.get("path") or "")
        consent = self.patch_authorizer(raw_path, args)
        path = Path(self._resolve_scoped(raw_path))
        line_start = int(args.get("lineStart") or 0)
        line_end = int(args.get("lineEnd") or 0)
        replacement = str(args.get("replacementText") or "")
        if line_start < 1 or line_end < line_start:
            raise ValueError("invalid line range")
        old_text = path.read_text(encoding="utf-8", errors="strict")
        old_lines = old_text.splitlines(keepends=True)
        before = "".join(old_lines[line_start - 1 : line_end])
        new_text = patched_text(old_text, line_start, line_end, replacement)
        from op0.receipts import file_hash

        hash_before = file_hash(path)
        path.write_text(new_text, encoding="utf-8")
        hash_after = file_hash(path)
        if self.on_patch_applied is not None:
            try:
                self.on_patch_applied(str(path), hash_before, hash_after, consent)
            except Exception:  # noqa: BLE001
                pass
        consent_id = getattr(consent, "consent_id", "")
        return (
            f"patch applied to {path.name} lines {line_start}-{line_end} "
            f"(consent {consent_id}); {len(before)} chars replaced by {len(replacement)}"
        )

    def _resolve_scoped(self, raw_path: str) -> str:
        path = Path(raw_path).expanduser()
        if not path.is_absolute() and self.scoped_roots:
            path = self.scoped_roots[0] / path
        resolved = path.resolve(strict=False)
        if not self._in_scope(resolved):
            raise PermissionError("path is outside the declared scope")
        return str(resolved)

    # -- write -----------------------------------------------------------

    def _apply_write(self, args: dict[str, Any]) -> str:
        if self.patch_authorizer is None:
            raise PermissionError("writing is not enabled in this session")
        raw_path = str(args.get("path") or "")
        content = str(args.get("content") or "")
        if not raw_path:
            raise ValueError("openpilot_write requires a path")
        resolved = Path(self._resolve_scoped(raw_path))
        consent = self.patch_authorizer(resolved, args)
        from op0.receipts import file_hash

        hash_before = file_hash(resolved) if resolved.is_file() else "absent"
        resolved.parent.mkdir(parents=True, exist_ok=True)
        resolved.write_text(content, encoding="utf-8")
        hash_after = file_hash(resolved)
        if self.on_patch_applied is not None:
            try:
                self.on_patch_applied(str(resolved), hash_before, hash_after, consent)
            except Exception:  # noqa: BLE001
                pass
        action = "overwrote" if hash_before != "absent" else "created"
        return f"{action} {resolved.name} ({len(content)} chars, consent {consent.consent_id})"

    # -- bash ------------------------------------------------------------

    def _run_bash(self, args: dict[str, Any]) -> str:
        if self.command_authorizer is None:
            raise PermissionError("bash is not enabled in this session")
        command = str(args.get("command") or "").strip()
        if not command:
            raise ValueError("openpilot_bash requires a command")
        consent = self.command_authorizer(command, args)
        try:
            completed = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=_BASH_TIMEOUT_SECONDS,
                cwd=self.scoped_roots[0] if self.scoped_roots else None,
            )
        except subprocess.TimeoutExpired as exc:
            if self.on_bash_executed is not None:
                try:
                    self.on_bash_executed(command, 124, f"timeout after {_BASH_TIMEOUT_SECONDS}s", consent)
                except Exception:  # noqa: BLE001
                    pass
            raise ValueError(f"command timed out after {_BASH_TIMEOUT_SECONDS}s") from exc
        output = (completed.stdout or "") + (("\n[stderr]\n" + completed.stderr) if completed.stderr else "")
        output = output.strip()
        if self.on_bash_executed is not None:
            try:
                self.on_bash_executed(command, completed.returncode, output, consent)
            except Exception:  # noqa: BLE001
                pass
        tail = output[-_MAX_OUTPUT_BYTES:]
        return f"exit {completed.returncode}\n{tail}" if tail else f"exit {completed.returncode}"

    # -- search ----------------------------------------------------------

    def _search(self, args: dict[str, Any]) -> str:
        pattern = str(args.get("pattern") or "")
        glob = str(args.get("glob") or "*")
        if not pattern:
            raise ValueError("openpilot_search requires a pattern")
        try:
            matcher = re.compile(pattern)
        except re.error:
            matcher = None
        root = self.scoped_roots[0] if self.scoped_roots else Path.cwd()
        hits: list[str] = []
        for current, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if d not in _SKIPPED_DIRS]
            for name in files:
                if not fnmatch.fnmatch(name, glob):
                    continue
                file_path = Path(current) / name
                if not self._in_scope(file_path):
                    continue
                try:
                    for number, line in enumerate(
                        file_path.read_text(encoding="utf-8", errors="replace").splitlines(), 1
                    ):
                        matched = matcher.search(line) if matcher is not None else pattern in line
                        if matched:
                            hits.append(f"{file_path.relative_to(root)}:{number}: {line.strip()[:200]}")
                            if len(hits) >= _SEARCH_HIT_LIMIT:
                                hits.append("(truncated)")
                                return "\n".join(hits)
                except OSError:
                    continue
        return "\n".join(hits) if hits else "(no matches)"


def _bounded_content(content: str) -> str:
    encoded = content.encode("utf-8")
    if len(encoded) <= _MAX_CONTENT_BYTES:
        return content
    marker = "<truncated>"
    budget = _MAX_CONTENT_BYTES - len(marker.encode("utf-8"))
    return encoded[:budget].decode("utf-8", errors="ignore") + marker
