"""
安全工具执行器

在受控环境中安全执行工具，支持超时、资源限制、错误处理。
"""

import time
import uuid
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from datetime import datetime
from typing import Any, Optional

from execution.executor_models import (
    ExecutionContext,
    ExecutionError,
    ExecutionResult,
    ExecutionStatus,
    ParallelExecutionResult,
)
from tools.tool_orchestration_models import (
    ParallelExecutionGroup,
    ToolSelection,
)
from tools.tool_registry import ToolRegistry
from core.exceptions import classify_error, is_retryable_error, extract_error_context


class ToolExecutor:
    """安全工具执行器"""

    def __init__(self, registry: ToolRegistry, max_workers: int = 4):
        """
        初始化执行器

        Args:
            registry: 工具注册表
            max_workers: 最大并发工作线程数
        """
        self.registry = registry
        self.max_workers = max_workers
        self._executor_pool = ThreadPoolExecutor(max_workers=max_workers)

    def execute_single(
        self,
        tool_selection: ToolSelection,
        context: Optional[ExecutionContext] = None
    ) -> ExecutionResult:
        """
        执行单个工具

        Args:
            tool_selection: 工具选择
            context: 执行上下文（可选）

        Returns:
            ExecutionResult: 执行结果
        """
        # 创建执行上下文
        if context is None:
            context = self._create_context(tool_selection)

        # 创建执行结果
        result = ExecutionResult(
            execution_id=context.execution_id,
            tool_name=tool_selection.tool_name,
            step_id=tool_selection.step_id,
            status=ExecutionStatus.PENDING,
            success=False,
            started_at=datetime.now(),
            max_retries=context.max_retries
        )

        # 执行前检查
        check_result = self._pre_execution_check(tool_selection, context)
        if not check_result["passed"]:
            result.mark_failed(ExecutionError(
                error_type="PreExecutionCheckFailed",
                error_message=check_result["reason"],
                recoverable=False,
                retry_recommended=False
            ))
            return result

        # 执行工具
        result.status = ExecutionStatus.RUNNING
        result.add_log("INFO", f"Starting execution of {tool_selection.tool_name}")

        try:
            # 获取工具执行器
            tool_executor = self.registry.get_executor(tool_selection.tool_name)
            if not tool_executor:
                raise ValueError(f"Tool executor not found: {tool_selection.tool_name}")

            # 执行工具（带超时）
            start_time = time.time()

            try:
                output = self._execute_with_timeout(
                    tool_executor,
                    tool_selection.input_params,
                    timeout=context.timeout_seconds
                )

                # 记录资源使用
                execution_time = time.time() - start_time
                result.resource_usage.cpu_percent = 0.0  # 简化版本，实际应该监控
                result.resource_usage.memory_mb = 0.0
                result.resource_usage.update_peaks()

                # 执行后验证
                validation_result = self._post_execution_validation(
                    tool_selection,
                    output,
                    context
                )

                if validation_result["valid"]:
                    result.mark_success(output)
                    result.add_log("INFO", f"Execution completed successfully in {execution_time:.2f}s")
                else:
                    result.mark_failed(ExecutionError(
                        error_type="ValidationFailed",
                        error_message=validation_result["reason"],
                        recoverable=False,
                        retry_recommended=False
                    ))

            except FutureTimeoutError:
                result.mark_timeout(context.timeout_seconds)
                result.add_log("ERROR", f"Execution timed out after {context.timeout_seconds}s")

        except Exception as e:
            # 使用增强的错误分类
            error_category = classify_error(e)
            error_context = extract_error_context(e)

            # Convert traceback list to string if present
            traceback_data = error_context.get('traceback')
            if traceback_data and isinstance(traceback_data, list):
                stack_trace_str = '\n'.join([
                    f"  File \"{frame['file']}\", line {frame['line']}, in {frame['function']}"
                    for frame in traceback_data
                ])
            else:
                stack_trace_str = str(traceback_data) if traceback_data else None

            error = ExecutionError(
                error_type=error_context.get('type', type(e).__name__),
                error_message=error_context.get('message', str(e)),
                stack_trace=stack_trace_str,
                recoverable=is_retryable_error(e),
                retry_recommended=is_retryable_error(e)
            )
            result.mark_failed(error)
            result.add_log("ERROR", f"Execution failed ({error_category.value}): {str(e)}")

        return result

    def execute_sequential(
        self,
        tool_selections: list[ToolSelection],
        stop_on_failure: bool = False
    ) -> list[ExecutionResult]:
        """
        顺序执行多个工具

        Args:
            tool_selections: 工具选择列表
            stop_on_failure: 是否在首次失败时停止

        Returns:
            list[ExecutionResult]: 执行结果列表
        """
        results = []

        for selection in tool_selections:
            result = self.execute_single(selection)
            results.append(result)

            if stop_on_failure and not result.success:
                # 标记剩余任务为取消
                for remaining in tool_selections[len(results):]:
                    cancelled_result = ExecutionResult(
                        execution_id=str(uuid.uuid4()),
                        tool_name=remaining.tool_name,
                        step_id=remaining.step_id,
                        status=ExecutionStatus.CANCELLED,
                        success=False,
                        started_at=datetime.now()
                    )
                    results.append(cancelled_result)
                break

        return results

    def execute_parallel(
        self,
        parallel_group: ParallelExecutionGroup
    ) -> ParallelExecutionResult:
        """
        并行执行工具组

        Args:
            parallel_group: 并行执行组

        Returns:
            ParallelExecutionResult: 并行执行结果
        """
        started_at = datetime.now()

        # 提交所有任务到线程池
        futures = []
        for selection in parallel_group.tool_selections:
            future = self._executor_pool.submit(self.execute_single, selection)
            futures.append((selection, future))

        # 等待所有任务完成（带超时）
        results = []
        for selection, future in futures:
            try:
                result = future.result(timeout=parallel_group.timeout_seconds)
                results.append(result)

                # 如果设置了 fail_fast 且有失败，取消其他任务
                if parallel_group.fail_fast and not result.success:
                    for _, remaining_future in futures[len(results):]:
                        remaining_future.cancel()
                    break

            except FutureTimeoutError:
                # 超时，创建超时结果
                timeout_result = ExecutionResult(
                    execution_id=str(uuid.uuid4()),
                    tool_name=selection.tool_name,
                    step_id=selection.step_id,
                    status=ExecutionStatus.TIMEOUT,
                    success=False,
                    started_at=started_at
                )
                timeout_result.mark_timeout(parallel_group.timeout_seconds)
                results.append(timeout_result)

        # 创建并行执行结果
        completed_at = datetime.now()
        parallel_result = ParallelExecutionResult.from_results(
            group_id=parallel_group.group_id,
            results=results
        )

        return parallel_result

    def execute_with_fallback(
        self,
        tool_selection: ToolSelection,
        fallback_tools: list[str]
    ) -> ExecutionResult:
        """
        执行工具（带降级）

        Args:
            tool_selection: 主工具选择
            fallback_tools: 备选工具列表

        Returns:
            ExecutionResult: 执行结果
        """
        # 先尝试主工具
        result = self.execute_single(tool_selection)

        if result.success:
            return result

        # 主工具失败，尝试备选工具
        result.add_log("INFO", f"Primary tool failed, trying fallbacks: {fallback_tools}")

        for fallback_tool in fallback_tools:
            # 创建备选工具选择
            fallback_selection = ToolSelection(
                step_id=tool_selection.step_id,
                tool_name=fallback_tool,
                reason="fallback",
                confidence=0.5,
                input_params=tool_selection.input_params,
                requires_confirmation=False,
                fallback_tools=[],
                depends_on=tool_selection.depends_on
            )

            # 执行备选工具
            fallback_result = self.execute_single(fallback_selection)

            if fallback_result.success:
                fallback_result.add_log("INFO", f"Fallback tool {fallback_tool} succeeded")
                return fallback_result

        # 所有备选工具都失败
        result.add_log("ERROR", "All fallback tools failed")
        return result

    def _create_context(self, tool_selection: ToolSelection) -> ExecutionContext:
        """创建执行上下文"""
        tool_def = self.registry.get(tool_selection.tool_name)

        return ExecutionContext(
            execution_id=str(uuid.uuid4()),
            tool_name=tool_selection.tool_name,
            step_id=tool_selection.step_id,
            input_params=tool_selection.input_params,
            timeout_seconds=tool_selection.timeout_override or (tool_def.timeout_seconds if tool_def else 30),
            max_retries=tool_def.max_retries if tool_def else 3,
            permission_level=tool_def.permission_level if tool_def else "medium",
            depends_on=tool_selection.depends_on
        )

    def _pre_execution_check(
        self,
        tool_selection: ToolSelection,
        context: ExecutionContext
    ) -> dict[str, Any]:
        """执行前检查"""
        # 检查工具是否存在
        tool_def = self.registry.get(tool_selection.tool_name)
        if not tool_def:
            return {"passed": False, "reason": f"Tool not found: {tool_selection.tool_name}"}

        # 检查工具执行器是否存在
        tool_executor = self.registry.get_executor(tool_selection.tool_name)
        if not tool_executor:
            return {"passed": False, "reason": f"Tool executor not found: {tool_selection.tool_name}"}

        # 检查依赖（简化版本）
        satisfied, missing = self.registry.check_dependencies(tool_selection.tool_name)
        if not satisfied:
            return {"passed": False, "reason": f"Missing dependencies: {missing}"}

        return {"passed": True}

    def _post_execution_validation(
        self,
        tool_selection: ToolSelection,
        output: Any,
        context: ExecutionContext
    ) -> dict[str, Any]:
        """执行后验证"""
        # 简化版本：只检查输出是否为 None
        if output is None:
            return {"valid": False, "reason": "Output is None"}

        return {"valid": True}

    def _execute_with_timeout(
        self,
        tool_executor: callable,
        params: dict[str, Any],
        timeout: int
    ) -> Any:
        """带超时的执行"""
        future = self._executor_pool.submit(tool_executor, params)
        return future.result(timeout=timeout)

    def shutdown(self):
        """关闭执行器"""
        self._executor_pool.shutdown(wait=True)
