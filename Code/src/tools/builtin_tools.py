"""Built-in tools for OpenPilot - Re-exports from individual tool modules."""

from __future__ import annotations

from tools.file_reader import FILE_READER_DEFINITION, file_reader_executor
from tools.directory_lister import DIRECTORY_LISTER_DEFINITION, directory_lister_executor
from tools.multi_file_reader import MULTI_FILE_READER_DEFINITION, multi_file_reader_executor
from tools.file_writer import FILE_WRITER_DEFINITION, file_writer_executor
from tools.llm_summarizer import LLM_SUMMARIZER_DEFINITION, llm_summarizer_executor
from tools.code_generator import CODE_GENERATOR_DEFINITION, code_generator_executor
from tools.code_reviewer import CODE_REVIEWER_DEFINITION, code_reviewer_executor
from tools.code_executor import CODE_EXECUTOR_DEFINITION, code_executor_executor
from tools.readme_tool import README_TOOL_DEFINITION, readme_tool_executor
from tools.project_improvement_tool import (
    PROJECT_IMPROVEMENT_TOOL_DEFINITION,
    PROJECT_STATE_READER_DEFINITION,
    project_improvement_tool_executor,
    project_state_reader_executor,
)
from tools.autonomy_tool import AUTONOMY_TOOL_DEFINITION, autonomy_tool_executor
from tools.env_tools import PROJECT_ENVIRONMENT_TOOL_DEFINITION, project_environment_tool_executor
from tools.command_tool import COMMAND_EXECUTOR_DEFINITION, command_executor
from tools.embedder import EMBEDDER_DEFINITION, embedder_executor
from tools.memory_context_tool import MEMORY_CONTEXT_TOOL_DEFINITION, memory_context_executor


__all__ = [
    # File Reader
    "FILE_READER_DEFINITION",
    "file_reader_executor",
    # Directory Lister
    "DIRECTORY_LISTER_DEFINITION",
    "directory_lister_executor",
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
    # Project Improvement Tool
    "PROJECT_IMPROVEMENT_TOOL_DEFINITION",
    "project_improvement_tool_executor",
    "PROJECT_STATE_READER_DEFINITION",
    "project_state_reader_executor",
    # Autonomy Tool
    "AUTONOMY_TOOL_DEFINITION",
    "autonomy_tool_executor",
    "PROJECT_ENVIRONMENT_TOOL_DEFINITION",
    "project_environment_tool_executor",
    "COMMAND_EXECUTOR_DEFINITION",
    "command_executor",
    "EMBEDDER_DEFINITION",
    "embedder_executor",
    "MEMORY_CONTEXT_TOOL_DEFINITION",
    "memory_context_executor",
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
    registry.register(DIRECTORY_LISTER_DEFINITION, directory_lister_executor)
    registry.register(MULTI_FILE_READER_DEFINITION, multi_file_reader_executor)
    registry.register(FILE_WRITER_DEFINITION, file_writer_executor)
    registry.register(LLM_SUMMARIZER_DEFINITION, llm_summarizer_executor)
    registry.register(CODE_GENERATOR_DEFINITION, code_generator_executor)
    registry.register(CODE_REVIEWER_DEFINITION, code_reviewer_executor)
    registry.register(CODE_EXECUTOR_DEFINITION, code_executor_executor)
    registry.register(README_TOOL_DEFINITION, readme_tool_executor)
    registry.register(PROJECT_IMPROVEMENT_TOOL_DEFINITION, project_improvement_tool_executor)
    registry.register(PROJECT_STATE_READER_DEFINITION, project_state_reader_executor)
    registry.register(AUTONOMY_TOOL_DEFINITION, autonomy_tool_executor)
    registry.register(PROJECT_ENVIRONMENT_TOOL_DEFINITION, project_environment_tool_executor)
    registry.register(COMMAND_EXECUTOR_DEFINITION, command_executor)
    registry.register(EMBEDDER_DEFINITION, embedder_executor)
    registry.register(MEMORY_CONTEXT_TOOL_DEFINITION, memory_context_executor)
