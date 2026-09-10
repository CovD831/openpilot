"""OS-level sandbox for bash execution (macOS Seatbelt).

Admission is the policy layer: it decides what the agent may do. This
module is the physical layer: even a bypassed or buggy gate cannot let a
sandboxed bash command touch anything outside the workspace. The profile
is generated from the same scoped roots admission uses, so both layers
enforce one boundary.

Design mirrors Codex CLI and Claude Code (both wrap commands with
sandbox-exec): deny-default posture, binary network choice (Seatbelt has
no domain-level filtering), and the ledger directory (.openpilot) is
forced read-only for bash - the append-only audit chain is an asset no
approved command may rewrite.
"""

from __future__ import annotations

import sys
from pathlib import Path

_SANDBOX_EXEC = Path("/usr/bin/sandbox-exec")
_SENSITIVE_READ_DENY = (".ssh", ".aws", ".gnupg", ".config/gcloud")


def available() -> bool:
    """Seatbelt exists only on macOS; sandbox-exec is deprecated by Apple
    but is the same primitive Claude Code and Codex CLI ship on."""
    return sys.platform == "darwin" and _SANDBOX_EXEC.is_file()


def _sbpl(path: str) -> str:
    return path.replace("\\", "\\\\").replace('"', '\\"')


def build_profile(scoped_roots: tuple[Path, ...], *, network: bool, home: str) -> str:
    """Generate the SBPL program. Reads are global (path resolution needs
    metadata everywhere) with credential directories denied; writes are
    scoped roots plus temp/devices only; network is all-or-nothing."""
    roots = " ".join(f'(subpath "{_sbpl(str(root))}")' for root in scoped_roots)
    sensitive = " ".join(f'(subpath "{_sbpl(home)}/{entry}")' for entry in _SENSITIVE_READ_DENY)
    primary = _sbpl(str(scoped_roots[0])) if scoped_roots else "/nonexistent"
    net = "" if network else "(deny network*)\n"
    return f"""(version 1)
(deny default)
(allow process-exec*)
(allow process-fork)
(allow process-info*)
(allow signal)
(allow sysctl-read)
(allow mach-lookup)
(allow mach-register)
(allow ipc-posix-shm*)
(allow ipc-posix-sem)
(allow pseudo-tty)
(allow file-ioctl)
(allow iokit-open)
(allow file-read-metadata)
(allow file-read*)
(deny file-read-data {sensitive})
(allow file-write*
  {roots}
  (subpath "/private/tmp")
  (subpath "/tmp")
  (subpath "/private/var/folders")
  (literal "/dev/null")
  (literal "/dev/tty"))
(deny file-write* (subpath "{primary}/.openpilot"))
{net}"""


def wrap_command(
    scoped_roots: tuple[Path, ...], command: str, *, network: bool, home: str
) -> list[str]:
    return [
        "/usr/bin/sandbox-exec",
        "-p",
        build_profile(scoped_roots, network=network, home=home),
        "/bin/bash",
        "-c",
        command,
    ]
