"""
结果验证与反馈数据模型

定义验证规则、验证结果、反馈条目等数据结构。
"""

from datetime import datetime
from enum import Enum
from typing import Any, Optional
from pydantic import BaseModel, Field, ConfigDict


class ValidationType(str, Enum):
    """验证类型"""
    FORMAT = "format"           # 格式验证
    TYPE = "type"               # 类型验证
    RANGE = "range"             # 范围验证
    PATTERN = "pattern"         # 模式验证
    SCHEMA = "schema"           # 结构验证
    CUSTOM = "custom"           # 自定义验证


class ValidationSeverity(str, Enum):
    """验证严重程度"""
    INFO = "info"               # 信息
    WARNING = "warning"         # 警告
    ERROR = "error"             # 错误
    CRITICAL = "critical"       # 严重错误


class FeedbackType(str, Enum):
    """反馈类型"""
    POSITIVE = "positive"       # 正面反馈
    NEGATIVE = "negative"       # 负面反馈
    NEUTRAL = "neutral"         # 中性反馈
    SUGGESTION = "suggestion"   # 建议


class QualityLevel(str, Enum):
    """质量等级"""
    EXCELLENT = "excellent"     # 优秀 (>= 0.9)
    GOOD = "good"               # 良好 (>= 0.7)
    FAIR = "fair"               # 一般 (>= 0.5)
    POOR = "poor"               # 较差 (>= 0.3)
    VERY_POOR = "very_poor"     # 很差 (< 0.3)


class ValidationRule(BaseModel):
    """验证规则"""
    model_config = ConfigDict(arbitrary_types_allowed=True, populate_by_name=True)

    rule_id: str = Field(description="规则ID")
    name: str = Field(description="规则名称")
    validation_type: ValidationType = Field(description="验证类型")
    severity: ValidationSeverity = Field(description="严重程度")

    # 验证参数
    expected_type: Optional[str] = Field(default=None, description="期望的类型")
    expected_format: Optional[str] = Field(default=None, description="期望的格式")
    pattern: Optional[str] = Field(default=None, description="正则模式")
    min_value: Optional[float] = Field(default=None, description="最小值")
    max_value: Optional[float] = Field(default=None, description="最大值")
    allowed_values: Optional[list[Any]] = Field(default=None, description="允许的值列表")
    json_schema: Optional[dict] = Field(default=None, alias="schema", description="JSON Schema")

    # 自定义验证
    custom_validator: Optional[str] = Field(default=None, description="自定义验证器名称")

    # 元数据
    description: str = Field(description="规则描述")
    enabled: bool = Field(default=True, description="是否启用")
    created_at: datetime = Field(default_factory=datetime.now, description="创建时间")

    @property
    def schema(self) -> Optional[dict]:
        """Backward-compatible access for callers that used rule.schema."""
        return self.json_schema


class ValidationIssue(BaseModel):
    """验证问题"""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    rule_id: str = Field(description="规则ID")
    severity: ValidationSeverity = Field(description="严重程度")
    message: str = Field(description="问题描述")

    # 问题位置
    field_path: Optional[str] = Field(default=None, description="字段路径")
    actual_value: Optional[Any] = Field(default=None, description="实际值")
    expected_value: Optional[Any] = Field(default=None, description="期望值")

    # 修复建议
    suggestion: Optional[str] = Field(default=None, description="修复建议")


class ValidationResult(BaseModel):
    """验证结果"""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    validation_id: str = Field(description="验证ID")
    target_id: str = Field(description="目标ID（工具执行ID或代码ID）")

    # 验证结果
    passed: bool = Field(description="是否通过验证")
    issues: list[ValidationIssue] = Field(default_factory=list, description="发现的问题")

    # 统计
    total_rules: int = Field(description="总规则数")
    passed_rules: int = Field(description="通过的规则数")
    failed_rules: int = Field(description="失败的规则数")

    # 严重程度统计
    critical_count: int = Field(default=0, description="严重错误数")
    error_count: int = Field(default=0, description="错误数")
    warning_count: int = Field(default=0, description="警告数")
    info_count: int = Field(default=0, description="信息数")

    # 元数据
    validated_at: datetime = Field(default_factory=datetime.now, description="验证时间")
    validation_time_ms: int = Field(default=0, description="验证耗时（毫秒）")

    @property
    def pass_rate(self) -> float:
        """通过率"""
        if self.total_rules == 0:
            return 0.0
        return self.passed_rules / self.total_rules

    @property
    def has_critical_issues(self) -> bool:
        """是否有严重问题"""
        return self.critical_count > 0


class FeedbackEntry(BaseModel):
    """反馈条目"""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    feedback_id: str = Field(description="反馈ID")
    target_id: str = Field(description="目标ID")
    feedback_type: FeedbackType = Field(description="反馈类型")

    # 反馈内容
    rating: Optional[float] = Field(default=None, ge=0.0, le=5.0, description="评分（0-5）")
    comment: Optional[str] = Field(default=None, description="评论")
    tags: list[str] = Field(default_factory=list, description="标签")

    # 具体问题
    issues: list[str] = Field(default_factory=list, description="发现的问题")
    suggestions: list[str] = Field(default_factory=list, description="改进建议")

    # 来源
    source: str = Field(default="user", description="反馈来源（user/system）")
    user_id: Optional[str] = Field(default=None, description="用户ID")

    # 元数据
    created_at: datetime = Field(default_factory=datetime.now, description="创建时间")
    metadata: dict[str, Any] = Field(default_factory=dict, description="元数据")


class QualityMetrics(BaseModel):
    """质量指标"""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    target_id: str = Field(description="目标ID")

    # 核心指标
    correctness_score: float = Field(ge=0.0, le=1.0, description="正确性评分")
    completeness_score: float = Field(ge=0.0, le=1.0, description="完整性评分")
    efficiency_score: float = Field(ge=0.0, le=1.0, description="效率评分")
    reliability_score: float = Field(ge=0.0, le=1.0, description="可靠性评分")

    # 综合评分
    overall_score: float = Field(ge=0.0, le=1.0, description="综合评分")
    quality_level: QualityLevel = Field(description="质量等级")

    # 详细指标
    execution_time_ms: int = Field(default=0, description="执行时间")
    error_count: int = Field(default=0, description="错误数")
    warning_count: int = Field(default=0, description="警告数")
    retry_count: int = Field(default=0, description="重试次数")

    # 用户反馈
    user_rating: Optional[float] = Field(default=None, description="用户评分")
    feedback_count: int = Field(default=0, description="反馈数量")

    # 元数据
    calculated_at: datetime = Field(default_factory=datetime.now, description="计算时间")

    @property
    def is_acceptable(self) -> bool:
        """是否可接受"""
        return self.overall_score >= 0.5 and self.quality_level not in (
            QualityLevel.POOR,
            QualityLevel.VERY_POOR,
        )


class ImprovementSuggestion(BaseModel):
    """改进建议"""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    suggestion_id: str = Field(description="建议ID")
    target_id: str = Field(description="目标ID")

    # 建议内容
    category: str = Field(description="建议类别")
    priority: str = Field(description="优先级（high/medium/low）")
    title: str = Field(description="建议标题")
    description: str = Field(description="详细描述")

    # 预期效果
    expected_improvement: str = Field(description="预期改进效果")
    estimated_effort: str = Field(description="预估工作量")

    # 实施方案
    action_items: list[str] = Field(default_factory=list, description="行动项")

    # 元数据
    created_at: datetime = Field(default_factory=datetime.now, description="创建时间")
    applied: bool = Field(default=False, description="是否已应用")


class ValidationReport(BaseModel):
    """验证报告"""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    report_id: str = Field(description="报告ID")
    target_id: str = Field(description="目标ID")

    # 验证结果
    validation_result: ValidationResult = Field(description="验证结果")
    quality_metrics: QualityMetrics = Field(description="质量指标")

    # 反馈
    feedback_entries: list[FeedbackEntry] = Field(
        default_factory=list,
        description="反馈条目"
    )

    # 改进建议
    improvement_suggestions: list[ImprovementSuggestion] = Field(
        default_factory=list,
        description="改进建议"
    )

    # 总结
    summary: str = Field(description="总结")
    recommendation: str = Field(description="建议")

    # 元数据
    generated_at: datetime = Field(default_factory=datetime.now, description="生成时间")


class FeedbackStatistics(BaseModel):
    """反馈统计"""
    model_config = ConfigDict(arbitrary_types_allowed=True)

    # 统计周期
    start_time: datetime = Field(description="开始时间")
    end_time: datetime = Field(description="结束时间")

    # 反馈统计
    total_feedback: int = Field(description="总反馈数")
    positive_feedback: int = Field(description="正面反馈数")
    negative_feedback: int = Field(description="负面反馈数")
    neutral_feedback: int = Field(description="中性反馈数")

    # 评分统计
    average_rating: float = Field(description="平均评分")
    rating_distribution: dict[str, int] = Field(
        default_factory=dict,
        description="评分分布"
    )

    # 质量统计
    average_quality_score: float = Field(description="平均质量分数")
    quality_distribution: dict[str, int] = Field(
        default_factory=dict,
        description="质量分布"
    )

    # 问题统计
    common_issues: list[tuple[str, int]] = Field(
        default_factory=list,
        description="常见问题及出现次数"
    )
    common_suggestions: list[tuple[str, int]] = Field(
        default_factory=list,
        description="常见建议及出现次数"
    )

    @property
    def positive_rate(self) -> float:
        """正面反馈率"""
        if self.total_feedback == 0:
            return 0.0
        return self.positive_feedback / self.total_feedback

    @property
    def satisfaction_score(self) -> float:
        """满意度分数（0-1）"""
        return self.average_rating / 5.0
