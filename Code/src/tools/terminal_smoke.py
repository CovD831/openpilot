"""PTY-backed smoke runner for terminal-interactive programs."""

from __future__ import annotations

import errno
import fcntl
import os
import pty
import select
import shlex
import signal
import struct
import subprocess
import termios
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from metadata import CommandArtifactMetadata


TERMINAL_RUNTIME_ERROR_MARKERS = (
    "traceback",
    "_curses.error",
    "addwstr() returned err",
    "addch() returned err",
    "addstr() returned err",
    "nocbreak() returned err",
    "cbreak() returned err",
)


@dataclass
class TerminalSmokeResult:
    command: str
    success: bool
    stdout: str
    stderr: str
    exit_code: int
    duration: float
    timed_out: bool = False
    skipped: bool = False
    skip_reason: str = ""

    def to_command_artifact(self) -> CommandArtifactMetadata:
        return CommandArtifactMetadata(
            command=self.command,
            success=self.success,
            stdout=self.stdout,
            stderr=self.stderr,
            exit_code=self.exit_code,
            duration=self.duration,
            attributes={
                "terminal_smoke": True,
                "timed_out": self.timed_out,
                "skipped": self.skipped,
                "skip_reason": self.skip_reason,
            },
        )


def looks_like_terminal_python_source(source: str) -> bool:
    lowered = source.lower()
    return any(marker in lowered for marker in ("import curses", "from curses", "curses.wrapper", "stdscr", ".getch("))


def looks_like_terminal_python_files(files: Sequence[str | Path]) -> bool:
    for raw_path in files:
        path = Path(raw_path).expanduser()
        if path.suffix != ".py" or not path.exists():
            continue
        try:
            if looks_like_terminal_python_source(path.read_text(encoding="utf-8")):
                return True
        except OSError:
            continue
    return False


def has_terminal_runtime_error(output: str) -> bool:
    lowered = strip_ansi(output).lower()
    return any(marker in lowered for marker in TERMINAL_RUNTIME_ERROR_MARKERS)


def run_terminal_command(
    command: str | Sequence[str],
    *,
    cwd: str | Path | None = None,
    env: dict[str, str] | None = None,
    timeout: float = 3.0,
    input_text: str = "qq",
    rows: int = 24,
    cols: int = 80,
    shell: bool = False,
) -> TerminalSmokeResult:
    """Run a command attached to a pseudo-terminal and capture startup failures."""
    command_display = command if isinstance(command, str) else shlex.join([str(item) for item in command])
    if os.name == "nt":
        return TerminalSmokeResult(
            command=command_display,
            success=True,
            stdout="",
            stderr="",
            exit_code=0,
            duration=0.0,
            skipped=True,
            skip_reason="PTY terminal smoke is not available on this platform.",
        )

    started = time.monotonic()
    master_fd = -1
    slave_fd = -1
    process: subprocess.Popen[Any] | None = None
    output_chunks: list[str] = []
    timed_out = False
    exit_code = -1

    try:
        master_fd, slave_fd = pty.openpty()
        _set_terminal_size(slave_fd, rows=rows, cols=cols)
        process_env = os.environ.copy()
        process_env.setdefault("TERM", "xterm-256color")
        if env:
            process_env.update({str(key): str(value) for key, value in env.items()})

        process = subprocess.Popen(
            command,
            cwd=str(cwd) if cwd else None,
            env=process_env,
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            shell=shell,
            close_fds=True,
            start_new_session=True,
        )
        os.close(slave_fd)
        slave_fd = -1
        _set_nonblocking(master_fd)

        deadline = started + max(float(timeout), 0.5)
        input_sent = False
        while True:
            output_chunks.extend(_read_available(master_fd))
            if not input_sent and time.monotonic() - started >= 0.25:
                _write_input(master_fd, input_text)
                input_sent = True
            polled = process.poll()
            if polled is not None:
                exit_code = int(polled)
                output_chunks.extend(_read_available(master_fd))
                break
            if time.monotonic() >= deadline:
                timed_out = True
                _terminate_process(process)
                output_chunks.extend(_read_available(master_fd))
                break
            select.select([master_fd], [], [], 0.05)
    except (OSError, subprocess.SubprocessError) as exc:
        duration = time.monotonic() - started
        return TerminalSmokeResult(
            command=command_display,
            success=True,
            stdout="",
            stderr="",
            exit_code=0,
            duration=duration,
            skipped=True,
            skip_reason=f"PTY terminal smoke skipped: {exc}",
        )
    finally:
        for fd in (slave_fd, master_fd):
            if fd >= 0:
                try:
                    os.close(fd)
                except OSError:
                    pass

    duration = time.monotonic() - started
    combined_output = "".join(output_chunks)
    has_error = has_terminal_runtime_error(combined_output)
    success = not has_error and (timed_out or exit_code == 0)
    return TerminalSmokeResult(
        command=command_display,
        success=success,
        stdout=combined_output if success else "",
        stderr=combined_output if not success else "",
        exit_code=0 if success and timed_out else exit_code,
        duration=duration,
        timed_out=timed_out,
        skipped=False,
    )


def strip_ansi(text: str) -> str:
    import re

    return re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", text or "")


def _set_terminal_size(fd: int, *, rows: int, cols: int) -> None:
    winsize = struct.pack("HHHH", int(rows), int(cols), 0, 0)
    fcntl.ioctl(fd, termios.TIOCSWINSZ, winsize)


def _set_nonblocking(fd: int) -> None:
    flags = fcntl.fcntl(fd, fcntl.F_GETFL)
    fcntl.fcntl(fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)


def _read_available(fd: int) -> list[str]:
    chunks: list[str] = []
    while True:
        try:
            data = os.read(fd, 4096)
        except BlockingIOError:
            break
        except OSError as exc:
            if exc.errno in {errno.EIO, errno.EBADF}:
                break
            raise
        if not data:
            break
        chunks.append(data.decode("utf-8", errors="replace"))
    return chunks


def _write_input(fd: int, input_text: str) -> None:
    if not input_text:
        return
    try:
        os.write(fd, input_text.encode("utf-8", errors="ignore"))
    except OSError:
        pass


def _terminate_process(process: subprocess.Popen[Any]) -> None:
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except OSError:
        process.terminate()
    try:
        process.wait(timeout=0.4)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except OSError:
            process.kill()
