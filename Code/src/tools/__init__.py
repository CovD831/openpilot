"""Tools module."""

from tools.tool_registry import ToolRegistry
from tools.tool_orchestrator import ToolOrchestrator
from tools.tool_executor import ToolExecutor
from tools.file_tools import AdaptiveFileReader, FileReadResult, FileType
from tools.env_tools import EnvironmentManager, EnvInfo, EnvOperationResult
from tools.command_tool import CommandTool, RiskAssessment, CommandResult, RiskLevel

# Built-in tool definitions and executors
from tools.file_reader import FILE_READER_DEFINITION, file_reader_executor
from tools.directory_lister import DIRECTORY_LISTER_DEFINITION, directory_lister_executor
from tools.multi_file_reader import MULTI_FILE_READER_DEFINITION, multi_file_reader_executor
from tools.file_writer import FILE_WRITER_DEFINITION, file_writer_executor
from tools.llm_summarizer import LLM_SUMMARIZER_DEFINITION, llm_summarizer_executor
from tools.code_generator import CODE_GENERATOR_DEFINITION, code_generator_executor
from tools.code_reviewer import CODE_REVIEWER_DEFINITION, code_reviewer_executor
from tools.code_executor import CODE_EXECUTOR_DEFINITION, code_executor_executor
from tools.readme_tool import README_TOOL_DEFINITION, readme_tool_executor
from tools.builtin_tools import register_builtin_tools

__all__ = [
    'ToolRegistry',
    'ToolOrchestrator',
    'ToolExecutor',
    'AdaptiveFileReader',
    'FileReadResult',
    'FileType',
    'EnvironmentManager',
    'EnvInfo',
    'EnvOperationResult',
    'CommandTool',
    'RiskAssessment',
    'CommandResult',
    'RiskLevel',
    # Built-in tools
    'FILE_READER_DEFINITION',
    'file_reader_executor',
    'DIRECTORY_LISTER_DEFINITION',
    'directory_lister_executor',
    'MULTI_FILE_READER_DEFINITION',
    'multi_file_reader_executor',
    'FILE_WRITER_DEFINITION',
    'file_writer_executor',
    'LLM_SUMMARIZER_DEFINITION',
    'llm_summarizer_executor',
    'CODE_GENERATOR_DEFINITION',
    'code_generator_executor',
    'CODE_REVIEWER_DEFINITION',
    'code_reviewer_executor',
    'CODE_EXECUTOR_DEFINITION',
    'code_executor_executor',
    'README_TOOL_DEFINITION',
    'readme_tool_executor',
    'register_builtin_tools',
]
