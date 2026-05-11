"""Enhanced command tool with risk assessment and confidence scoring."""

from __future__ import annotations

import os
import platform
import re
import subprocess
from dataclasses import dataclass
from enum import Enum
from typing import Any

from pydantic import BaseModel


class RiskLevel(str, Enum):
    """Command risk levels."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ExecutionMode(str, Enum):
    """Command execution modes."""
    DRY_RUN = "dry_run"
    INTERACTIVE = "interactive"
    AUTOMATIC = "automatic"


@dataclass
class RiskAssessment:
    """Risk assessment for a command."""

    risk_level: RiskLevel
    risk_factors: list[str]
    affected_paths: list[str]
    requires_confirmation: bool
    recommendation: str


class CommandResult(BaseModel):
    """Result of command execution."""

    command: str
    success: bool
    stdout: str
    stderr: str
    exit_code: int
    duration: float
    risk_assessment: dict[str, Any] | None = None


class CommandTool:
    """Enhanced command execution with risk assessment."""

    # Destructive command patterns
    DESTRUCTIVE_PATTERNS = [
        r'\brm\b.*-rf',
        r'\brm\b.*-fr',
        r'\bformat\b',
        r'\bdd\b',
        r'\bmkfs\b',
        r'\bfdisk\b',
        r'\bparted\b',
    ]

    # High-risk command patterns
    HIGH_RISK_PATTERNS = [
        r'\brm\b',
        r'\bchmod\b',
        r'\bchown\b',
        r'\bsudo\b',
        r'\bsu\b',
        r'\bkill\b',
        r'\bpkill\b',
        r'\bshutdown\b',
        r'\breboot\b',
    ]

    # Medium-risk patterns
    MEDIUM_RISK_PATTERNS = [
        r'\bmv\b',
        r'\bcp\b',
        r'\bmkdir\b',
        r'\btouch\b',
        r'\bwrite\b',
        r'\b>\b',
        r'\b>>\b',
    ]

    def __init__(self, default_timeout: float = 30.0):
        """Initialize command tool.

        Args:
            default_timeout: Default command timeout in seconds
        """
        self.default_timeout = default_timeout
        self.system = platform.system()

    def assess_risk(self, command: str) -> RiskAssessment:
        """Assess risk of a command.

        Args:
            command: Command to assess

        Returns:
            RiskAssessment
        """
        risk_factors = []
        affected_paths = []
        risk_level = RiskLevel.LOW

        # Check for destructive patterns
        for pattern in self.DESTRUCTIVE_PATTERNS:
            if re.search(pattern, command, re.IGNORECASE):
                risk_factors.append(f"Destructive operation: {pattern}")
                risk_level = RiskLevel.CRITICAL

        # Check for high-risk patterns
        if risk_level != RiskLevel.CRITICAL:
            for pattern in self.HIGH_RISK_PATTERNS:
                if re.search(pattern, command, re.IGNORECASE):
                    risk_factors.append(f"High-risk operation: {pattern}")
                    risk_level = RiskLevel.HIGH

        # Check for medium-risk patterns
        if risk_level == RiskLevel.LOW:
            for pattern in self.MEDIUM_RISK_PATTERNS:
                if re.search(pattern, command, re.IGNORECASE):
                    risk_factors.append(f"File modification: {pattern}")
                    risk_level = RiskLevel.MEDIUM

        # Extract file paths
        affected_paths = self._extract_paths(command)

        # Determine if confirmation required
        requires_confirmation = risk_level in (RiskLevel.HIGH, RiskLevel.CRITICAL)

        # Generate recommendation
        recommendation = self._generate_recommendation(risk_level, risk_factors)

        return RiskAssessment(
            risk_level=risk_level,
            risk_factors=risk_factors,
            affected_paths=affected_paths,
            requires_confirmation=requires_confirmation,
            recommendation=recommendation
        )

    def estimate_confidence(self, command: str) -> float:
        """Estimate confidence in command execution.

        Args:
            command: Command to estimate

        Returns:
            Confidence score (0.0 to 1.0)
        """
        confidence = 1.0

        # Check command syntax
        if not command.strip():
            return 0.0

        # Check for common command errors
        if command.count('"') % 2 != 0 or command.count("'") % 2 != 0:
            confidence *= 0.5  # Unmatched quotes

        # Check for pipe errors
        if '|' in command:
            parts = command.split('|')
            if any(not p.strip() for p in parts):
                confidence *= 0.7  # Empty pipe segment

        # Check for path existence
        paths = self._extract_paths(command)
        for path in paths:
            if not os.path.exists(path):
                confidence *= 0.8  # Path doesn't exist

        return max(0.0, min(1.0, confidence))

    def execute(
        self,
        command: str,
        mode: ExecutionMode = ExecutionMode.AUTOMATIC,
        timeout: float | None = None,
        cwd: str | None = None,
        env: dict[str, str] | None = None
    ) -> CommandResult:
        """Execute a command.

        Args:
            command: Command to execute
            mode: Execution mode
            timeout: Command timeout
            cwd: Working directory
            env: Environment variables

        Returns:
            CommandResult
        """
        import time

        # Assess risk
        risk_assessment = self.assess_risk(command)

        # Handle dry run
        if mode == ExecutionMode.DRY_RUN:
            return CommandResult(
                command=command,
                success=True,
                stdout=f"[DRY RUN] Would execute: {command}",
                stderr="",
                exit_code=0,
                duration=0.0,
                risk_assessment=risk_assessment.__dict__
            )

        # Handle interactive mode (would need user confirmation in real implementation)
        if mode == ExecutionMode.INTERACTIVE and risk_assessment.requires_confirmation:
            # In real implementation, prompt user here
            pass

        # Execute command
        timeout = timeout or self.default_timeout
        start_time = time.time()

        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=cwd,
                env=env or os.environ.copy()
            )

            duration = time.time() - start_time

            return CommandResult(
                command=command,
                success=result.returncode == 0,
                stdout=result.stdout,
                stderr=result.stderr,
                exit_code=result.returncode,
                duration=duration,
                risk_assessment=risk_assessment.__dict__
            )

        except subprocess.TimeoutExpired:
            duration = time.time() - start_time
            return CommandResult(
                command=command,
                success=False,
                stdout="",
                stderr=f"Command timed out after {timeout}s",
                exit_code=-1,
                duration=duration,
                risk_assessment=risk_assessment.__dict__
            )

        except Exception as e:
            duration = time.time() - start_time
            return CommandResult(
                command=command,
                success=False,
                stdout="",
                stderr=str(e),
                exit_code=-1,
                duration=duration,
                risk_assessment=risk_assessment.__dict__
            )

    def _extract_paths(self, command: str) -> list[str]:
        """Extract file paths from command."""
        # Simple path extraction (can be improved)
        paths = []
        tokens = command.split()

        for token in tokens:
            # Skip flags
            if token.startswith('-'):
                continue

            # Check if looks like a path
            if '/' in token or '\\' in token or '.' in token:
                # Remove quotes
                path = token.strip('"').strip("'")
                if path and not path.startswith('$'):
                    paths.append(path)

        return paths

    def _generate_recommendation(self, risk_level: RiskLevel, risk_factors: list[str]) -> str:
        """Generate recommendation based on risk."""
        if risk_level == RiskLevel.CRITICAL:
            return "CRITICAL: This command is irreversible and highly destructive. Confirm before proceeding."
        elif risk_level == RiskLevel.HIGH:
            return "HIGH RISK: This command may cause significant changes. Review carefully before executing."
        elif risk_level == RiskLevel.MEDIUM:
            return "MEDIUM RISK: This command will modify files. Ensure you have backups if needed."
        else:
            return "LOW RISK: This command is safe to execute."
