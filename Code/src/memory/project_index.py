"""Deterministic file content indexes and directory sketches."""

from __future__ import annotations

import ast
import hashlib
import json
import math
import os
import re
from pathlib import Path
from typing import Any

from metadata import (
    DirectorySketchMetadata,
    FileContentIndexMetadata,
    FileContentSectionMetadata,
)


class ProjectIndexManager:
    """Maintain sidecar file indexes and per-directory sketch files without LLMs."""

    INDEX_ROOT = ".openpilot/file_indexes"
    SKETCH_NAME = "sketch.json"
    INDEX_VERSION = 2
    IGNORED_DIRS = {
        ".git",
        ".mypy_cache",
        ".openpilot",
        ".pytest_cache",
        ".venv",
        "__pycache__",
        "node_modules",
        "venv",
    }
    TEXT_SUFFIXES = {
        ".css",
        ".html",
        ".ini",
        ".js",
        ".json",
        ".jsx",
        ".md",
        ".py",
        ".rs",
        ".sh",
        ".toml",
        ".ts",
        ".tsx",
        ".txt",
        ".yaml",
        ".yml",
    }

    def __init__(self, root_path: str | Path = ".", *, embedding_service: Any | None = None) -> None:
        self.root_path = Path(root_path).expanduser()
        self.embedding_service = embedding_service

    @classmethod
    def for_path(cls, path: str | Path, *, embedding_service: Any | None = None) -> "ProjectIndexManager":
        return cls(_infer_project_root(Path(path).expanduser()), embedding_service=embedding_service)

    def update_file_index(self, file_path: str | Path) -> FileContentIndexMetadata:
        """Build and write the sidecar index for a file."""
        path = Path(file_path).expanduser()
        if not path.is_absolute():
            path = self.root_path / path
        if not path.exists() or not path.is_file():
            raise FileNotFoundError(f"Cannot index missing file: {path}")
        if self._is_ignored(path):
            raise ValueError(f"Cannot index ignored file: {path}")

        content = _read_text(path)
        relative = _relative_path(path, self.root_path)
        index_file = self.index_file_for(path)
        index = FileContentIndexMetadata(
            file_path=str(path),
            relative_path=relative,
            index_file=str(index_file),
            project_root=str(self.root_path),
            content_sha256=hashlib.sha256(content.encode("utf-8")).hexdigest(),
            language=_language_for_path(path),
            byte_size=path.stat().st_size,
            line_count=len(content.splitlines()),
            sections=self._sections_for(path, content, relative),
        )
        index_file.parent.mkdir(parents=True, exist_ok=True)
        index_file.write_text(json.dumps(index.to_json_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        return index

    def remove_file_index(self, file_path: str | Path) -> dict[str, Any]:
        """Remove a sidecar index after deleting a file."""
        path = Path(file_path).expanduser()
        if not path.is_absolute():
            path = self.root_path / path
        index_file = self.index_file_for(path)
        removed = False
        if index_file.exists():
            index_file.unlink()
            removed = True
        return {"index_file": str(index_file), "removed": removed}

    def update_directory_sketch(self, directory: str | Path) -> DirectorySketchMetadata:
        """Build and write one directory sketch from current file indexes."""
        directory_path = Path(directory).expanduser()
        if not directory_path.is_absolute():
            directory_path = self.root_path / directory_path
        files: dict[str, dict[str, Any]] = {}
        for path in sorted(item for item in directory_path.iterdir() if item.is_file()):
            if self._skip_project_file(path):
                continue
            try:
                index = self.update_file_index(path)
            except (OSError, UnicodeDecodeError, ValueError):
                continue
            files[path.name] = self._sketch_file_item(path, index)

        sketch = DirectorySketchMetadata(
            version=self.INDEX_VERSION,
            directory=str(directory_path),
            project_root=str(self.root_path),
            files=files,
        )
        sketch_path = directory_path / self.SKETCH_NAME
        sketch_path.write_text(json.dumps(sketch.to_json_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        return sketch

    def update_after_file_change(self, file_path: str | Path) -> dict[str, Any]:
        """Refresh sidecar index and containing directory sketch for a changed file."""
        path = Path(file_path).expanduser()
        if not path.is_absolute():
            path = self.root_path / path
        index = self.update_file_index(path)
        sketch = self.update_directory_sketch(path.parent)
        return {
            "file_index": index.to_json_dict(),
            "index_file": index.index_file,
            "sketch_file": str(path.parent / self.SKETCH_NAME),
            "sketch": sketch.to_json_dict(),
        }

    def update_after_file_delete(self, file_path: str | Path) -> dict[str, Any]:
        """Remove sidecar index and refresh the containing directory sketch."""
        path = Path(file_path).expanduser()
        if not path.is_absolute():
            path = self.root_path / path
        removal = self.remove_file_index(path)
        sketch = self.update_directory_sketch(path.parent)
        return {
            **removal,
            "sketch_file": str(path.parent / self.SKETCH_NAME),
            "sketch": sketch.to_json_dict(),
        }

    def index_file_for(self, file_path: str | Path) -> Path:
        path = Path(file_path).expanduser()
        if not path.is_absolute():
            path = self.root_path / path
        relative = Path(_relative_path(path, self.root_path))
        return self.root_path / self.INDEX_ROOT / relative.parent / f"{relative.name}.index.json"

    def _sections_for(self, path: Path, content: str, relative_path: str) -> list[FileContentSectionMetadata]:
        suffix = path.suffix.lower()
        if suffix == ".py":
            sections = _python_sections(content)
        elif suffix in {".md", ".markdown"}:
            sections = _markdown_sections(content)
        elif suffix == ".json":
            sections = _json_sections(content)
        else:
            sections = _text_sections(content)
        return [
            self._section_metadata(relative_path, content, section)
            for section in sections
            if section["line_start"] <= section["line_end"]
        ]

    def _section_metadata(
        self,
        relative_path: str,
        content: str,
        section: dict[str, Any],
    ) -> FileContentSectionMetadata:
        line_start = int(section["line_start"])
        line_end = int(section["line_end"])
        char_start, char_end = _line_char_span(content, line_start, line_end)
        summary = str(section.get("summary") or section.get("title") or "").strip()
        title = str(section.get("title") or summary or f"lines {line_start}-{line_end}")
        seed = f"{relative_path}:{title}:{line_start}:{line_end}:{summary}"
        return FileContentSectionMetadata(
            section_id=hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16],
            title=title[:160],
            section_type=str(section.get("section_type") or "text"),
            summary=summary[:600],
            embedding=self._embed(summary or title),
            line_start=line_start,
            line_end=line_end,
            char_start=char_start,
            char_end=char_end,
            symbol_name=str(section.get("symbol_name") or ""),
            parent_symbol=str(section.get("parent_symbol") or ""),
        )

    def _embed(self, text: str) -> list[float]:
        if self.embedding_service is not None and hasattr(self.embedding_service, "embed_text"):
            try:
                vector = self.embedding_service.embed_text(text)
                return [float(item) for item in vector]
            except Exception:
                pass
        return _stable_hash_embedding(text)

    def _sketch_file_item(self, path: Path, index: FileContentIndexMetadata) -> dict[str, Any]:
        section_summaries = [
            {
                "section_id": section.section_id,
                "title": section.title,
                "summary": section.summary,
                "section_type": section.section_type,
                "line_start": section.line_start,
                "line_end": section.line_end,
                "char_start": section.char_start,
                "char_end": section.char_end,
            }
            for section in index.sections[:24]
        ]
        description = _file_description(path, index)
        return {
            "name": path.name,
            "path": str(path),
            "suffix": path.suffix,
            "description": description,
            "function_description": description,
            "semantic_info": {
                "kind": "content_index",
                "terms": _terms(f"{path.name} {description}")[:32],
                "index_file": index.index_file,
                "content_sha256": index.content_sha256,
            },
            "content_index": {
                "index_file": index.index_file,
                "content_sha256": index.content_sha256,
                "language": index.language,
                "line_count": index.line_count,
                "sections": section_summaries,
            },
            "mtime": path.stat().st_mtime,
            "size": path.stat().st_size,
        }

    def _skip_project_file(self, path: Path) -> bool:
        return path.name == self.SKETCH_NAME or self._is_ignored(path)

    def _is_ignored(self, path: Path) -> bool:
        return any(part in self.IGNORED_DIRS for part in path.parts)


def _infer_project_root(path: Path) -> Path:
    directory = path if path.is_dir() else path.parent
    candidates = [directory, *directory.parents]
    markers = (".openpilot", ".git", "pyproject.toml", "package.json", "requirements.txt", "sketch.json")
    for candidate in candidates:
        if any((candidate / marker).exists() for marker in markers):
            return candidate
    return directory


def _relative_path(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except (OSError, ValueError):
        return path.name


def _read_text(path: Path) -> str:
    if path.suffix.lower() not in ProjectIndexManager.TEXT_SUFFIXES:
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def _language_for_path(path: Path) -> str:
    suffix = path.suffix.lower()
    return {
        ".css": "css",
        ".html": "html",
        ".js": "javascript",
        ".jsx": "javascript",
        ".json": "json",
        ".md": "markdown",
        ".py": "python",
        ".rs": "rust",
        ".sh": "shell",
        ".ts": "typescript",
        ".tsx": "typescript",
        ".yaml": "yaml",
        ".yml": "yaml",
    }.get(suffix, suffix.removeprefix(".") or "text")


def _python_sections(content: str) -> list[dict[str, Any]]:
    sections: list[dict[str, Any]] = []
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return _text_sections(content)

    module_doc = ast.get_docstring(tree) or ""
    imports = [node for node in tree.body if isinstance(node, (ast.Import, ast.ImportFrom))]
    if module_doc or imports:
        line_start = 1
        line_end = max((getattr(node, "end_lineno", getattr(node, "lineno", 1)) for node in imports), default=1)
        sections.append(
            {
                "title": "module overview",
                "section_type": "python_module",
                "summary": module_doc or "module imports and top-level setup",
                "line_start": line_start,
                "line_end": line_end,
            }
        )

    parents: dict[ast.AST, str] = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            if isinstance(parent, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                parents[child] = parent.name
    for node in ast.walk(tree):
        if not isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        end_lineno = getattr(node, "end_lineno", None)
        if not end_lineno:
            continue
        kind = "class" if isinstance(node, ast.ClassDef) else "function"
        source_segment = ast.get_source_segment(content, node) or ""
        summary = ast.get_docstring(node) or f"{kind} {node.name}: {_compact_text(source_segment)}"
        sections.append(
            {
                "title": f"{kind} {node.name}",
                "section_type": f"python_{kind}",
                "summary": summary,
                "line_start": int(node.lineno),
                "line_end": int(end_lineno),
                "symbol_name": node.name,
                "parent_symbol": parents.get(node, ""),
            }
        )
    sections.sort(key=lambda item: (int(item["line_start"]), int(item["line_end"])))
    return sections or _text_sections(content)


def _markdown_sections(content: str) -> list[dict[str, Any]]:
    lines = content.splitlines()
    headings = [
        (index + 1, line.strip())
        for index, line in enumerate(lines)
        if re.match(r"^#{1,6}\s+\S", line)
    ]
    if not headings:
        return _text_sections(content)
    sections = []
    for position, (line_number, heading) in enumerate(headings):
        next_start = headings[position + 1][0] if position + 1 < len(headings) else len(lines) + 1
        body = "\n".join(lines[line_number: max(line_number, next_start - 1)])
        sections.append(
            {
                "title": heading.lstrip("#").strip(),
                "section_type": "markdown_heading",
                "summary": _compact_text(body) or heading,
                "line_start": line_number,
                "line_end": max(line_number, next_start - 1),
            }
        )
    return sections


def _json_sections(content: str) -> list[dict[str, Any]]:
    try:
        payload = json.loads(content)
    except json.JSONDecodeError:
        return _text_sections(content)
    if not isinstance(payload, dict):
        return _text_sections(content)
    lines = content.splitlines()
    sections = []
    for key, value in payload.items():
        line_number = _find_json_key_line(lines, str(key))
        sections.append(
            {
                "title": str(key),
                "section_type": "json_key",
                "summary": f"{key}: {_compact_text(json.dumps(value, ensure_ascii=False))}",
                "line_start": line_number,
                "line_end": line_number,
                "symbol_name": str(key),
            }
        )
    return sections or _text_sections(content)


def _text_sections(content: str) -> list[dict[str, Any]]:
    lines = content.splitlines()
    sections = []
    start: int | None = None
    buffer: list[str] = []
    for index, line in enumerate(lines, start=1):
        if line.strip():
            start = start or index
            buffer.append(line)
            continue
        if start is not None:
            sections.append(_text_section(start, index - 1, buffer))
            start = None
            buffer = []
    if start is not None:
        sections.append(_text_section(start, len(lines), buffer))
    if not sections and lines:
        sections.append(_text_section(1, len(lines), lines))
    return sections[:64]


def _text_section(line_start: int, line_end: int, lines: list[str]) -> dict[str, Any]:
    summary = _compact_text(" ".join(line.strip() for line in lines if line.strip()))
    return {
        "title": summary[:80] or f"lines {line_start}-{line_end}",
        "section_type": "text_block",
        "summary": summary,
        "line_start": line_start,
        "line_end": line_end,
    }


def _find_json_key_line(lines: list[str], key: str) -> int:
    pattern = re.compile(rf'^\s*"{re.escape(key)}"\s*:')
    for index, line in enumerate(lines, start=1):
        if pattern.search(line):
            return index
    return 1


def _line_char_span(content: str, line_start: int, line_end: int) -> tuple[int, int]:
    offsets = [0]
    position = 0
    for line in content.splitlines(keepends=True):
        position += len(line)
        offsets.append(position)
    if not offsets:
        return 0, 0
    start_index = max(0, min(line_start - 1, len(offsets) - 1))
    end_index = max(start_index, min(line_end, len(offsets) - 1))
    return offsets[start_index], offsets[end_index]


def _stable_hash_embedding(text: str, dimension: int = 16) -> list[float]:
    vector = [0.0] * dimension
    for term in _terms(text):
        digest = hashlib.sha256(term.encode("utf-8")).digest()
        index = digest[0] % dimension
        sign = 1.0 if digest[1] % 2 == 0 else -1.0
        vector[index] += sign
    norm = math.sqrt(sum(item * item for item in vector)) or 1.0
    return [round(item / norm, 6) for item in vector]


def _terms(text: str) -> list[str]:
    return [term for term in re.split(r"\W+", text.lower()) if term]


def _compact_text(text: str, limit: int = 240) -> str:
    return " ".join(str(text or "").split())[:limit]


def _file_description(path: Path, index: FileContentIndexMetadata) -> str:
    if index.deleted:
        return f"deleted {path.name}"
    sections = ", ".join(section.title for section in index.sections[:6] if section.title)
    summaries = " ".join(section.summary for section in index.sections[:6] if section.summary)
    if sections and summaries:
        return f"{index.language or path.suffix or 'text'} file {path.name}; sections: {sections}; summary: {summaries}"
    if sections:
        return f"{index.language or path.suffix or 'text'} file {path.name}; sections: {sections}"
    return f"{index.language or path.suffix or 'text'} file {path.name}"
