"""Built-in tools for OpenPilot Phase 2."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from core.llm import LLMClient, LLMMessage, LLMRequest
from models.tool_models import (
    PermissionLevel,
    ToolCapability,
    ToolDefinition,
    ToolExecutionResult,
    ToolFailureMode,
    ToolInputSchema,
    ToolOutputSchema,
)


# ============================================================================
# File Reader Tool
# ============================================================================

FILE_READER_DEFINITION = ToolDefinition(
    name="file_reader",
    display_name="File Reader",
    description="Read contents from a local file",
    version="1.0.0",
    capabilities=[ToolCapability.FILE_READ],
    permission_level=PermissionLevel.LOW,
    input_schema=[
        ToolInputSchema(
            name="file_path",
            type="string",
            description="Absolute or relative path to the file",
            required=True
        ),
        ToolInputSchema(
            name="encoding",
            type="string",
            description="File encoding (default: utf-8)",
            required=False,
            default="utf-8"
        ),
        ToolInputSchema(
            name="max_size_mb",
            type="integer",
            description="Maximum file size in MB (default: 10)",
            required=False,
            default=10
        )
    ],
    output_schema=ToolOutputSchema(
        type="object",
        description="File contents and metadata",
        properties={
            "content": {"type": "string", "description": "File contents"},
            "size_bytes": {"type": "integer", "description": "File size in bytes"},
            "encoding": {"type": "string", "description": "File encoding used"}
        }
    ),
    timeout_seconds=30,
    max_retries=2,
    failure_modes=[
        ToolFailureMode(
            error_type="file_not_found",
            description="File does not exist",
            recovery_strategy="Check file path and try again"
        ),
        ToolFailureMode(
            error_type="permission_denied",
            description="No permission to read file",
            recovery_strategy="Check file permissions"
        ),
        ToolFailureMode(
            error_type="file_too_large",
            description="File exceeds maximum size",
            recovery_strategy="Increase max_size_mb or read file in chunks"
        ),
        ToolFailureMode(
            error_type="encoding_error",
            description="Cannot decode file with specified encoding",
            recovery_strategy="Try different encoding (e.g., latin-1, gbk)"
        )
    ],
    tags=["file", "read", "local", "io"],
    audit_required=True
)


def file_reader_executor(params: dict[str, Any]) -> dict[str, Any]:
    """
    Execute file reader tool.

    Args:
        params: Tool parameters (file_path, encoding, max_size_mb)

    Returns:
        Dictionary with content, size_bytes, encoding

    Raises:
        FileNotFoundError: If file doesn't exist
        PermissionError: If no read permission
        ValueError: If file too large or encoding error
    """
    file_path = Path(params["file_path"])
    encoding = params.get("encoding", "utf-8")
    max_size_mb = params.get("max_size_mb", 10)

    # Check file exists
    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    # Check file size
    size_bytes = file_path.stat().st_size
    max_size_bytes = max_size_mb * 1024 * 1024
    if size_bytes > max_size_bytes:
        raise ValueError(
            f"File too large: {size_bytes} bytes "
            f"(max: {max_size_bytes} bytes)"
        )

    # Read file
    try:
        content = file_path.read_text(encoding=encoding)
    except PermissionError as e:
        raise PermissionError(f"No permission to read file: {file_path}") from e
    except UnicodeDecodeError as e:
        raise ValueError(
            f"Cannot decode file with encoding '{encoding}': {e}"
        ) from e

    return {
        "content": content,
        "size_bytes": size_bytes,
        "encoding": encoding
    }


# ============================================================================
# Directory Lister Tool
# ============================================================================

DIRECTORY_LISTER_DEFINITION = ToolDefinition(
    name="directory_lister",
    display_name="Directory Lister",
    description="List local files in a directory using a glob pattern",
    version="1.0.0",
    capabilities=[ToolCapability.FILE_READ],
    permission_level=PermissionLevel.LOW,
    input_schema=[
        ToolInputSchema(
            name="directory_path",
            type="string",
            description="Absolute or relative directory path",
            required=True
        ),
        ToolInputSchema(
            name="pattern",
            type="string",
            description="Glob pattern for files",
            required=False,
            default="*完成报告*.md"
        ),
        ToolInputSchema(
            name="recursive",
            type="boolean",
            description="Search recursively",
            required=False,
            default=False
        ),
        ToolInputSchema(
            name="max_files",
            type="integer",
            description="Maximum number of files to return",
            required=False,
            default=100
        ),
    ],
    output_schema=ToolOutputSchema(
        type="object",
        description="Matched file paths and metadata",
        properties={
            "directory_path": {"type": "string", "description": "Directory searched"},
            "pattern": {"type": "string", "description": "Glob pattern used"},
            "files": {"type": "array", "description": "Matched file paths"},
            "count": {"type": "integer", "description": "Number of matched files"},
            "truncated": {"type": "boolean", "description": "Whether results were truncated"},
        },
    ),
    timeout_seconds=30,
    max_retries=2,
    failure_modes=[
        ToolFailureMode(
            error_type="directory_not_found",
            description="Directory does not exist",
            recovery_strategy="Check directory path and try again"
        ),
        ToolFailureMode(
            error_type="not_a_directory",
            description="Path exists but is not a directory",
            recovery_strategy="Provide a directory path"
        ),
    ],
    tags=["directory", "list", "file", "local", "io"],
    audit_required=True,
)


def directory_lister_executor(params: dict[str, Any]) -> dict[str, Any]:
    """List files in a directory."""
    directory_path = Path(params["directory_path"])
    pattern = params.get("pattern", "*完成报告*.md")
    recursive = params.get("recursive", False)
    max_files = params.get("max_files", 100)

    if not directory_path.exists():
        raise FileNotFoundError(f"Directory not found: {directory_path}")
    if not directory_path.is_dir():
        raise NotADirectoryError(f"Not a directory: {directory_path}")

    iterator = directory_path.rglob(pattern) if recursive else directory_path.glob(pattern)
    matched = sorted(str(path) for path in iterator if path.is_file())
    truncated = len(matched) > max_files

    return {
        "directory_path": str(directory_path),
        "pattern": pattern,
        "files": matched[:max_files],
        "count": min(len(matched), max_files),
        "total_count": len(matched),
        "truncated": truncated,
    }


# ============================================================================
# Multi File Reader Tool
# ============================================================================

MULTI_FILE_READER_DEFINITION = ToolDefinition(
    name="multi_file_reader",
    display_name="Multi File Reader",
    description="Read and combine contents from multiple local files",
    version="1.0.0",
    capabilities=[ToolCapability.FILE_READ],
    permission_level=PermissionLevel.LOW,
    input_schema=[
        ToolInputSchema(
            name="file_paths",
            type="array",
            description="List of file paths to read",
            required=False
        ),
        ToolInputSchema(
            name="directory_path",
            type="string",
            description="Directory to scan if file_paths is omitted",
            required=False
        ),
        ToolInputSchema(
            name="pattern",
            type="string",
            description="Glob pattern used with directory_path",
            required=False,
            default="*完成报告*.md"
        ),
        ToolInputSchema(
            name="encoding",
            type="string",
            description="File encoding",
            required=False,
            default="utf-8"
        ),
        ToolInputSchema(
            name="max_total_chars",
            type="integer",
            description="Maximum combined content length",
            required=False,
            default=50000
        ),
    ],
    output_schema=ToolOutputSchema(
        type="object",
        description="Combined file contents and metadata",
        properties={
            "content": {"type": "string", "description": "Combined file contents"},
            "files": {"type": "array", "description": "Read file paths"},
            "count": {"type": "integer", "description": "Number of files read"},
            "truncated": {"type": "boolean", "description": "Whether content was truncated"},
        },
    ),
    timeout_seconds=60,
    max_retries=2,
    failure_modes=[
        ToolFailureMode(
            error_type="file_not_found",
            description="One or more files do not exist",
            recovery_strategy="Check file paths and retry"
        ),
        ToolFailureMode(
            error_type="encoding_error",
            description="Cannot decode a file with specified encoding",
            recovery_strategy="Try a different encoding"
        ),
    ],
    tags=["file", "read", "batch", "local", "io"],
    audit_required=True,
)


def multi_file_reader_executor(params: dict[str, Any]) -> dict[str, Any]:
    """Read multiple files and combine them into one text payload."""
    file_paths = params.get("file_paths") or params.get("files")
    if not file_paths:
        directory_path = params.get("directory_path")
        if not directory_path:
            raise ValueError("multi_file_reader requires file_paths or directory_path")
        pattern = params.get("pattern", "*完成报告*.md")
        directory_result = directory_lister_executor(
            {
                "directory_path": directory_path,
                "pattern": pattern,
                "recursive": params.get("recursive", False),
                "max_files": params.get("max_files", 100),
            }
        )
        file_paths = directory_result["files"]

    encoding = params.get("encoding", "utf-8")
    max_total_chars = params.get("max_total_chars", 50000)
    combined_parts: list[str] = []
    read_files: list[str] = []
    total_chars = 0
    truncated = False

    for file_path_value in file_paths:
        file_path = Path(file_path_value)
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")
        if not file_path.is_file():
            continue

        content = file_path.read_text(encoding=encoding)
        header = f"\n\n# Source: {file_path}\n\n"
        remaining = max_total_chars - total_chars
        if remaining <= 0:
            truncated = True
            break

        chunk = header + content
        if len(chunk) > remaining:
            chunk = chunk[:remaining]
            truncated = True

        combined_parts.append(chunk)
        read_files.append(str(file_path))
        total_chars += len(chunk)

        if truncated:
            break

    return {
        "content": "".join(combined_parts).strip(),
        "files": read_files,
        "count": len(read_files),
        "truncated": truncated,
        "encoding": encoding,
    }


# ============================================================================
# File Writer Tool
# ============================================================================

FILE_WRITER_DEFINITION = ToolDefinition(
    name="file_writer",
    display_name="File Writer",
    description="Write contents to a local file",
    version="1.0.0",
    capabilities=[ToolCapability.FILE_WRITE],
    permission_level=PermissionLevel.MEDIUM,
    input_schema=[
        ToolInputSchema(
            name="file_path",
            type="string",
            description="Absolute or relative path to the file",
            required=True
        ),
        ToolInputSchema(
            name="content",
            type="string",
            description="Content to write to file",
            required=True
        ),
        ToolInputSchema(
            name="encoding",
            type="string",
            description="File encoding (default: utf-8)",
            required=False,
            default="utf-8"
        ),
        ToolInputSchema(
            name="create_dirs",
            type="boolean",
            description="Create parent directories if they don't exist",
            required=False,
            default=True
        ),
        ToolInputSchema(
            name="overwrite",
            type="boolean",
            description="Overwrite file if it exists",
            required=False,
            default=True
        )
    ],
    output_schema=ToolOutputSchema(
        type="object",
        description="Write result and metadata",
        properties={
            "file_path": {"type": "string", "description": "Path to written file"},
            "bytes_written": {"type": "integer", "description": "Number of bytes written"},
            "created": {"type": "boolean", "description": "Whether file was newly created"}
        }
    ),
    timeout_seconds=30,
    max_retries=2,
    failure_modes=[
        ToolFailureMode(
            error_type="permission_denied",
            description="No permission to write file",
            recovery_strategy="Check file/directory permissions"
        ),
        ToolFailureMode(
            error_type="file_exists",
            description="File exists and overwrite=False",
            recovery_strategy="Set overwrite=True or choose different path"
        ),
        ToolFailureMode(
            error_type="disk_full",
            description="Not enough disk space",
            recovery_strategy="Free up disk space or write to different location"
        )
    ],
    tags=["file", "write", "local", "io"],
    audit_required=True
)


def file_writer_executor(params: dict[str, Any]) -> dict[str, Any]:
    """
    Execute file writer tool.

    Args:
        params: Tool parameters (file_path, content, encoding, create_dirs, overwrite)

    Returns:
        Dictionary with file_path, bytes_written, created

    Raises:
        PermissionError: If no write permission
        FileExistsError: If file exists and overwrite=False
        OSError: If disk full or other OS error
    """
    file_path = Path(params["file_path"])
    content = params["content"]
    encoding = params.get("encoding", "utf-8")
    create_dirs = params.get("create_dirs", True)
    overwrite = params.get("overwrite", True)

    # Check if file exists
    file_existed = file_path.exists()
    if file_existed and not overwrite:
        raise FileExistsError(
            f"File exists and overwrite=False: {file_path}"
        )

    # Create parent directories if needed
    if create_dirs and not file_path.parent.exists():
        try:
            file_path.parent.mkdir(parents=True, exist_ok=True)
        except PermissionError as e:
            raise PermissionError(
                f"No permission to create directory: {file_path.parent}"
            ) from e

    # Write file
    try:
        file_path.write_text(content, encoding=encoding)
        bytes_written = file_path.stat().st_size
    except PermissionError as e:
        raise PermissionError(
            f"No permission to write file: {file_path}"
        ) from e
    except OSError as e:
        # Could be disk full or other OS error
        raise OSError(f"Failed to write file: {e}") from e

    return {
        "file_path": str(file_path.absolute()),
        "bytes_written": bytes_written,
        "created": not file_existed
    }


# ============================================================================
# LLM Summarizer Tool
# ============================================================================

LLM_SUMMARIZER_DEFINITION = ToolDefinition(
    name="llm_summarizer",
    display_name="LLM Summarizer",
    description="Generate summary or analysis using LLM",
    version="1.0.0",
    capabilities=[ToolCapability.LLM_CALL],
    permission_level=PermissionLevel.LOW,
    input_schema=[
        ToolInputSchema(
            name="text",
            type="string",
            description="Text to summarize or analyze",
            required=True
        ),
        ToolInputSchema(
            name="instruction",
            type="string",
            description="Instruction for the LLM (e.g., 'Summarize in 3 sentences')",
            required=False,
            default="Summarize the following text concisely."
        ),
        ToolInputSchema(
            name="max_tokens",
            type="integer",
            description="Maximum tokens in response",
            required=False,
            default=500
        )
    ],
    output_schema=ToolOutputSchema(
        type="object",
        description="LLM response and metadata",
        properties={
            "summary": {"type": "string", "description": "Generated summary"},
            "tokens_used": {"type": "integer", "description": "Number of tokens used"},
            "model": {"type": "string", "description": "Model used"}
        }
    ),
    timeout_seconds=60,
    max_retries=3,
    failure_modes=[
        ToolFailureMode(
            error_type="llm_timeout",
            description="LLM request timed out",
            recovery_strategy="Retry with shorter text or higher timeout"
        ),
        ToolFailureMode(
            error_type="llm_error",
            description="LLM returned error",
            recovery_strategy="Check LLM configuration and API key"
        ),
        ToolFailureMode(
            error_type="text_too_long",
            description="Input text exceeds model context limit",
            recovery_strategy="Split text into chunks or use longer context model"
        )
    ],
    tags=["llm", "summarize", "analysis", "text"],
    audit_required=True
)


def llm_summarizer_executor(params: dict[str, Any]) -> dict[str, Any]:
    """
    Execute LLM summarizer tool.

    Args:
        params: Tool parameters (text, instruction, max_tokens)

    Returns:
        Dictionary with summary, tokens_used, model

    Raises:
        ValueError: If text too long or invalid parameters
        Exception: If LLM call fails
    """
    text = params["text"]
    instruction = params.get("instruction", "Summarize the following text concisely.")
    max_tokens = params.get("max_tokens", 500)

    # Build prompt
    prompt = f"{instruction}\n\n{text}"

    # Call LLM
    try:
        from core.config import LLMSettings
        settings = LLMSettings()
        client = LLMClient(settings)

        response = client.complete(
            LLMRequest(
                messages=[LLMMessage(role="user", content=prompt)],
                response_format="text",
                max_tokens=max_tokens,
                temperature=0.3,
            )
        )

        return {
            "summary": response.content,
            "tokens_used": response.usage.get("total_tokens", 0) if response.usage else 0,
            "model": settings.model
        }
    except Exception as e:
        raise Exception(f"LLM summarizer failed: {e}") from e


# ============================================================================
# Code Generator Tool
# ============================================================================

CODE_GENERATOR_DEFINITION = ToolDefinition(
    name="code_generator",
    display_name="Code Generator",
    description="Generate code using LLM based on task description",
    version="1.0.0",
    capabilities=[ToolCapability.CODE_EXECUTION, ToolCapability.LLM_CALL],
    permission_level=PermissionLevel.MEDIUM,
    input_schema=[
        ToolInputSchema(
            name="task_description",
            type="string",
            description="Description of the code to generate",
            required=True
        ),
        ToolInputSchema(
            name="language",
            type="string",
            description="Programming language (python, shell, bash)",
            required=True
        ),
        ToolInputSchema(
            name="context",
            type="string",
            description="Additional context or requirements",
            required=False,
            default=""
        )
    ],
    output_schema=ToolOutputSchema(
        type="object",
        description="Generated code and metadata",
        properties={
            "code": {"type": "string", "description": "Generated code"},
            "language": {"type": "string", "description": "Programming language"},
            "explanation": {"type": "string", "description": "Code explanation"},
            "imports": {"type": "array", "description": "List of imported modules"},
            "functions": {"type": "array", "description": "List of function names"}
        }
    ),
    timeout_seconds=120,
    max_retries=2,
    failure_modes=[
        ToolFailureMode(
            error_type="llm_timeout",
            description="LLM request timed out",
            recovery_strategy="Retry with simpler task description"
        ),
        ToolFailureMode(
            error_type="llm_error",
            description="LLM returned error",
            recovery_strategy="Check LLM configuration and API key"
        ),
        ToolFailureMode(
            error_type="invalid_language",
            description="Unsupported programming language",
            recovery_strategy="Use python, shell, or bash"
        )
    ],
    tags=["code", "generation", "llm", "programming"],
    audit_required=True
)


def code_generator_executor(params: dict[str, Any]) -> dict[str, Any]:
    """
    Execute code generator tool.

    Args:
        params: Tool parameters (task_description, language, context)

    Returns:
        Dictionary with code, language, explanation, imports, functions
    """
    from execution.code_generator import CodeGenerator
    from models.code_models import CodeGenerationRequest, CodeLanguage
    import uuid

    task_description = params["task_description"]
    language_str = params["language"].lower()
    context = params.get("context", "")

    # Map language string to CodeLanguage enum
    language_map = {
        "python": CodeLanguage.PYTHON,
        "shell": CodeLanguage.SHELL,
        "bash": CodeLanguage.BASH,
    }

    if language_str not in language_map:
        raise ValueError(f"Unsupported language: {language_str}. Use python, shell, or bash.")

    language = language_map[language_str]

    try:
        from core.config import LLMSettings
        settings = LLMSettings()
        generator = CodeGenerator(LLMClient(settings))

        # Create request
        request = CodeGenerationRequest(
            request_id=f"req_{uuid.uuid4().hex[:8]}",
            task_description=task_description,
            language=language,
            context=context
        )

        # Generate code
        result = generator.generate_code(request)

        return {
            "code": result.code,
            "language": result.language.value,
            "explanation": f"Generated {result.line_count} lines of {result.language.value} code",
            "imports": result.imports,
            "functions": result.functions
        }
    except Exception as e:
        raise Exception(f"Code generation failed: {e}") from e


# ============================================================================
# Code Reviewer Tool
# ============================================================================

CODE_REVIEWER_DEFINITION = ToolDefinition(
    name="code_reviewer",
    display_name="Code Reviewer",
    description="Review code quality and suggest improvements using LLM",
    version="1.0.0",
    capabilities=[ToolCapability.CODE_EXECUTION, ToolCapability.LLM_CALL],
    permission_level=PermissionLevel.LOW,
    input_schema=[
        ToolInputSchema(
            name="code",
            type="string",
            description="Code to review",
            required=True
        ),
        ToolInputSchema(
            name="language",
            type="string",
            description="Programming language (python, shell, bash)",
            required=True
        )
    ],
    output_schema=ToolOutputSchema(
        type="object",
        description="Code review results",
        properties={
            "review": {"type": "string", "description": "Overall review summary"},
            "issues": {"type": "array", "description": "List of issues found"},
            "suggestions": {"type": "array", "description": "Improvement suggestions"},
            "approved": {"type": "boolean", "description": "Whether code is approved"}
        }
    ),
    timeout_seconds=60,
    max_retries=2,
    failure_modes=[
        ToolFailureMode(
            error_type="llm_timeout",
            description="LLM request timed out",
            recovery_strategy="Retry with shorter code snippet"
        ),
        ToolFailureMode(
            error_type="llm_error",
            description="LLM returned error",
            recovery_strategy="Check LLM configuration and API key"
        )
    ],
    tags=["code", "review", "quality", "llm"],
    audit_required=True
)


def code_reviewer_executor(params: dict[str, Any]) -> dict[str, Any]:
    """
    Execute code reviewer tool.

    Args:
        params: Tool parameters (code, language)

    Returns:
        Dictionary with review, issues, suggestions, approved
    """
    from execution.code_reviewer import CodeReviewer
    from models.code_models import CodeLanguage, GeneratedCode
    import uuid

    code = params["code"]
    language_str = params["language"].lower()

    # Map language string to CodeLanguage enum
    language_map = {
        "python": CodeLanguage.PYTHON,
        "shell": CodeLanguage.SHELL,
        "bash": CodeLanguage.BASH,
    }

    if language_str not in language_map:
        raise ValueError(f"Unsupported language: {language_str}. Use python, shell, or bash.")

    language = language_map[language_str]

    try:
        from core.config import LLMSettings
        settings = LLMSettings()
        reviewer = CodeReviewer(LLMClient(settings))

        # Create GeneratedCode object
        generated_code = GeneratedCode(
            code_id=f"code_{uuid.uuid4().hex[:8]}",
            request_id=f"req_{uuid.uuid4().hex[:8]}",
            language=language,
            code=code,
            line_count=len([line for line in code.split("\n") if line.strip()]),
            imports=[],
            functions=[],
            model_used="unknown",
            generation_time_ms=0
        )

        # Review code
        result = reviewer.review_code(generated_code)

        return {
            "review": result.review,
            "issues": [issue.dict() if hasattr(issue, 'dict') else str(issue) for issue in result.dangerous_operations],
            "suggestions": result.suggestions,
            "approved": result.approved
        }
    except Exception as e:
        raise Exception(f"Code review failed: {e}") from e


# ============================================================================
# Code Executor Tool
# ============================================================================

CODE_EXECUTOR_DEFINITION = ToolDefinition(
    name="code_executor",
    display_name="Code Executor",
    description="Execute code in a sandboxed environment",
    version="1.0.0",
    capabilities=[ToolCapability.CODE_EXECUTION],
    permission_level=PermissionLevel.HIGH,
    input_schema=[
        ToolInputSchema(
            name="code",
            type="string",
            description="Code to execute",
            required=True
        ),
        ToolInputSchema(
            name="language",
            type="string",
            description="Programming language (python, shell, bash)",
            required=True
        ),
        ToolInputSchema(
            name="timeout",
            type="integer",
            description="Execution timeout in seconds (default: 30)",
            required=False,
            default=30
        )
    ],
    output_schema=ToolOutputSchema(
        type="object",
        description="Code execution results",
        properties={
            "success": {"type": "boolean", "description": "Whether execution succeeded"},
            "output": {"type": "string", "description": "Execution output (stdout)"},
            "error": {"type": "string", "description": "Error message (if failed)"},
            "exit_code": {"type": "integer", "description": "Process exit code"}
        }
    ),
    timeout_seconds=60,
    max_retries=1,
    failure_modes=[
        ToolFailureMode(
            error_type="execution_timeout",
            description="Code execution timed out",
            recovery_strategy="Increase timeout or optimize code"
        ),
        ToolFailureMode(
            error_type="execution_error",
            description="Code execution failed",
            recovery_strategy="Review code for errors and fix"
        ),
        ToolFailureMode(
            error_type="permission_denied",
            description="Insufficient permissions to execute code",
            recovery_strategy="Check execution permissions"
        )
    ],
    tags=["code", "execution", "sandbox", "runtime"],
    audit_required=True
)


def code_executor_executor(params: dict[str, Any]) -> dict[str, Any]:
    """
    Execute code executor tool.

    Args:
        params: Tool parameters (code, language, timeout)

    Returns:
        Dictionary with success, output, error, exit_code
    """
    from execution.code_executor import CodeExecutor
    from models.code_models import CodeLanguage, GeneratedCode
    import uuid

    code = params["code"]
    language_str = params["language"].lower()
    timeout = params.get("timeout", 30)

    # Map language string to CodeLanguage enum
    language_map = {
        "python": CodeLanguage.PYTHON,
        "shell": CodeLanguage.SHELL,
        "bash": CodeLanguage.BASH,
    }

    if language_str not in language_map:
        raise ValueError(f"Unsupported language: {language_str}. Use python, shell, or bash.")

    language = language_map[language_str]

    try:
        executor = CodeExecutor()

        # Create GeneratedCode object
        generated_code = GeneratedCode(
            code_id=f"code_{uuid.uuid4().hex[:8]}",
            request_id=f"req_{uuid.uuid4().hex[:8]}",
            language=language,
            code=code,
            line_count=len([line for line in code.split("\n") if line.strip()]),
            imports=[],
            functions=[],
            model_used="unknown",
            generation_time_ms=0
        )

        # Execute code
        result = executor.execute(
            generated_code=generated_code,
            timeout=timeout
        )

        return {
            "success": result.success,
            "output": result.stdout if result.success else result.stderr,
            "error": result.error_message or "",
            "exit_code": result.exit_code
        }
    except Exception as e:
        raise Exception(f"Code execution failed: {e}") from e


# ============================================================================
# Registration Helper
# ============================================================================

def register_builtin_tools(registry) -> None:
    """
    Register all built-in tools to a registry.

    Args:
        registry: ToolRegistry instance
    """
    registry.register(FILE_READER_DEFINITION, file_reader_executor)
    registry.register(DIRECTORY_LISTER_DEFINITION, directory_lister_executor)
    registry.register(MULTI_FILE_READER_DEFINITION, multi_file_reader_executor)
    registry.register(FILE_WRITER_DEFINITION, file_writer_executor)
    registry.register(LLM_SUMMARIZER_DEFINITION, llm_summarizer_executor)
    registry.register(CODE_GENERATOR_DEFINITION, code_generator_executor)
    registry.register(CODE_REVIEWER_DEFINITION, code_reviewer_executor)
    registry.register(CODE_EXECUTOR_DEFINITION, code_executor_executor)
