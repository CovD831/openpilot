"""Code Editor Tool - Generate localized symbol replacements for existing code."""

from __future__ import annotations

import ast
import re
import textwrap
import uuid
from pathlib import Path

from metadata import ToolContractMetadata, ToolInputMetadata, ToolResultMetadata, metadata_tool_result

from core.tool_contracts import PermissionLevel, ToolCapability, ToolDefinition, ToolFailureMode


CODE_EDITOR_DEFINITION = ToolDefinition(
    name="code_editor",
    display_name="Code Editor",
    description="Modify an existing code symbol or explicit line range without producing a full-file replacement",
    version="1.0.0",
    capabilities=[ToolCapability.CODE_EXECUTION, ToolCapability.LLM_CALL, ToolCapability.FILE_READ],
    permission_level=PermissionLevel.MEDIUM,
    contract_metadata=ToolContractMetadata(
        tool_name="code_editor",
        input_metadata_type="ToolInputMetadata",
        output_metadata_type="ToolResultMetadata",
        required_input_fields=["task_description", "language"],
        required_any_of=[["file_path"], ["code"]],
        input_defaults={"operation_kind": "modify_symbol", "target_scope": "symbol"},
    ),
    timeout_seconds=300,
    max_retries=2,
    failure_modes=[
        ToolFailureMode(
            error_type="symbol_not_found",
            description="Could not locate a requested symbol in the target Python source",
            recovery_strategy="Read the file and retry with an exact symbol_name or line range",
        )
    ],
    tags=["code", "edit", "symbol", "patch"],
    audit_required=True,
)


@metadata_tool_result("code_editor")
def code_editor_executor(input_metadata: ToolInputMetadata) -> ToolResultMetadata:
    params = input_metadata.to_params()
    language = str(params.get("language") or "python").lower()
    source = _source_from_params(params)
    line_start, line_end, current_snippet = _resolve_scope(source, params, language)

    replacement = str(params.get("replacement_text") or "").strip()
    if not replacement:
        llm_client = params.get("_llm_client")
        if llm_client is None:
            from core.config import LLMSettings
            from core.llm import LLMClient

            llm_client = LLMClient(LLMSettings())
        replacement = _extract_code(_call_llm(llm_client, _build_prompt(params, current_snippet, language)), language).rstrip()

    if not replacement:
        raise ValueError("code_editor produced empty replacement_text")
    if language == "python":
        _validate_python_replacement(replacement, current_snippet)

    return {
        "code": replacement,
        "replacement_text": replacement,
        "language": language,
        "operation_kind": "modify_symbol",
        "target_scope": params.get("target_scope") or "symbol",
        "symbol_name": params.get("symbol_name"),
        "symbol_type": params.get("symbol_type"),
        "line_start": line_start,
        "line_end": line_end,
        "patch": {
            "operation_kind": "modify_symbol",
            "replacement_text": replacement,
            "symbol_name": params.get("symbol_name"),
            "symbol_type": params.get("symbol_type"),
            "line_start": line_start,
            "line_end": line_end,
        },
        "code_id": f"code_edit_{uuid.uuid4().hex[:8]}",
    }


def _source_from_params(params: dict[str, object]) -> str:
    if isinstance(params.get("code"), str) and params.get("code"):
        return str(params["code"])
    if isinstance(params.get("content"), str) and params.get("content"):
        return str(params["content"])
    file_path = params.get("file_path")
    if not file_path:
        raise ValueError("code_editor requires file_path or code")
    path = Path(str(file_path)).expanduser()
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(f"Code edit target file not found: {path}")
    return path.read_text(encoding=str(params.get("encoding") or "utf-8"))


def _resolve_scope(source: str, params: dict[str, object], language: str) -> tuple[int, int, str]:
    lines = source.splitlines()
    line_start = params.get("line_start")
    line_end = params.get("line_end")
    if isinstance(line_start, int) and isinstance(line_end, int):
        if line_start < 1 or line_end < line_start or line_end > len(lines):
            raise ValueError(f"Invalid code edit range: {line_start}-{line_end}")
        return line_start, line_end, "\n".join(lines[line_start - 1 : line_end])
    if language != "python":
        raise ValueError("code_editor needs line_start/line_end for non-Python code")
    symbol_name = str(params.get("symbol_name") or "")
    if not symbol_name:
        raise ValueError("code_editor requires symbol_name or line_start/line_end")
    start, end = _find_python_symbol_range(source, symbol_name)
    return start, end, "\n".join(lines[start - 1 : end])


def _find_python_symbol_range(source: str, symbol_name: str) -> tuple[int, int]:
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        raise ValueError(f"Cannot locate symbol in invalid Python source: {exc}") from exc
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name == symbol_name:
            end_lineno = getattr(node, "end_lineno", None)
            if not end_lineno:
                raise ValueError(f"Python runtime did not provide end_lineno for symbol: {symbol_name}")
            return int(node.lineno), int(end_lineno)
    raise ValueError(f"Python symbol not found: {symbol_name}")


def _build_prompt(params: dict[str, object], current_snippet: str, language: str) -> str:
    return f"""You are OpenPilot's Code Editor.
Modify only the shown {language} code scope. Return a replacement for that scope only, not the full file.

TASK:
{params.get("task_description") or ""}

SYMBOL:
{params.get("symbol_type") or ""} {params.get("symbol_name") or ""}

CURRENT SCOPE:
```{language}
{current_snippet}
```

SURROUNDING CONTEXT:
{params.get("context") or ""}

Return only the replacement code in a fenced code block.
"""


def _call_llm(llm_client: object, prompt: str) -> str:
    if hasattr(llm_client, "complete"):
        from core.llm import LLMMessage, LLMRequest

        response = llm_client.complete(
            LLMRequest(messages=[LLMMessage(role="user", content=prompt)], response_format="text", temperature=0.2)
        )
        return str(response.content)
    if hasattr(llm_client, "generate"):
        return str(llm_client.generate(prompt))
    if hasattr(llm_client, "chat"):
        return str(llm_client.chat([{"role": "user", "content": prompt}]))
    return str(llm_client(prompt))


def _extract_code(raw_response: str, language: str) -> str:
    pattern = rf"```(?:{re.escape(language)}|python|bash|shell)?\s*\n(.*?)```"
    match = re.search(pattern, raw_response, re.DOTALL | re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return raw_response.strip()


def _validate_python_replacement(replacement: str, current_snippet: str) -> None:
    try:
        ast.parse(replacement)
        return
    except SyntaxError:
        pass
    indented = textwrap.indent(replacement, "    ")
    wrapper = "class _OpenPilotPatchScope:\n" + indented + "\n"
    try:
        ast.parse(wrapper)
    except SyntaxError as exc:
        raise ValueError(f"Replacement Python scope has syntax error on line {exc.lineno}: {exc.msg}") from exc
