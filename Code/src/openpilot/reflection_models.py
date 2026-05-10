"""
反思与优化数据模型

定义反思条目、优化策略、性能指标、学习记录等数据结构。
"""

from datetime import datetime
from enum import Enum
from typing import Any, Optional
from pydantic import BaseModel, Field, ConfigDict


class ReflectionType(str, Enum):
    """反思类型"""
    SUCCESS = "success"         # 成功案例反思
    FAILURE = "failure"         # 失败案例反思
    IMPROVEMENT = "improvement" # 改进机会反思
    PATTERN = "pattern"         # 模式识别反思


class OptimizationTarget(str, Enum):
    """优化目标"""
    PERFORMANCE = "performance"     # 性能优化
    ACCURACY = "accuracy"           # 准确性优化
    EFFICIENCY = "efficiency"       # 效率优化
    RELIABILITY = "reliability"     # 可靠性优化
    COST = "cost"                   # 成本优化


class LearningStatus(str, Enum):
    """学习状态"""
    PENDING = "pending"         # 待学习
    LEARNING = "learning"       # 学习中
    LEARNED = "learned"         # 已学习
    APPLIED = "applied"         # 已应用
    VALIDATED = "validated"     # 已验证


class StrategyType(str, Enum):
    """策略类型"""
    TOOL_SELECTION = "tool_selection"       # 工具选择策略
    EXECUTION = "execution"                 # 执行策略
    RETRY = "retry"                         # 重试策略
    FALLBACK = "fallback"                   # 降级策略
    RESOURCE = "resource"                   # 资源分配策略


class ReflectionEntry(BaseModel):
    """反思条目"""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    reflection_id: str = Field(description="反思ID")
    reflection_type: ReflectionType = Field(description="反思类型")

    # 关联信息
    target_id: str = Field(description="目标ID（执行ID、代码ID等）")
    target_type: str = Field(description="目标类型")

    # 反思内容
    observation: str = Field(description="观察到的现象")
    analysis: str = Field(description="分析结果")
    insights: list[str] = Field(default_factory=list, description="洞察")
    lessons_learned: list[str] = Field(default_factory=list, description="经验教训")

    # 问题识别
    problems_identified: list[str] = Field(
        default_factory=list,
        description="识别的问题"
    )
    root_causes: list[str] = Field(default_factory=list, description="根本原因")

    # 改进建议
    improvement_opportunities: list[str] = Field(
        default_factory=list,
        description="改进机会"
    )
    recommended_actions: list[str] = Field(
        default_factory=list,
        description="推荐行动"
    )

    # 上下文
    context: dict[str, Any] = Field(default_factory=dict, description="上下文信息")

    # 元数据
    created_at: datetime = Field(default_factory=datetime.now, description="创建时间")
    confidence: float = Field(default=0.5, ge=0.0, le=1.0, description="置信度")


class OptimizationStrategy(BaseModel):
    """优化策略"""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    strategy_id: str = Field(description="策略ID")
    strategy_type: StrategyType = Field(description="策略类型")
    optimization_target: OptimizationTarget = Field(description="优化目标")

    # 策略内容
    name: str = Field(description="策略名称")
    description: str = Field(description="策略描述")
    parameters: dict[str, Any] = Field(default_factory=dict, description="策略参数")

    # 适用条件
    applicable_conditions: list[str] = Field(
        default_factory=list,
        description="适用条件"
    )
    constraints: list[str] = Field(default_factory=list, description="约束条件")

    # 预期效果
    expected_improvement: str = Field(description="预期改进")
    expected_impact: float = Field(
        default=0.0,
        ge=-1.0,
        le=1.0,
        description="预期影响（-1到1）"
    )

    # 实施信息
    implementation_steps: list[str] = Field(
        default_factory=list,
        description="实施步骤"
    )
    estimated_effort: str = Field(default="medium", description="预估工作量")

    # 验证信息
    validation_criteria: list[str] = Field(
        default_factory=list,
        description="验证标准"
    )
    success_metrics: list[str] = Field(default_factory=list, description="成功指标")

    # 状态
    enabled: bool = Field(default=True, description="是否启用")
    priority: int = Field(default=5, ge=1, le=10, description="优先级（1-10）")

    # 元数据
    created_at: datetime = Field(default_factory=datetime.now, description="创建时间")
    last_applied_at: Optional[datetime] = Field(
        default=None,
        description="最后应用时间"
    )
    application_count: int = Field(default=0, description="应用次数")


class PerformanceMetrics(BaseModel):
    """性能指标"""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    target_id: str = Field(description="目标ID")
    metric_type: str = Field(description="指标类型")

    # 时间指标
    execution_time_ms: int = Field(default=0, description="执行时间（毫秒）")
    total_time_ms: int = Field(default=0, description="总时间（毫秒）")
    wait_time_ms: int = Field(default=0, description="等待时间（毫秒）")

    # 资源指标
    cpu_usage_percent: float = Field(default=0.0, description="CPU使用率")
    memory_usage_mb: float = Field(default=0.0, description="内存使用（MB）")
    disk_io_mb: float = Field(default=0.0, description="磁盘IO（MB）")
    network_io_mb: float = Field(default=0.0, description="网络IO（MB）")

    # 质量指标
    success_rate: float = Field(default=0.0, ge=0.0, le=1.0, description="成功率")
    error_rate: float = Field(default=0.0, ge=0.0, le=1.0, description="错误率")
    retry_rate: float = Field(default=0.0, ge=0.0, le=1.0, description="重试率")

    # 吞吐量指标
    throughput: float = Field(default=0.0, description="吞吐量（操作/秒）")
    requests_per_second: float = Field(default=0.0, description="请求数/秒")

    # 统计信息
    sample_count: int = Field(default=0, description="样本数量")
    measurement_period_seconds: int = Field(default=0, description="测量周期（秒）")

    # 元数据
    measured_at: datetime = Field(default_factory=datetime.now, description="测量时间")


class LearningRecord(BaseModel):
    """学习记录"""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    record_id: str = Field(description="记录ID")
    learning_status: LearningStatus = Field(description="学习状态")

    # 学习内容
    topic: str = Field(description="学习主题")
    category: str = Field(description="学习类别")
    content: str = Field(description="学习内容")

    # 来源
    source_type: str = Field(description="来源类型（reflection/feedback/experiment）")
    source_id: str = Field(description="来源ID")

    # 学习结果
    key_takeaways: list[str] = Field(default_factory=list, description="关键要点")
    patterns_discovered: list[str] = Field(
        default_factory=list,
        description="发现的模式"
    )
    best_practices: list[str] = Field(default_factory=list, description="最佳实践")

    # 应用信息
    applicable_scenarios: list[str] = Field(
        default_factory=list,
        description="适用场景"
    )
    application_examples: list[str] = Field(
        default_factory=list,
        description="应用示例"
    )

    # 验证信息
    validation_results: list[dict[str, Any]] = Field(
        default_factory=list,
        description="验证结果"
    )
    effectiveness_score: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="有效性评分"
    )

    # 元数据
    created_at: datetime = Field(default_factory=datetime.now, description="创建时间")
    learned_at: Optional[datetime] = Field(default=None, description="学习时间")
    applied_at: Optional[datetime] = Field(default=None, description="应用时间")
    confidence: float = Field(default=0.5, ge=0.0, le=1.0, description="置信度")


class OptimizationResult(BaseModel):
    """优化结果"""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    optimization_id: str = Field(description="优化ID")
    strategy_id: str = Field(description="策略ID")
    target_id: str = Field(description="目标ID")

    # 优化前后对比
    before_metrics: PerformanceMetrics = Field(description="优化前指标")
    after_metrics: PerformanceMetrics = Field(description="优化后指标")

    # 改进情况
    improvement_percentage: float = Field(description="改进百分比")
    improvement_details: dict[str, float] = Field(
        default_factory=dict,
        description="改进详情"
    )

    # 结果评估
    success: bool = Field(description="是否成功")
    actual_impact: float = Field(
        default=0.0,
        ge=-1.0,
        le=1.0,
        description="实际影响"
    )
    side_effects: list[str] = Field(default_factory=list, description="副作用")

    # 元数据
    optimized_at: datetime = Field(default_factory=datetime.now, description="优化时间")
    duration_seconds: int = Field(default=0, description="优化耗时（秒）")


class ReflectionReport(BaseModel):
    """反思报告"""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    report_id: str = Field(description="报告ID")
    report_type: str = Field(description="报告类型")

    # 时间范围
    start_time: datetime = Field(description="开始时间")
    end_time: datetime = Field(description="结束时间")

    # 反思条目
    reflections: list[ReflectionEntry] = Field(
        default_factory=list,
        description="反思条目"
    )

    # 统计信息
    total_reflections: int = Field(description="总反思数")
    success_reflections: int = Field(description="成功反思数")
    failure_reflections: int = Field(description="失败反思数")
    improvement_reflections: int = Field(description="改进反思数")

    # 关键发现
    key_findings: list[str] = Field(default_factory=list, description="关键发现")
    common_patterns: list[str] = Field(default_factory=list, description="常见模式")
    recurring_issues: list[str] = Field(default_factory=list, description="重复问题")

    # 优化建议
    optimization_strategies: list[OptimizationStrategy] = Field(
        default_factory=list,
        description="优化策略"
    )
    priority_actions: list[str] = Field(default_factory=list, description="优先行动")

    # 学习成果
    learning_records: list[LearningRecord] = Field(
        default_factory=list,
        description="学习记录"
    )

    # 元数据
    generated_at: datetime = Field(default_factory=datetime.now, description="生成时间")


class OptimizationStatistics(BaseModel):
    """优化统计"""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    # 时间范围
    start_time: datetime = Field(description="开始时间")
    end_time: datetime = Field(description="结束时间")

    # 优化统计
    total_optimizations: int = Field(description="总优化次数")
    successful_optimizations: int = Field(description="成功优化次数")
    failed_optimizations: int = Field(description="失败优化次数")

    # 改进统计
    average_improvement: float = Field(description="平均改进百分比")
    best_improvement: float = Field(description="最佳改进百分比")
    worst_improvement: float = Field(description="最差改进百分比")

    # 策略统计
    strategy_usage: dict[str, int] = Field(
        default_factory=dict,
        description="策略使用次数"
    )
    strategy_success_rate: dict[str, float] = Field(
        default_factory=dict,
        description="策略成功率"
    )

    # 学习统计
    total_learning_records: int = Field(description="总学习记录数")
    applied_learning_records: int = Field(description="已应用学习记录数")
    validated_learning_records: int = Field(description="已验证学习记录数")

    # 性能趋势
    performance_trend: list[float] = Field(
        default_factory=list,
        description="性能趋势"
    )

    @property
    def success_rate(self) -> float:
        """优化成功率"""
        if self.total_optimizations == 0:
            return 0.0
        return self.successful_optimizations / self.total_optimizations

    @property
    def learning_application_rate(self) -> float:
        """学习应用率"""
        if self.total_learning_records == 0:
            return 0.0
        return self.applied_learning_records / self.total_learning_records
