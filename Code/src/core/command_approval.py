"""Central command approval policy for shell execution tools."""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable


@dataclass(frozen=True)
class CommandApprovalDecision:
    command: str
    cwd: str = ""
    requires_confirmation: bool = False
    auto_approved: bool = False
    risk_level: str = "low"
    reasons: list[str] = field(default_factory=list)

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "command": self.command,
            "cwd": self.cwd,
            "requires_confirmation": self.requires_confirmation,
            "auto_approved": self.auto_approved,
            "risk_level": self.risk_level,
            "reasons": list(self.reasons),
        }


class CommandApprovalGate:
    """Decide whether a command can run automatically or needs user approval."""

    def evaluate(self, command: str, *, cwd: str | None = None) -> CommandApprovalDecision:
        command = str(command or "").strip()
        cwd = str(cwd or "").strip()
        reasons: list[str] = []
        lowered = f" {command.lower()} "
        tokens = _split_command(command)

        if re.search(r"(^|\s)(sudo|su)\b", lowered):
            reasons.append("Command requests elevated privileges.")
        if any(token in {">", ">>"} for token in tokens):
            reasons.append("Command writes through shell redirection.")
        if any(token in {"rm", "chmod", "chown", "kill", "pkill", "shutdown", "reboot"} for token in tokens):
            reasons.append("Command uses a high-risk system or destructive operation.")
        if any(token in {"brew", "apt", "apt-get", "yum", "dnf", "pacman"} for token in tokens):
            reasons.append("Command uses a system package manager.")
        if _writes_system_path(command):
            reasons.append("Command may write to a system-level path.")
        if _looks_like_global_package_install(tokens, command, cwd):
            reasons.append("Command appears to install packages outside the project virtual environment.")

        if not reasons and _is_known_safe_project_command(tokens, command, cwd):
            return CommandApprovalDecision(command=command, cwd=cwd, auto_approved=True)

        if reasons:
            return CommandApprovalDecision(
                command=command,
                cwd=cwd,
                requires_confirmation=True,
                risk_level="high",
                reasons=reasons,
            )

        return CommandApprovalDecision(command=command, cwd=cwd, auto_approved=True, risk_level="low")

    def approve(
        self,
        command: str,
        *,
        cwd: str | None = None,
        approval_callback: Callable[[CommandApprovalDecision], bool] | None = None,
    ) -> CommandApprovalDecision:
        decision = self.evaluate(command, cwd=cwd)
        if not decision.requires_confirmation:
            return decision
        if approval_callback is None:
            raise PermissionError(_declined_message(decision, "No user confirmation callback was available."))
        if not approval_callback(decision):
            raise PermissionError(_declined_message(decision, "User declined command execution."))
        return CommandApprovalDecision(
            command=decision.command,
            cwd=decision.cwd,
            requires_confirmation=True,
            auto_approved=False,
            risk_level=decision.risk_level,
            reasons=decision.reasons,
        )


def _declined_message(decision: CommandApprovalDecision, prefix: str) -> str:
    reasons = "; ".join(decision.reasons) or "Command requires confirmation."
    return f"{prefix} Command: {decision.command}. Reason: {reasons}"


def _split_command(command: str) -> list[str]:
    try:
        return shlex.split(command)
    except ValueError:
        return command.split()


def _writes_system_path(command: str) -> bool:
    lowered = command.lower()
    return any(path in lowered for path in ("/usr/", "/system/", "/library/", "/opt/homebrew/"))


def _looks_like_global_package_install(tokens: list[str], command: str, cwd: str) -> bool:
    lowered = command.lower()
    if not any(token in tokens for token in ("pip", "pip3", "npm", "pnpm", "yarn")):
        return False
    if not any(action in tokens for action in ("install", "add", "i")):
        return False
    if ".venv" in lowered:
        return False
    if cwd and str(Path(cwd) / ".venv") in command:
        return False
    return True


def _is_known_safe_project_command(tokens: list[str], command: str, cwd: str) -> bool:
    lowered = command.lower()
    if ".venv" in lowered and " pip " in f" {lowered} ":
        return True
    if ".venv" in lowered and " -m pip " in lowered:
        return True
    if " -m compileall " in lowered:
        return True
    if cwd and str(Path(cwd) / ".venv") in command and "pip" in lowered:
        return True
    executable = Path(tokens[0]).name if tokens else ""
    return executable in {"python", "python3"} and "-m" in tokens and "compileall" in tokens
