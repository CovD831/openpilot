"""Enhanced file reading tools with adaptive strategies."""

from __future__ import annotations

import mimetypes
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel


class FileType(str, Enum):
    """File type categories."""
    CODE = "code"
    DATABASE = "database"
    CONFIG = "config"
    LOG = "log"
    DATA = "data"
    BINARY = "binary"
    TEXT = "text"
    UNKNOWN = "unknown"


@dataclass
class FileReadStrategy:
    """Strategy for reading a file."""

    file_type: FileType
    read_full: bool
    max_lines: int | None
    max_size_mb: float | None
    encoding: str = "utf-8"


class FileReadResult(BaseModel):
    """Result of file reading operation."""

    file_path: str
    file_type: FileType
    content: str
    lines_read: int
    total_lines: int | None
    file_size_bytes: int
    truncated: bool
    encoding: str
    metadata: dict[str, Any] = {}


class AdaptiveFileReader:
    """File reader with adaptive strategies based on file type."""

    # File type detection rules
    FILE_TYPE_RULES = {
        FileType.CODE: {
            "extensions": [
                ".py", ".js", ".ts", ".tsx", ".jsx", ".java", ".cpp", ".c", ".h",
                ".cs", ".go", ".rs", ".rb", ".php", ".swift", ".kt", ".scala",
                ".sh", ".bash", ".zsh", ".fish"
            ],
            "read_full": True,
            "max_lines": None,
            "max_size_mb": 5.0
        },
        FileType.DATABASE: {
            "extensions": [".sql", ".db", ".sqlite", ".sqlite3"],
            "read_full": False,
            "max_lines": 50,
            "max_size_mb": 1.0
        },
        FileType.CONFIG: {
            "extensions": [
                ".json", ".yaml", ".yml", ".toml", ".ini", ".conf",
                ".cfg", ".xml", ".env", ".properties"
            ],
            "read_full": True,
            "max_lines": None,
            "max_size_mb": 1.0
        },
        FileType.LOG: {
            "extensions": [".log", ".out", ".err"],
            "read_full": False,
            "max_lines": 100,
            "max_size_mb": 2.0
        },
        FileType.DATA: {
            "extensions": [".csv", ".tsv", ".dat", ".txt"],
            "read_full": False,
            "max_lines": 20,
            "max_size_mb": 1.0
        },
        FileType.BINARY: {
            "extensions": [
                ".exe", ".dll", ".so", ".dylib", ".bin", ".dat",
                ".zip", ".tar", ".gz", ".bz2", ".7z",
                ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".ico",
                ".mp3", ".mp4", ".avi", ".mov", ".wav",
                ".pdf", ".doc", ".docx", ".xls", ".xlsx"
            ],
            "read_full": False,
            "max_lines": 0,
            "max_size_mb": 0.0
        }
    }

    def __init__(self, default_encoding: str = "utf-8"):
        """Initialize file reader.

        Args:
            default_encoding: Default file encoding
        """
        self.default_encoding = default_encoding

    def detect_file_type(self, file_path: Path) -> FileType:
        """Detect file type based on extension and content.

        Args:
            file_path: Path to file

        Returns:
            Detected file type
        """
        extension = file_path.suffix.lower()

        # Check against known extensions
        for file_type, rules in self.FILE_TYPE_RULES.items():
            if extension in rules["extensions"]:
                return file_type

        # Try MIME type detection
        mime_type, _ = mimetypes.guess_type(str(file_path))
        if mime_type:
            if mime_type.startswith("text/"):
                return FileType.TEXT
            elif mime_type.startswith("application/"):
                return FileType.BINARY

        return FileType.UNKNOWN

    def get_read_strategy(self, file_path: Path) -> FileReadStrategy:
        """Get reading strategy for a file.

        Args:
            file_path: Path to file

        Returns:
            FileReadStrategy for the file
        """
        file_type = self.detect_file_type(file_path)

        # Get rules for file type
        if file_type in self.FILE_TYPE_RULES:
            rules = self.FILE_TYPE_RULES[file_type]
            return FileReadStrategy(
                file_type=file_type,
                read_full=rules["read_full"],
                max_lines=rules["max_lines"],
                max_size_mb=rules["max_size_mb"],
                encoding=self.default_encoding
            )

        # Default strategy for unknown types
        return FileReadStrategy(
            file_type=file_type,
            read_full=False,
            max_lines=100,
            max_size_mb=1.0,
            encoding=self.default_encoding
        )

    def read_file(
        self,
        file_path: str | Path,
        strategy: FileReadStrategy | None = None,
        offset: int = 0
    ) -> FileReadResult:
        """Read a file using adaptive strategy.

        Args:
            file_path: Path to file
            strategy: Optional custom strategy (auto-detected if None)
            offset: Line offset to start reading from

        Returns:
            FileReadResult with file content

        Raises:
            FileNotFoundError: If file doesn't exist
            PermissionError: If file cannot be read
            ValueError: If file is too large
        """
        file_path = Path(file_path)

        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        if not file_path.is_file():
            raise ValueError(f"Not a file: {file_path}")

        # Get strategy
        if strategy is None:
            strategy = self.get_read_strategy(file_path)

        # Check file size
        file_size = file_path.stat().st_size
        max_size_bytes = (strategy.max_size_mb * 1024 * 1024) if strategy.max_size_mb else float('inf')

        if file_size > max_size_bytes:
            raise ValueError(
                f"File too large: {file_size / (1024*1024):.2f}MB "
                f"(max: {strategy.max_size_mb}MB)"
            )

        # Handle binary files
        if strategy.file_type == FileType.BINARY:
            return FileReadResult(
                file_path=str(file_path),
                file_type=strategy.file_type,
                content="[Binary file - content not displayed]",
                lines_read=0,
                total_lines=0,
                file_size_bytes=file_size,
                truncated=False,
                encoding="binary",
                metadata={"mime_type": mimetypes.guess_type(str(file_path))[0]}
            )

        # Read text file
        try:
            with open(file_path, 'r', encoding=strategy.encoding) as f:
                lines = f.readlines()

            total_lines = len(lines)

            # Apply offset
            if offset > 0:
                lines = lines[offset:]

            # Apply line limit
            truncated = False
            if strategy.max_lines and len(lines) > strategy.max_lines:
                lines = lines[:strategy.max_lines]
                truncated = True

            content = ''.join(lines)
            lines_read = len(lines)

            return FileReadResult(
                file_path=str(file_path),
                file_type=strategy.file_type,
                content=content,
                lines_read=lines_read,
                total_lines=total_lines,
                file_size_bytes=file_size,
                truncated=truncated,
                encoding=strategy.encoding
            )

        except UnicodeDecodeError as e:
            # Try alternative encodings
            for alt_encoding in ['latin-1', 'cp1252', 'iso-8859-1']:
                try:
                    with open(file_path, 'r', encoding=alt_encoding) as f:
                        lines = f.readlines()

                    if strategy.max_lines:
                        lines = lines[:strategy.max_lines]

                    return FileReadResult(
                        file_path=str(file_path),
                        file_type=strategy.file_type,
                        content=''.join(lines),
                        lines_read=len(lines),
                        total_lines=None,
                        file_size_bytes=file_size,
                        truncated=strategy.max_lines is not None,
                        encoding=alt_encoding,
                        metadata={"encoding_fallback": True}
                    )
                except UnicodeDecodeError:
                    continue

            raise ValueError(f"Cannot decode file with any known encoding: {e}") from e

    def read_file_sample(self, file_path: str | Path, num_lines: int = 10) -> FileReadResult:
        """Read a sample of lines from a file.

        Args:
            file_path: Path to file
            num_lines: Number of lines to read

        Returns:
            FileReadResult with sample content
        """
        file_path = Path(file_path)
        strategy = self.get_read_strategy(file_path)
        strategy.max_lines = num_lines
        strategy.read_full = False

        return self.read_file(file_path, strategy)

    def read_file_tail(self, file_path: str | Path, num_lines: int = 100) -> FileReadResult:
        """Read the last N lines of a file.

        Args:
            file_path: Path to file
            num_lines: Number of lines to read from end

        Returns:
            FileReadResult with tail content
        """
        file_path = Path(file_path)

        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        strategy = self.get_read_strategy(file_path)

        try:
            with open(file_path, 'r', encoding=strategy.encoding) as f:
                lines = f.readlines()

            total_lines = len(lines)
            tail_lines = lines[-num_lines:] if len(lines) > num_lines else lines

            return FileReadResult(
                file_path=str(file_path),
                file_type=strategy.file_type,
                content=''.join(tail_lines),
                lines_read=len(tail_lines),
                total_lines=total_lines,
                file_size_bytes=file_path.stat().st_size,
                truncated=len(lines) > num_lines,
                encoding=strategy.encoding,
                metadata={"read_mode": "tail"}
            )

        except UnicodeDecodeError:
            return FileReadResult(
                file_path=str(file_path),
                file_type=FileType.BINARY,
                content="[Cannot decode file - possibly binary]",
                lines_read=0,
                total_lines=0,
                file_size_bytes=file_path.stat().st_size,
                truncated=False,
                encoding="unknown"
            )
