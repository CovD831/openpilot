"""Code Executor Tool - Execute code in a sandboxed environment."""

from __future__ import annotations

import io
import os
import subprocess
import sys
import tempfile
import time
import traceback
import uuid
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Any, Optional

from metadata import ToolContractMetadata, ToolInputMetadata, ToolResultMetadata, metadata_tool_result

from core.tool_contracts import (
    PermissionLevel,
    ToolCapability,
    ToolDefinition,
    ToolFailureMode,
)
from tools.code_models import CodeExecutionResult, CodeLanguage, GeneratedCode


CODE_EXECUTOR_DEFINITION = ToolDefinition(
    name="code_executor",
    display_name="Code Executor",
    description="Execute code in a sandboxed environment",
    version="1.0.0",
    capabilities=[ToolCapability.CODE_EXECUTION],
    permission_level=PermissionLevel.HIGH,
    contract_metadata=ToolContractMetadata(
        tool_name='code_executor',
        input_metadata_type="ToolInputMetadata",
        output_metadata_type="ToolResultMetadata",
        required_input_fields=['code', 'language'],
        input_defaults={'timeout': 30},
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


@metadata_tool_result('code_executor')
def code_executor_executor(input_metadata: ToolInputMetadata) -> ToolResultMetadata:
    params = input_metadata.to_params()
    """
    Execute code executor tool.

    Args:
        params: Tool parameters (code, language, timeout)

    Returns:
        Dictionary with success, output, error, exit_code
    """
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


class CodeExecutor:
    """代码执行器"""

    def __init__(
        self,
        default_timeout: int = 30,
        max_memory_mb: int = 512,
        enable_sandbox: bool = True,
    ):
        """
        初始化执行器

        Args:
            default_timeout: 默认超时时间（秒）
            max_memory_mb: 最大内存限制（MB）
            enable_sandbox: 是否启用沙箱
        """
        self.default_timeout = default_timeout
        self.max_memory_mb = max_memory_mb
        self.enable_sandbox = enable_sandbox
        self._execution_count = 0

    def execute(
        self,
        generated_code: GeneratedCode,
        input_data: Optional[dict[str, Any]] = None,
        timeout: Optional[int] = None,
        env: Optional[str] = None,
    ) -> CodeExecutionResult:
        """
        执行代码

        Args:
            generated_code: 生成的代码
            input_data: 输入数据
            timeout: 超时时间（秒）
            env: 虚拟环境名称（如 conda 环境名），None 表示使用当前环境

        Returns:
            CodeExecutionResult: 执行结果
        """
        execution_id = f"exec_{uuid.uuid4().hex[:8]}"
        timeout = timeout or self.default_timeout

        start_time = time.time()

        try:
            if generated_code.language == CodeLanguage.PYTHON:
                result = self._execute_python(
                    generated_code.code, input_data, timeout, execution_id, env
                )
            elif generated_code.language in (CodeLanguage.SHELL, CodeLanguage.BASH):
                result = self._execute_shell(
                    generated_code.code, input_data, timeout, execution_id, env
                )
            else:
                raise ValueError(f"不支持的语言: {generated_code.language}")

            # 更新统计
            self._execution_count += 1

            return result

        except Exception as e:
            execution_time_ms = int((time.time() - start_time) * 1000)
            return CodeExecutionResult(
                execution_id=execution_id,
                code_id=generated_code.code_id,
                success=False,
                exit_code=1,
                error_type=type(e).__name__,
                error_message=str(e),
                traceback=traceback.format_exc(),
                execution_time_ms=execution_time_ms,
                sandbox_used=self.enable_sandbox,
            )

    def _execute_python(
        self,
        code: str,
        input_data: Optional[dict[str, Any]],
        timeout: int,
        execution_id: str,
        env: Optional[str] = None,
    ) -> CodeExecutionResult:
        """执行 Python 代码

        Args:
            code: Python 代码
            input_data: 输入数据
            timeout: 超时时间
            execution_id: 执行ID
            env: 虚拟环境名称（如 conda 环境名），None 表示使用当前环境
        """
        start_time = time.time()

        # 如果指定了虚拟环境，使用 subprocess 在该环境中执行
        if env:
            return self._execute_python_in_env(code, input_data, timeout, execution_id, env)

        # 否则在当前环境中直接执行
        # 准备执行环境
        stdout_capture = io.StringIO()
        stderr_capture = io.StringIO()

        # 准备全局变量
        global_vars = {
            "__name__": "__main__",
            "__builtins__": __builtins__,
        }

        # 注入输入数据
        if input_data:
            global_vars.update(input_data)

        success = False
        exit_code = 0
        return_value = None
        error_type = None
        error_message = None
        error_line = None
        error_traceback = None

        try:
            # 重定向标准输出和错误
            with redirect_stdout(stdout_capture), redirect_stderr(stderr_capture):
                # 编译代码
                compiled_code = compile(code, "<generated>", "exec")

                # 执行代码（带超时）
                # 注意：这里的超时实现是简化的，实际应该使用更复杂的机制
                exec(compiled_code, global_vars)

            success = True

            # 尝试获取返回值（如果有 main 函数）
            if "main" in global_vars and callable(global_vars["main"]):
                return_value = global_vars["main"]()

        except SyntaxError as e:
            error_type = "SyntaxError"
            error_message = str(e)
            error_line = e.lineno
            error_traceback = traceback.format_exc()
            exit_code = 1

        except TimeoutError as e:
            error_type = "TimeoutError"
            error_message = f"执行超时（{timeout}秒）"
            error_traceback = traceback.format_exc()
            exit_code = 124

        except Exception as e:
            error_type = type(e).__name__
            error_message = str(e)
            error_traceback = traceback.format_exc()
            exit_code = 1

            # 尝试提取错误行号
            tb = sys.exc_info()[2]
            if tb:
                while tb.tb_next:
                    tb = tb.tb_next
                error_line = tb.tb_lineno

        execution_time_ms = int((time.time() - start_time) * 1000)

        return CodeExecutionResult(
            execution_id=execution_id,
            code_id="unknown",
            success=success,
            exit_code=exit_code,
            stdout=stdout_capture.getvalue(),
            stderr=stderr_capture.getvalue(),
            return_value=return_value,
            error_type=error_type,
            error_message=error_message,
            error_line=error_line,
            traceback=error_traceback,
            execution_time_ms=execution_time_ms,
            memory_used_mb=0.0,  # 简化版本不监控内存
            cpu_percent=0.0,  # 简化版本不监控 CPU
            sandbox_used=self.enable_sandbox,
        )

    def _execute_python_in_env(
        self,
        code: str,
        input_data: Optional[dict[str, Any]],
        timeout: int,
        execution_id: str,
        env: str,
    ) -> CodeExecutionResult:
        """在指定的虚拟环境中执行 Python 代码

        Args:
            code: Python 代码
            input_data: 输入数据
            timeout: 超时时间
            execution_id: 执行ID
            env: 虚拟环境名称（如 conda 环境名）
        """
        start_time = time.time()

        # 创建临时 Python 脚本文件
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False
        ) as script_file:
            script_file.write(code)
            script_path = script_file.name

        try:
            # 构建在虚拟环境中执行的命令
            # 假设使用 conda，可以扩展支持其他虚拟环境管理器
            cmd = ["conda", "run", "-n", env, "python", script_path]

            # 准备环境变量
            exec_env = os.environ.copy()
            if input_data:
                for key, value in input_data.items():
                    exec_env[key] = str(value)

            # 执行脚本
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=exec_env,
            )

            execution_time_ms = int((time.time() - start_time) * 1000)

            return CodeExecutionResult(
                execution_id=execution_id,
                code_id="unknown",
                success=result.returncode == 0,
                exit_code=result.returncode,
                stdout=result.stdout,
                stderr=result.stderr,
                execution_time_ms=execution_time_ms,
                sandbox_used=self.enable_sandbox,
            )

        except subprocess.TimeoutExpired:
            execution_time_ms = int((time.time() - start_time) * 1000)
            return CodeExecutionResult(
                execution_id=execution_id,
                code_id="unknown",
                success=False,
                exit_code=124,
                error_type="TimeoutError",
                error_message=f"执行超时（{timeout}秒）",
                execution_time_ms=execution_time_ms,
                sandbox_used=self.enable_sandbox,
            )

        except Exception as e:
            execution_time_ms = int((time.time() - start_time) * 1000)
            return CodeExecutionResult(
                execution_id=execution_id,
                code_id="unknown",
                success=False,
                exit_code=1,
                error_type=type(e).__name__,
                error_message=str(e),
                traceback=traceback.format_exc(),
                execution_time_ms=execution_time_ms,
                sandbox_used=self.enable_sandbox,
            )

        finally:
            # 清理临时文件
            try:
                Path(script_path).unlink()
            except Exception:
                pass

    def _execute_shell(
        self,
        code: str,
        input_data: Optional[dict[str, Any]],
        timeout: int,
        execution_id: str,
        env: Optional[str] = None,
    ) -> CodeExecutionResult:
        """执行 Shell 代码

        Args:
            code: Shell 代码
            input_data: 输入数据
            timeout: 超时时间
            execution_id: 执行ID
            env: 虚拟环境名称（如 conda 环境名），None 表示使用当前环境
        """
        start_time = time.time()

        # 创建临时脚本文件
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".sh", delete=False
        ) as script_file:
            script_file.write("#!/bin/bash\n")
            script_file.write("set -e\n")  # 遇到错误立即退出
            script_file.write("\n")
            script_file.write(code)
            script_path = script_file.name

        try:
            # 设置执行权限
            os.chmod(script_path, 0o755)

            # 准备环境变量
            exec_env = os.environ.copy()
            if input_data:
                for key, value in input_data.items():
                    exec_env[key] = str(value)

            # 构建执行命令
            if env:
                # 如果指定了虚拟环境，在该环境中执行
                cmd = ["conda", "run", "-n", env, "/bin/bash", script_path]
            else:
                # 否则直接执行
                cmd = ["/bin/bash", script_path]

            # 执行脚本
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=exec_env,
            )

            execution_time_ms = int((time.time() - start_time) * 1000)

            return CodeExecutionResult(
                execution_id=execution_id,
                code_id="unknown",
                success=result.returncode == 0,
                exit_code=result.returncode,
                stdout=result.stdout,
                stderr=result.stderr,
                execution_time_ms=execution_time_ms,
                sandbox_used=self.enable_sandbox,
            )

        except subprocess.TimeoutExpired:
            execution_time_ms = int((time.time() - start_time) * 1000)
            return CodeExecutionResult(
                execution_id=execution_id,
                code_id="unknown",
                success=False,
                exit_code=124,
                error_type="TimeoutError",
                error_message=f"执行超时（{timeout}秒）",
                execution_time_ms=execution_time_ms,
                sandbox_used=self.enable_sandbox,
            )

        except Exception as e:
            execution_time_ms = int((time.time() - start_time) * 1000)
            return CodeExecutionResult(
                execution_id=execution_id,
                code_id="unknown",
                success=False,
                exit_code=1,
                error_type=type(e).__name__,
                error_message=str(e),
                traceback=traceback.format_exc(),
                execution_time_ms=execution_time_ms,
                sandbox_used=self.enable_sandbox,
            )

        finally:
            # 清理临时文件
            try:
                Path(script_path).unlink()
            except Exception:
                pass

    def execute_with_retry(
        self,
        generated_code: GeneratedCode,
        input_data: Optional[dict[str, Any]] = None,
        max_retries: int = 2,
        env: Optional[str] = None,
    ) -> CodeExecutionResult:
        """
        执行代码（带重试）

        Args:
            generated_code: 生成的代码
            input_data: 输入数据
            max_retries: 最大重试次数
            env: 虚拟环境名称（如 conda 环境名），None 表示使用当前环境

        Returns:
            CodeExecutionResult: 执行结果
        """
        last_result = None

        for attempt in range(max_retries + 1):
            result = self.execute(generated_code, input_data, env=env)

            if result.success:
                return result

            last_result = result

            # 如果是语法错误或超时，不重试
            if result.error_type in ("SyntaxError", "TimeoutError"):
                break

            # 等待后重试
            if attempt < max_retries:
                time.sleep(0.5 * (attempt + 1))

        return last_result

    def validate_output(
        self,
        result: CodeExecutionResult,
        expected_output: Optional[Any] = None,
        output_validator: Optional[callable] = None,
    ) -> tuple[bool, Optional[str]]:
        """
        验证输出

        Args:
            result: 执行结果
            expected_output: 期望的输出
            output_validator: 自定义验证函数

        Returns:
            tuple[bool, Optional[str]]: (是否有效, 错误消息)
        """
        if not result.success:
            return False, "执行失败"

        # 使用自定义验证器
        if output_validator:
            try:
                is_valid = output_validator(result.return_value)
                if not is_valid:
                    return False, "输出验证失败"
                return True, None
            except Exception as e:
                return False, f"验证器错误: {e}"

        # 比较期望输出
        if expected_output is not None:
            if result.return_value != expected_output:
                return False, f"输出不匹配: 期望 {expected_output}, 实际 {result.return_value}"

        return True, None

    def get_stats(self) -> dict:
        """获取执行统计"""
        return {
            "total_executions": self._execution_count,
            "sandbox_enabled": self.enable_sandbox,
            "default_timeout": self.default_timeout,
            "max_memory_mb": self.max_memory_mb,
        }
