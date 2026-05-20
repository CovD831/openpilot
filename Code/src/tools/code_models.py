"""
代码生成数据模型

定义代码生成、审查、执行相关的数据结构。
"""

from datetime import datetime
from enum import Enum
from typing import Any, Optional
from pydantic import BaseModel, Field, ConfigDict


class CodeLanguage(str, Enum):
    """代码语言"""
    PYTHON = "python"
    SHELL = "shell"
    BASH = "bash"


class DangerLevel(str, Enum):
    """危险等级"""
    SAFE = "safe"           # 安全
    LOW = "low"             # 低风险
    MEDIUM = "medium"       # 中风险
    HIGH = "high"           # 高风险
    CRITICAL = "critical"   # 严重风险


class CodeGenerationRequest(BaseModel):
    """代码生成请求"""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    request_id: str = Field(description="请求ID")
    task_description: str = Field(description="任务描述")
    language: CodeLanguage = Field(default=CodeLanguage.PYTHON, description="目标语言")

    # 输入数据
    input_data: Optional[dict[str, Any]] = Field(default=None, description="输入数据")
    context: Optional[str] = Field(default=None, description="上下文信息")
    prompt_context: dict[str, Any] = Field(default_factory=dict, description="上层 Agent 传入的结构化提示上下文")

    # 约束条件
    max_lines: int = Field(default=100, description="最大行数")
    allowed_imports: Optional[list[str]] = Field(default=None, description="允许的导入")
    forbidden_operations: list[str] = Field(
        default_factory=lambda: ["os.system", "eval", "exec", "subprocess.call"],
        description="禁止的操作"
    )

    # 执行约束
    timeout_seconds: int = Field(default=30, description="执行超时（秒）")
    max_memory_mb: int = Field(default=512, description="最大内存（MB）")

    # 附加属性
    created_at: datetime = Field(default_factory=datetime.now, description="创建时间")
    attributes: dict[str, Any] = Field(default_factory=dict, description="附加属性")


class GeneratedCode(BaseModel):
    """生成的代码"""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    code_id: str = Field(description="代码ID")
    request_id: str = Field(description="请求ID")

    # 代码内容
    language: CodeLanguage = Field(description="代码语言")
    code: str = Field(description="代码内容")

    # 代码元信息
    line_count: int = Field(description="代码行数")
    imports: list[str] = Field(default_factory=list, description="导入的模块")
    functions: list[str] = Field(default_factory=list, description="定义的函数")

    # 生成信息
    model_used: str = Field(description="使用的模型")
    generation_time_ms: int = Field(description="生成耗时（毫秒）")
    tokens_used: int = Field(default=0, description="使用的token数")

    # 附加属性
    generated_at: datetime = Field(default_factory=datetime.now, description="生成时间")
    attributes: dict[str, Any] = Field(default_factory=dict, description="附加属性")


class DangerousOperation(BaseModel):
    """危险操作"""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    operation: str = Field(description="操作名称")
    line_number: int = Field(description="行号")
    danger_level: DangerLevel = Field(description="危险等级")
    reason: str = Field(description="危险原因")
    suggestion: Optional[str] = Field(default=None, description="修复建议")


class CodeReviewResult(BaseModel):
    """代码审查结果"""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    code_id: str = Field(description="代码ID")

    # 审查结果
    approved: bool = Field(description="是否通过审查")
    overall_danger_level: DangerLevel = Field(description="整体危险等级")

    # 发现的问题
    dangerous_operations: list[DangerousOperation] = Field(
        default_factory=list,
        description="危险操作列表"
    )
    syntax_errors: list[str] = Field(default_factory=list, description="语法错误")
    warnings: list[str] = Field(default_factory=list, description="警告信息")

    # 代码质量
    quality_score: float = Field(default=0.0, ge=0.0, le=1.0, description="质量评分")
    complexity_score: float = Field(default=0.0, ge=0.0, le=1.0, description="复杂度评分")

    # 建议
    recommendations: list[str] = Field(default_factory=list, description="改进建议")

    # 元数据
    reviewed_at: datetime = Field(default_factory=datetime.now, description="审查时间")
    reviewer_version: str = Field(default="1.0.0", description="审查器版本")


class CodeExecutionResult(BaseModel):
    """代码执行结果"""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    execution_id: str = Field(description="执行ID")
    code_id: str = Field(description="代码ID")

    # 执行状态
    success: bool = Field(description="是否成功")
    exit_code: int = Field(default=0, description="退出码")

    # 输出
    stdout: str = Field(default="", description="标准输出")
    stderr: str = Field(default="", description="标准错误")
    return_value: Optional[Any] = Field(default=None, description="返回值")

    # 错误信息
    error_type: Optional[str] = Field(default=None, description="错误类型")
    error_message: Optional[str] = Field(default=None, description="错误消息")
    error_line: Optional[int] = Field(default=None, description="错误行号")
    traceback: Optional[str] = Field(default=None, description="错误堆栈")

    # 执行统计
    execution_time_ms: int = Field(description="执行时间（毫秒）")
    memory_used_mb: float = Field(default=0.0, description="内存使用（MB）")
    cpu_percent: float = Field(default=0.0, description="CPU使用率（%）")

    # 元数据
    executed_at: datetime = Field(default_factory=datetime.now, description="执行时间")
    sandbox_used: bool = Field(default=True, description="是否使用沙箱")


class CodeFixSuggestion(BaseModel):
    """代码修复建议"""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    error_type: str = Field(description="错误类型")
    error_message: str = Field(description="错误消息")

    # 修复建议
    suggested_fix: str = Field(description="建议的修复方法")
    fixed_code: Optional[str] = Field(default=None, description="修复后的代码")

    # 置信度
    confidence: float = Field(ge=0.0, le=1.0, description="修复置信度")

    # 说明
    explanation: str = Field(description="修复说明")


class CodeCacheEntry(BaseModel):
    """代码缓存条目"""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    cache_key: str = Field(description="缓存键（任务描述的哈希）")

    # 代码信息
    code: str = Field(description="代码内容")
    language: CodeLanguage = Field(description="代码语言")

    # 使用统计
    use_count: int = Field(default=1, description="使用次数")
    success_count: int = Field(default=0, description="成功次数")
    failure_count: int = Field(default=0, description="失败次数")

    # 性能统计
    avg_execution_time_ms: float = Field(default=0.0, description="平均执行时间")

    # 时间戳
    created_at: datetime = Field(default_factory=datetime.now, description="创建时间")
    last_used_at: datetime = Field(default_factory=datetime.now, description="最后使用时间")

    # 附加属性
    attributes: dict[str, Any] = Field(default_factory=dict, description="附加属性")

    @property
    def success_rate(self) -> float:
        """成功率"""
        total = self.success_count + self.failure_count
        if total == 0:
            return 0.0
        return self.success_count / total


class CodeGenerationSummary(BaseModel):
    """代码生成摘要"""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    # 统计
    total_requests: int = Field(description="总请求数")
    successful_generations: int = Field(description="成功生成数")
    failed_generations: int = Field(description="失败生成数")

    # 审查统计
    approved_codes: int = Field(description="通过审查数")
    rejected_codes: int = Field(description="未通过审查数")

    # 执行统计
    successful_executions: int = Field(description="成功执行数")
    failed_executions: int = Field(description="失败执行数")

    # 缓存统计
    cache_hits: int = Field(default=0, description="缓存命中数")
    cache_misses: int = Field(default=0, description="缓存未命中数")

    # 时间统计
    total_generation_time_ms: int = Field(description="总生成时间")
    total_execution_time_ms: int = Field(description="总执行时间")

    # 时间范围
    start_time: datetime = Field(description="开始时间")
    end_time: datetime = Field(description="结束时间")

    @property
    def generation_success_rate(self) -> float:
        """生成成功率"""
        if self.total_requests == 0:
            return 0.0
        return self.successful_generations / self.total_requests

    @property
    def execution_success_rate(self) -> float:
        """执行成功率"""
        total = self.successful_executions + self.failed_executions
        if total == 0:
            return 0.0
        return self.successful_executions / total

    @property
    def cache_hit_rate(self) -> float:
        """缓存命中率"""
        total = self.cache_hits + self.cache_misses
        if total == 0:
            return 0.0
        return self.cache_hits / total
