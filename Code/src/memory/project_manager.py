"""Project sketch management for memory-guided file discovery."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any


class ProjectManager:
    """Maintain per-directory sketch.json files and search them."""

    SKETCH_NAME = "sketch.json"
    IGNORED_DIRS = {
        ".git",
        ".mypy_cache",
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

    def __init__(
        self,
        root_path: str | Path = ".",
        *,
        embedding_service: Any | None = None,
        max_preview_chars: int = 600,
    ) -> None:
        self.root_path = Path(root_path).expanduser()
        self.embedding_service = embedding_service
        self.max_preview_chars = max_preview_chars

    def update(self, path: str | Path | None = None) -> dict[str, Any]:
        """Update sketch files for a file's directory or a directory tree."""
        target = Path(path).expanduser() if path is not None else self.root_path
        if target.is_file():
            directories = [target.parent]
        elif target.exists():
            directories = [directory for directory in self._walk_directories(target)]
        else:
            raise FileNotFoundError(f"Project path not found: {target}")

        updated = []
        file_count = 0
        for directory in directories:
            sketch = self._build_directory_sketch(directory)
            file_count += len(sketch["files"])
            sketch_path = directory / self.SKETCH_NAME
            sketch_path.write_text(json.dumps(sketch, ensure_ascii=False, indent=2), encoding="utf-8")
            updated.append(str(sketch_path))

        return {
            "root_path": str(target),
            "updated_sketches": updated,
            "file_count": file_count,
        }

    def search(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        """Search project sketches with a keyword fallback strategy."""
        query = query.strip()
        if not query:
            return []

        results = []
        for sketch_path in self.root_path.rglob(self.SKETCH_NAME):
            if self._is_ignored(sketch_path):
                continue
            sketch = self._load_sketch(sketch_path)
            for item in sketch.get("files", {}).values():
                score = self._score_item(query, item)
                if score <= 0:
                    continue
                results.append(
                    {
                        "path": item.get("path", ""),
                        "name": item.get("name", ""),
                        "suffix": item.get("suffix", ""),
                        "description": item.get("description", ""),
                        "mtime": item.get("mtime", 0.0),
                        "size": item.get("size", 0),
                        "score": score,
                        "sketch_path": str(sketch_path),
                    }
                )

        results.sort(key=lambda item: (item["score"], item["mtime"]), reverse=True)
        return results[:limit]

    def _walk_directories(self, root: Path):
        for directory, dirnames, _ in os.walk(root):
            dirnames[:] = [name for name in dirnames if name not in self.IGNORED_DIRS]
            yield Path(directory)

    def _build_directory_sketch(self, directory: Path) -> dict[str, Any]:
        files = {}
        for path in sorted(item for item in directory.iterdir() if item.is_file()):
            if path.name == self.SKETCH_NAME:
                continue
            stat = path.stat()
            description = self._describe_file(path)
            semantic_info = self._semantic_info(path, description)
            item = {
                "name": path.name,
                "path": str(path),
                "suffix": path.suffix,
                "description": description,
                "function_description": description,
                "semantic_info": semantic_info,
                "mtime": stat.st_mtime,
                "size": stat.st_size,
            }
            if self.embedding_service is not None:
                item["embedding"] = self.embedding_service.embed_text(description)
            files[path.name] = item

        return {
            "version": 1,
            "directory": str(directory),
            "files": files,
        }

    def _describe_file(self, path: Path) -> str:
        parts = [f"{path.suffix or 'plain'} file named {path.name}"]
        preview = self._read_preview(path)
        if preview:
            parts.append(f"Preview: {preview}")
        return ". ".join(parts)

    def _read_preview(self, path: Path) -> str:
        if path.suffix.lower() not in self.TEXT_SUFFIXES:
            return ""
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        return " ".join(lines)[: self.max_preview_chars]

    def _semantic_info(self, path: Path, description: str) -> Any:
        if self.embedding_service is not None:
            return self.embedding_service.embed_text(description)
        terms = self._terms(f"{path.name} {path.suffix} {description}")
        seen = []
        for term in terms:
            if term not in seen:
                seen.append(term)
        return {
            "kind": "keyword_fallback",
            "terms": seen[:24],
        }

    def _load_sketch(self, sketch_path: Path) -> dict[str, Any]:
        try:
            return json.loads(sketch_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {"files": {}}

    def _score_item(self, query: str, item: dict[str, Any]) -> float:
        haystack = " ".join(
            str(item.get(key, ""))
            for key in ("name", "path", "suffix", "description")
        ).lower()
        query_terms = self._terms(query)
        if not query_terms:
            return 0.0
        matches = sum(1 for term in query_terms if term in haystack)
        if matches == 0:
            return 0.0
        name_bonus = 0.5 if any(term in str(item.get("name", "")).lower() for term in query_terms) else 0.0
        return matches / len(query_terms) + name_bonus

    def _terms(self, text: str) -> list[str]:
        return [term for term in re.split(r"\W+", text.lower()) if term]

    def _is_ignored(self, path: Path) -> bool:
        return any(part in self.IGNORED_DIRS for part in path.parts)
