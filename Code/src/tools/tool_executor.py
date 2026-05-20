"""
安全工具执行器

在受控环境中安全执行工具，支持超时、资源限制、错误处理。
"""

import time
import uuid
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from datetime import datetime
from typing import Any, Optional

from tools.executor_models import (
    ExecutionContext,
    ExecutionError,
    ExecutionResult,
    ExecutionStatus,
    ParallelExecutionResult,
)
from tools.tool_selection import (
    ParallelExecutionGroup,
    ToolSelection,
)
from tools.tool_registry import ToolRegistry
from core.tool_contracts import ToolDefinition
from core.exceptions import classify_error, is_retryable_error, extract_error_context
from metadata import (
    FailureMetadata,
    ResultStatus,
    ToolInputMetadata,
    ToolResultMetadata,
    metadata_summary,
    payload_to_artifact,
)


class ToolExecutor:
    """安全工具执行器"""

    def __init__(self, registry: ToolRegistry, max_workers: int = 4, logger: Any | None = None):
        """
        初始化执行器

        Args:
            registry: 工具注册表
            max_workers: 最大并发工作线程数
            logger: Optional OpenPilotLogger-compatible structured logger
        """
        self.registry = registry
        self.max_workers = max_workers
        self.logger = logger
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
        self._log_tool_event(
            "start",
            tool_selection,
            context,
            success=None,
            input_summary=tool_selection.input_metadata,
        )

        # 执行前检查
        check_result = self._pre_execution_check(tool_selection, context)
        if not check_result["passed"]:
            result.attributes.update(check_result.get("attributes", {}))
            result.mark_failed(ExecutionError(
                error_type=check_result.get("error_type", "PreExecutionCheckFailed"),
                error_message=check_result["reason"],
                recoverable=check_result.get("recoverable", False),
                retry_recommended=check_result.get("retry_recommended", False)
            ))
            self._log_tool_event(
                "failure",
                tool_selection,
                context,
                success=False,
                input_summary=tool_selection.input_metadata,
                error=result.error.error_message if result.error else check_result["reason"],
                annotations=result.attributes,
                duration_ms=int(result.duration_seconds * 1000),
            )
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
                    tool_selection.input_metadata,
                    timeout=context.timeout_seconds
                )
                output_metadata = self._coerce_tool_result_metadata(tool_selection.tool_name, output)

                # 记录资源使用
                execution_time = time.time() - start_time
                result.resource_usage.cpu_percent = 0.0  # 简化版本，实际应该监控
                result.resource_usage.memory_mb = 0.0
                result.resource_usage.update_peaks()

                # 执行后验证
                validation_result = self._post_execution_validation(
                    tool_selection,
                    output_metadata,
                    context
                )

                if validation_result["valid"]:
                    result.mark_success(output_metadata)
                    warnings = validation_result.get("warnings", [])
                    if warnings:
                        result.attributes["validation_warnings"] = warnings
                        for warning in warnings:
                            result.add_log("WARNING", warning)
                            self._log_tool_event(
                                "validation_warning",
                                tool_selection,
                                context,
                                success=True,
                                input_summary=tool_selection.input_metadata,
                                output_summary=output_metadata,
                                annotations={"warning": warning},
                                duration_ms=int(result.duration_seconds * 1000),
                            )
                    result.add_log("INFO", f"Execution completed successfully in {execution_time:.2f}s")
                    self._log_tool_event(
                        "success",
                        tool_selection,
                        context,
                        success=True,
                        input_summary=tool_selection.input_metadata,
                        output_summary=output_metadata,
                        annotations=result.attributes,
                        duration_ms=int(result.duration_seconds * 1000),
                    )
                else:
                    result.attributes.update(validation_result.get("attributes", {}))
                    result.mark_failed(ExecutionError(
                        error_type="ValidationFailed",
                        error_message=validation_result["reason"],
                        recoverable=False,
                        retry_recommended=False
                    ))
                    self._log_tool_event(
                        "failure",
                        tool_selection,
                        context,
                        success=False,
                        input_summary=tool_selection.input_metadata,
                        output_summary=output_metadata,
                        error=validation_result["reason"],
                        annotations=result.attributes,
                        duration_ms=int(result.duration_seconds * 1000),
                    )

            except FutureTimeoutError:
                result.mark_timeout(context.timeout_seconds)
                result.add_log("ERROR", f"Execution timed out after {context.timeout_seconds}s")
                self._log_tool_event(
                    "failure",
                    tool_selection,
                    context,
                    success=False,
                    input_summary=tool_selection.input_metadata,
                    error=f"Execution timed out after {context.timeout_seconds}s",
                    annotations=result.attributes,
                    duration_ms=int(result.duration_seconds * 1000),
                )

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
            result.attributes.update(
                self._failure_metadata(
                    tool_selection.tool_name,
                    error.error_type,
                    error.error_message,
                )
            )
            result.mark_failed(error)
            result.add_log("ERROR", f"Execution failed ({error_category.value}): {str(e)}")
            self._log_tool_event(
                "failure",
                tool_selection,
                context,
                success=False,
                input_summary=tool_selection.input_metadata,
                error=error.error_message,
                annotations=result.attributes,
                duration_ms=int(result.duration_seconds * 1000),
            )

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
                input_metadata=tool_selection.input_metadata,
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
            input_metadata=tool_selection.input_metadata,
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
            return {
                "passed": False,
                "reason": f"Missing dependencies: {missing}",
                "error_type": "MissingDependency",
                "attributes": {"missing_dependencies": missing},
            }

        validation_result = self._validate_input_metadata(tool_def, tool_selection.input_metadata)
        if not validation_result["valid"]:
            return {
                "passed": False,
                "reason": validation_result["reason"],
                "error_type": "InvalidInput",
                "recoverable": True,
                "retry_recommended": True,
                "attributes": {
                    "validation_errors": validation_result["errors"],
                    **self._failure_metadata(
                        tool_selection.tool_name,
                        "invalid_input",
                        validation_result["reason"],
                    ),
                },
            }

        return {"passed": True}

    def _post_execution_validation(
        self,
        tool_selection: ToolSelection,
        output_metadata: ToolResultMetadata,
        context: ExecutionContext
    ) -> dict[str, Any]:
        """执行后验证"""
        if output_metadata is None:
            return {
                "valid": False,
                "reason": "Output is None",
                "attributes": self._failure_metadata(
                    tool_selection.tool_name,
                    "invalid_output",
                    "Output is None",
                ),
            }

        tool_def = self.registry.get(tool_selection.tool_name)
        warnings = []
        if tool_def:
            if not isinstance(output_metadata, tool_def.output_metadata_type):
                warnings.append(
                    f"Output for {tool_def.name} does not match declared metadata type "
                    f"{tool_def.output_metadata_type.__name__}: got {type(output_metadata).__name__}"
                )

        return {"valid": True, "warnings": warnings}

    def _validate_input_metadata(
        self,
        tool_def: ToolDefinition,
        input_metadata: ToolInputMetadata
    ) -> dict[str, Any]:
        """Validate tool input metadata against ToolDefinition."""
        errors = []
        if not isinstance(input_metadata, tool_def.input_metadata_type):
            errors.append(
                f"Invalid metadata type for {tool_def.name}: "
                f"expected {tool_def.input_metadata_type.__name__}, got {type(input_metadata).__name__}"
            )
        if input_metadata.tool_name and input_metadata.tool_name != tool_def.name:
            errors.append(
                f"Input metadata tool_name mismatch: expected {tool_def.name}, got {input_metadata.tool_name}"
            )
        contract = tool_def.contract_metadata
        params = input_metadata.to_params()
        if contract:
            for field_name, default in contract.input_defaults.items():
                if field_name not in params and hasattr(input_metadata, field_name):
                    setattr(input_metadata, field_name, deepcopy(default))
            params = input_metadata.to_params()

        for field_name in (contract.required_input_fields if contract else []):
            value_present = field_name in params
            if not value_present:
                errors.append(f"Missing required metadata field: {field_name}")
                continue
            if params[field_name] is None:
                errors.append(f"Required metadata field cannot be None: {field_name}")

        return {
            "valid": not errors,
            "errors": errors,
            "reason": "; ".join(errors),
        }

    def _failure_metadata(
        self,
        tool_name: str,
        error_type: str,
        error_message: str
    ) -> dict[str, Any]:
        """Build failure attributes from a tool's declared failure modes."""
        tool_def = self.registry.get(tool_name)
        if not tool_def:
            return {}

        normalized_error = (error_type or "").lower()
        normalized_message = (error_message or "").lower()
        for failure_mode in tool_def.failure_modes:
            mode_type = failure_mode.error_type.lower()
            spaced_mode_type = mode_type.replace("_", " ")
            if (
                mode_type in normalized_error
                or mode_type in normalized_message
                or spaced_mode_type in normalized_message
            ):
                return {
                    "failure_mode": failure_mode.error_type,
                    "recovery_strategy": failure_mode.recovery_strategy,
                }

        if normalized_error in {"invalidinput", "invalid_input"} or "missing required" in normalized_message:
            return {
                "failure_mode": "invalid_input",
                "recovery_strategy": "Provide all required metadata fields with the declared types.",
            }

        return {}

    def _execute_with_timeout(
        self,
        tool_executor: callable,
        input_metadata: ToolInputMetadata,
        timeout: int
    ) -> Any:
        """带超时的执行"""
        future = self._executor_pool.submit(tool_executor, input_metadata)
        return future.result(timeout=timeout)

    def _coerce_tool_result_metadata(self, tool_name: str, output: Any) -> ToolResultMetadata:
        if isinstance(output, ToolResultMetadata):
            return output
        if hasattr(output, "model_dump"):
            output = output.model_dump(mode="json")
        return ToolResultMetadata(
            tool_name=tool_name,
            status=ResultStatus.SUCCESS,
            result=payload_to_artifact(tool_name, output, None),
        )

    def _log_tool_event(
        self,
        event_type: str,
        tool_selection: ToolSelection,
        context: ExecutionContext,
        *,
        success: bool | None,
        input_summary: Any | None = None,
        output_summary: Any | None = None,
        error: str | None = None,
        annotations: dict[str, Any] | None = None,
        duration_ms: int | None = None,
    ) -> None:
        if not self.logger or not hasattr(self.logger, "log_structured_event"):
            return
        try:
            self.logger.log_structured_event(
                source_type="tool",
                source_name=tool_selection.tool_name,
                phase="tool_execution",
                event_type=event_type,
                session_id=context.attributes.get("session_id", context.execution_id),
                turn_id=int(context.attributes.get("turn_id", 1)),
                success=success,
                duration_ms=duration_ms,
                input_summary=self._json_safe_summary(input_summary),
                output_summary=self._json_safe_summary(output_summary),
                error=error,
                annotations=annotations or {},
            )
        except Exception:
            pass

    def _json_safe_summary(self, value: Any) -> Any:
        return metadata_summary(value)

    def shutdown(self):
        """关闭执行器"""
        self._executor_pool.shutdown(wait=True)
