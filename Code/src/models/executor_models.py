"""
执行器数据模型

定义工具执行相关的数据结构，包括执行上下文、结果、日志等。
"""

from datetime import datetime
from enum import Enum
from typing import Any, Optional
from pydantic import BaseModel, Field, ConfigDict


class ExecutionStatus(str, Enum):
    """执行状态"""
    PENDING = "pending"           # 等待执行
    RUNNING = "running"           # 执行中
    SUCCESS = "success"           # 执行成功
    FAILED = "failed"             # 执行失败
    TIMEOUT = "timeout"           # 执行超时
    CANCELLED = "cancelled"       # 已取消
    RETRYING = "retrying"         # 重试中


class ExecutionPriority(str, Enum):
    """执行优先级"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ResourceType(str, Enum):
    """资源类型"""
    CPU = "cpu"
    MEMORY = "memory"
    DISK = "disk"
    NETWORK = "network"
    FILE_HANDLE = "file_handle"


class ExecutionContext(BaseModel):
    """执行上下文"""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    execution_id: str = Field(description="执行ID")
    tool_name: str = Field(description="工具名称")
    step_id: str = Field(description="步骤ID")

    # 输入参数
    input_params: dict[str, Any] = Field(default_factory=dict, description="输入参数")

    # 执行配置
    timeout_seconds: int = Field(default=300, description="超时时间（秒）")
    max_retries: int = Field(default=3, description="最大重试次数")
    retry_delay_seconds: int = Field(default=5, description="重试延迟（秒）")

    # 资源限制
    max_memory_mb: Optional[int] = Field(default=None, description="最大内存（MB）")
    max_cpu_percent: Optional[int] = Field(default=None, description="最大CPU使用率（%）")
    max_disk_mb: Optional[int] = Field(default=None, description="最大磁盘使用（MB）")

    # 权限和安全
    permission_level: str = Field(default="low", description="权限级别")
    sandbox_enabled: bool = Field(default=True, description="是否启用沙箱")
    allow_network: bool = Field(default=False, description="是否允许网络访问")
    allow_file_write: bool = Field(default=False, description="是否允许文件写入")

    # 依赖和优先级
    depends_on: list[str] = Field(default_factory=list, description="依赖的执行ID")
    priority: ExecutionPriority = Field(default=ExecutionPriority.MEDIUM, description="执行优先级")

    # 元数据
    metadata: dict[str, Any] = Field(default_factory=dict, description="元数据")
    created_at: datetime = Field(default_factory=datetime.now, description="创建时间")


class ResourceUsage(BaseModel):
    """资源使用情况"""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    cpu_percent: float = Field(default=0.0, description="CPU使用率（%）")
    memory_mb: float = Field(default=0.0, description="内存使用（MB）")
    disk_read_mb: float = Field(default=0.0, description="磁盘读取（MB）")
    disk_write_mb: float = Field(default=0.0, description="磁盘写入（MB）")
    network_sent_mb: float = Field(default=0.0, description="网络发送（MB）")
    network_recv_mb: float = Field(default=0.0, description="网络接收（MB）")

    peak_memory_mb: float = Field(default=0.0, description="峰值内存（MB）")
    peak_cpu_percent: float = Field(default=0.0, description="峰值CPU（%）")

    def update_peaks(self):
        """更新峰值"""
        self.peak_memory_mb = max(self.peak_memory_mb, self.memory_mb)
        self.peak_cpu_percent = max(self.peak_cpu_percent, self.cpu_percent)


class ExecutionLog(BaseModel):
    """执行日志"""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    timestamp: datetime = Field(default_factory=datetime.now, description="时间戳")
    level: str = Field(description="日志级别（INFO/WARNING/ERROR）")
    message: str = Field(description="日志消息")
    details: Optional[dict[str, Any]] = Field(default=None, description="详细信息")


class ExecutionError(BaseModel):
    """执行错误"""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    error_type: str = Field(description="错误类型")
    error_message: str = Field(description="错误消息")
    error_code: Optional[str] = Field(default=None, description="错误代码")
    stack_trace: Optional[str] = Field(default=None, description="堆栈跟踪")
    recoverable: bool = Field(default=False, description="是否可恢复")
    retry_recommended: bool = Field(default=False, description="是否建议重试")


class ExecutionResult(BaseModel):
    """执行结果"""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    execution_id: str = Field(description="执行ID")
    tool_name: str = Field(description="工具名称")
    step_id: str = Field(description="步骤ID")

    # 执行状态
    status: ExecutionStatus = Field(description="执行状态")
    success: bool = Field(description="是否成功")

    # 执行结果
    output: Optional[Any] = Field(default=None, description="输出结果")
    error: Optional[ExecutionError] = Field(default=None, description="错误信息")

    # 时间统计
    started_at: datetime = Field(description="开始时间")
    completed_at: Optional[datetime] = Field(default=None, description="完成时间")
    duration_seconds: float = Field(default=0.0, description="执行时长（秒）")

    # 重试信息
    attempt_number: int = Field(default=1, description="尝试次数")
    max_retries: int = Field(default=3, description="最大重试次数")
    retry_count: int = Field(default=0, description="已重试次数")

    # 资源使用
    resource_usage: ResourceUsage = Field(default_factory=ResourceUsage, description="资源使用情况")

    # 日志
    logs: list[ExecutionLog] = Field(default_factory=list, description="执行日志")

    # 元数据
    metadata: dict[str, Any] = Field(default_factory=dict, description="元数据")

    def add_log(self, level: str, message: str, details: Optional[dict[str, Any]] = None):
        """添加日志"""
        log = ExecutionLog(level=level, message=message, details=details)
        self.logs.append(log)

    def mark_success(self, output: Any):
        """标记为成功"""
        self.status = ExecutionStatus.SUCCESS
        self.success = True
        self.output = output
        self.completed_at = datetime.now()
        if self.started_at:
            self.duration_seconds = (self.completed_at - self.started_at).total_seconds()

    def mark_failed(self, error: ExecutionError):
        """标记为失败"""
        self.status = ExecutionStatus.FAILED
        self.success = False
        self.error = error
        self.completed_at = datetime.now()
        if self.started_at:
            self.duration_seconds = (self.completed_at - self.started_at).total_seconds()

    def mark_timeout(self, timeout_seconds: float = 0.0):
        """标记为超时"""
        self.status = ExecutionStatus.TIMEOUT
        self.success = False
        self.completed_at = datetime.now()
        if self.started_at:
            self.duration_seconds = (self.completed_at - self.started_at).total_seconds()
        self.error = ExecutionError(
            error_type="TimeoutError",
            error_message=f"Execution exceeded timeout of {timeout_seconds}s",
            recoverable=True,
            retry_recommended=True
        )


class ParallelExecutionResult(BaseModel):
    """并行执行结果"""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    group_id: str = Field(description="执行组ID")
    results: list[ExecutionResult] = Field(description="各个执行结果")

    # 整体状态
    all_success: bool = Field(description="是否全部成功")
    any_failed: bool = Field(description="是否有失败")

    # 时间统计
    started_at: datetime = Field(description="开始时间")
    completed_at: datetime = Field(description="完成时间")
    total_duration_seconds: float = Field(description="总时长（秒）")

    # 资源统计
    total_resource_usage: ResourceUsage = Field(default_factory=ResourceUsage, description="总资源使用")

    @classmethod
    def from_results(cls, group_id: str, results: list[ExecutionResult]) -> "ParallelExecutionResult":
        """从执行结果列表创建"""
        all_success = all(r.success for r in results)
        any_failed = any(not r.success for r in results)

        started_at = min(r.started_at for r in results)
        completed_at = max(r.completed_at for r in results if r.completed_at)
        total_duration = (completed_at - started_at).total_seconds()

        # 聚合资源使用
        total_usage = ResourceUsage()
        for r in results:
            total_usage.cpu_percent += r.resource_usage.cpu_percent
            total_usage.memory_mb += r.resource_usage.memory_mb
            total_usage.disk_read_mb += r.resource_usage.disk_read_mb
            total_usage.disk_write_mb += r.resource_usage.disk_write_mb
            total_usage.network_sent_mb += r.resource_usage.network_sent_mb
            total_usage.network_recv_mb += r.resource_usage.network_recv_mb
            total_usage.peak_memory_mb = max(total_usage.peak_memory_mb, r.resource_usage.peak_memory_mb)
            total_usage.peak_cpu_percent = max(total_usage.peak_cpu_percent, r.resource_usage.peak_cpu_percent)

        return cls(
            group_id=group_id,
            results=results,
            all_success=all_success,
            any_failed=any_failed,
            started_at=started_at,
            completed_at=completed_at,
            total_duration_seconds=total_duration,
            total_resource_usage=total_usage
        )


class ExecutionPlan(BaseModel):
    """执行计划"""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    plan_id: str = Field(description="计划ID")
    contexts: list[ExecutionContext] = Field(description="执行上下文列表")

    # 执行策略
    execution_strategy: str = Field(default="sequential", description="执行策略（sequential/parallel/hybrid）")
    parallel_groups: list[list[str]] = Field(default_factory=list, description="并行执行组（execution_id列表）")

    # 失败处理
    stop_on_first_failure: bool = Field(default=False, description="首次失败时停止")
    fallback_enabled: bool = Field(default=True, description="是否启用降级")

    # 元数据
    created_at: datetime = Field(default_factory=datetime.now, description="创建时间")
    metadata: dict[str, Any] = Field(default_factory=dict, description="元数据")


class ExecutionSummary(BaseModel):
    """执行摘要"""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    plan_id: str = Field(description="计划ID")

    # 统计
    total_executions: int = Field(description="总执行数")
    successful_executions: int = Field(description="成功执行数")
    failed_executions: int = Field(description="失败执行数")
    timeout_executions: int = Field(description="超时执行数")

    # 时间
    started_at: datetime = Field(description="开始时间")
    completed_at: datetime = Field(description="完成时间")
    total_duration_seconds: float = Field(description="总时长（秒）")

    # 资源
    total_resource_usage: ResourceUsage = Field(description="总资源使用")

    # 结果
    results: list[ExecutionResult] = Field(description="所有执行结果")

    @property
    def success_rate(self) -> float:
        """成功率"""
        if self.total_executions == 0:
            return 0.0
        return self.successful_executions / self.total_executions

    @property
    def average_duration_seconds(self) -> float:
        """平均执行时长"""
        if self.total_executions == 0:
            return 0.0
        return self.total_duration_seconds / self.total_executions
