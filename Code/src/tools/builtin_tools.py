"""Built-in tools for OpenPilot - Re-exports from individual tool modules."""

from __future__ import annotations

from tools.file_reader import FILE_READER_DEFINITION, file_reader_executor
from tools.multi_file_reader import MULTI_FILE_READER_DEFINITION, multi_file_reader_executor
from tools.file_writer import FILE_WRITER_DEFINITION, file_writer_executor
from tools.llm_summarizer import LLM_SUMMARIZER_DEFINITION, llm_summarizer_executor
from tools.code_generator import CODE_GENERATOR_DEFINITION, code_generator_executor
from tools.code_reviewer import CODE_REVIEWER_DEFINITION, code_reviewer_executor
from tools.code_executor import CODE_EXECUTOR_DEFINITION, code_executor_executor
from tools.readme_tool import README_TOOL_DEFINITION, readme_tool_executor
from tools.command_tool import COMMAND_EXECUTOR_DEFINITION, command_executor
from tools.embedder import EMBEDDER_DEFINITION, embedder_executor


__all__ = [
    # File Reader
    "FILE_READER_DEFINITION",
    "file_reader_executor",
    # Multi File Reader
    "MULTI_FILE_READER_DEFINITION",
    "multi_file_reader_executor",
    # File Writer
    "FILE_WRITER_DEFINITION",
    "file_writer_executor",
    # LLM Summarizer
    "LLM_SUMMARIZER_DEFINITION",
    "llm_summarizer_executor",
    # Code Generator
    "CODE_GENERATOR_DEFINITION",
    "code_generator_executor",
    # Code Reviewer
    "CODE_REVIEWER_DEFINITION",
    "code_reviewer_executor",
    # Code Executor
    "CODE_EXECUTOR_DEFINITION",
    "code_executor_executor",
    # README Tool
    "README_TOOL_DEFINITION",
    "readme_tool_executor",
    "COMMAND_EXECUTOR_DEFINITION",
    "command_executor",
    "EMBEDDER_DEFINITION",
    "embedder_executor",
    # Registration
    "register_builtin_tools",
]


def register_builtin_tools(registry) -> None:
    """
    Register all built-in tools to a registry.

    Args:
        registry: ToolRegistry instance
    """
    registry.register(FILE_READER_DEFINITION, file_reader_executor)
    registry.register(MULTI_FILE_READER_DEFINITION, multi_file_reader_executor)
    registry.register(FILE_WRITER_DEFINITION, file_writer_executor)
    registry.register(LLM_SUMMARIZER_DEFINITION, llm_summarizer_executor)
    registry.register(CODE_GENERATOR_DEFINITION, code_generator_executor)
    registry.register(CODE_REVIEWER_DEFINITION, code_reviewer_executor)
    registry.register(CODE_EXECUTOR_DEFINITION, code_executor_executor)
    registry.register(README_TOOL_DEFINITION, readme_tool_executor)
    registry.register(COMMAND_EXECUTOR_DEFINITION, command_executor)
    registry.register(EMBEDDER_DEFINITION, embedder_executor)
