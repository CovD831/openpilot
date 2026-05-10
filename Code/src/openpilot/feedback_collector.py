"""
反馈收集器

收集用户反馈、自动评分、生成改进建议。
"""

import time
import uuid
from collections import Counter
from datetime import datetime, timedelta
from typing import Optional

from openpilot.validation_models import (
    FeedbackEntry,
    FeedbackStatistics,
    FeedbackType,
    ImprovementSuggestion,
    QualityMetrics,
    ValidationResult,
)


class FeedbackCollector:
    """反馈收集器"""

    def __init__(self):
        """初始化反馈收集器"""
        self._feedback_entries: list[FeedbackEntry] = []
        self._quality_metrics: dict[str, QualityMetrics] = {}

    def collect_feedback(
        self,
        target_id: str,
        feedback_type: FeedbackType,
        rating: Optional[float] = None,
        comment: Optional[str] = None,
        tags: Optional[list[str]] = None,
        issues: Optional[list[str]] = None,
        suggestions: Optional[list[str]] = None,
        source: str = "user",
        user_id: Optional[str] = None,
    ) -> FeedbackEntry:
        """
        收集反馈

        Args:
            target_id: 目标ID
            feedback_type: 反馈类型
            rating: 评分（0-5）
            comment: 评论
            tags: 标签
            issues: 发现的问题
            suggestions: 改进建议
            source: 反馈来源
            user_id: 用户ID

        Returns:
            FeedbackEntry: 反馈条目
        """
        feedback_id = f"fb_{uuid.uuid4().hex[:8]}"

        feedback = FeedbackEntry(
            feedback_id=feedback_id,
            target_id=target_id,
            feedback_type=feedback_type,
            rating=rating,
            comment=comment,
            tags=tags or [],
            issues=issues or [],
            suggestions=suggestions or [],
            source=source,
            user_id=user_id,
        )

        self._feedback_entries.append(feedback)
        return feedback

    def collect_automatic_feedback(
        self,
        target_id: str,
        quality_metrics: QualityMetrics,
        validation_result: ValidationResult,
    ) -> FeedbackEntry:
        """
        自动收集反馈（基于质量指标和验证结果）

        Args:
            target_id: 目标ID
            quality_metrics: 质量指标
            validation_result: 验证结果

        Returns:
            FeedbackEntry: 反馈条目
        """
        # 存储质量指标
        self._quality_metrics[target_id] = quality_metrics

        # 确定反馈类型
        if quality_metrics.overall_score >= 0.7:
            feedback_type = FeedbackType.POSITIVE
        elif quality_metrics.overall_score >= 0.5:
            feedback_type = FeedbackType.NEUTRAL
        else:
            feedback_type = FeedbackType.NEGATIVE

        # 收集问题
        issues = []
        if quality_metrics.correctness_score < 0.7:
            issues.append("正确性需要改进")
        if quality_metrics.completeness_score < 0.7:
            issues.append("完整性不足")
        if quality_metrics.efficiency_score < 0.5:
            issues.append("执行效率较低")
        if quality_metrics.reliability_score < 0.7:
            issues.append("可靠性有待提高")

        # 从验证结果中提取问题
        for issue in validation_result.issues:
            issues.append(issue.message)

        # 生成建议
        suggestions = self._generate_suggestions_from_metrics(quality_metrics)

        # 生成标签
        tags = [quality_metrics.quality_level.value]
        if quality_metrics.error_count > 0:
            tags.append("has_errors")
        if quality_metrics.warning_count > 0:
            tags.append("has_warnings")

        return self.collect_feedback(
            target_id=target_id,
            feedback_type=feedback_type,
            rating=quality_metrics.overall_score * 5,  # 转换为 0-5 评分
            comment=f"自动评估: {quality_metrics.quality_level.value}",
            tags=tags,
            issues=issues,
            suggestions=suggestions,
            source="system",
        )

    def generate_improvement_suggestions(
        self,
        target_id: str,
        quality_metrics: QualityMetrics,
        validation_result: ValidationResult,
    ) -> list[ImprovementSuggestion]:
        """
        生成改进建议

        Args:
            target_id: 目标ID
            quality_metrics: 质量指标
            validation_result: 验证结果

        Returns:
            list[ImprovementSuggestion]: 改进建议列表
        """
        suggestions = []

        # 1. 基于正确性的建议
        if quality_metrics.correctness_score < 0.7:
            suggestions.append(
                ImprovementSuggestion(
                    suggestion_id=f"sug_{uuid.uuid4().hex[:8]}",
                    target_id=target_id,
                    category="correctness",
                    priority="high",
                    title="提高输出正确性",
                    description=f"当前正确性评分为 {quality_metrics.correctness_score:.2f}，需要改进",
                    expected_improvement="提高输出准确性，减少错误",
                    estimated_effort="medium",
                    action_items=[
                        "检查输入数据的有效性",
                        "增加边界条件处理",
                        "添加更多的单元测试",
                    ],
                )
            )

        # 2. 基于完整性的建议
        if quality_metrics.completeness_score < 0.7:
            suggestions.append(
                ImprovementSuggestion(
                    suggestion_id=f"sug_{uuid.uuid4().hex[:8]}",
                    target_id=target_id,
                    category="completeness",
                    priority="medium",
                    title="提高输出完整性",
                    description=f"当前完整性评分为 {quality_metrics.completeness_score:.2f}",
                    expected_improvement="确保所有必需的输出都被生成",
                    estimated_effort="low",
                    action_items=[
                        "检查是否缺少必需的输出字段",
                        "确保所有分支都有返回值",
                    ],
                )
            )

        # 3. 基于效率的建议
        if quality_metrics.efficiency_score < 0.5:
            suggestions.append(
                ImprovementSuggestion(
                    suggestion_id=f"sug_{uuid.uuid4().hex[:8]}",
                    target_id=target_id,
                    category="efficiency",
                    priority="low",
                    title="优化执行效率",
                    description=f"执行时间为 {quality_metrics.execution_time_ms}ms，效率评分为 {quality_metrics.efficiency_score:.2f}",
                    expected_improvement="减少执行时间，提高响应速度",
                    estimated_effort="medium",
                    action_items=[
                        "分析性能瓶颈",
                        "优化算法复杂度",
                        "考虑使用缓存",
                    ],
                )
            )

        # 4. 基于可靠性的建议
        if quality_metrics.reliability_score < 0.7:
            suggestions.append(
                ImprovementSuggestion(
                    suggestion_id=f"sug_{uuid.uuid4().hex[:8]}",
                    target_id=target_id,
                    category="reliability",
                    priority="high",
                    title="提高系统可靠性",
                    description=f"可靠性评分为 {quality_metrics.reliability_score:.2f}，有 {quality_metrics.error_count} 个错误",
                    expected_improvement="减少错误和重试次数",
                    estimated_effort="high",
                    action_items=[
                        "增强错误处理",
                        "添加重试机制",
                        "改进输入验证",
                    ],
                )
            )

        # 5. 基于验证问题的建议
        if validation_result.critical_count > 0:
            suggestions.append(
                ImprovementSuggestion(
                    suggestion_id=f"sug_{uuid.uuid4().hex[:8]}",
                    target_id=target_id,
                    category="validation",
                    priority="critical",
                    title="修复严重验证问题",
                    description=f"发现 {validation_result.critical_count} 个严重问题",
                    expected_improvement="消除所有严重问题",
                    estimated_effort="high",
                    action_items=[
                        issue.message
                        for issue in validation_result.issues
                        if issue.severity.value == "critical"
                    ][:3],
                )
            )

        return suggestions

    def get_feedback_statistics(
        self,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> FeedbackStatistics:
        """
        获取反馈统计

        Args:
            start_time: 开始时间
            end_time: 结束时间

        Returns:
            FeedbackStatistics: 反馈统计
        """
        # 默认时间范围：最近 7 天
        if end_time is None:
            end_time = datetime.now()
        if start_time is None:
            start_time = end_time - timedelta(days=7)

        # 筛选时间范围内的反馈
        filtered_feedback = [
            fb
            for fb in self._feedback_entries
            if start_time <= fb.created_at <= end_time
        ]

        # 统计反馈类型
        total_feedback = len(filtered_feedback)
        positive_feedback = sum(
            1 for fb in filtered_feedback if fb.feedback_type == FeedbackType.POSITIVE
        )
        negative_feedback = sum(
            1 for fb in filtered_feedback if fb.feedback_type == FeedbackType.NEGATIVE
        )
        neutral_feedback = sum(
            1 for fb in filtered_feedback if fb.feedback_type == FeedbackType.NEUTRAL
        )

        # 统计评分
        ratings = [fb.rating for fb in filtered_feedback if fb.rating is not None]
        average_rating = sum(ratings) / len(ratings) if ratings else 0.0

        # 评分分布
        rating_distribution = {}
        for rating in ratings:
            key = f"{int(rating)}-{int(rating)+1}"
            rating_distribution[key] = rating_distribution.get(key, 0) + 1

        # 质量统计
        quality_scores = [
            metrics.overall_score
            for metrics in self._quality_metrics.values()
        ]
        average_quality_score = (
            sum(quality_scores) / len(quality_scores) if quality_scores else 0.0
        )

        # 质量分布
        quality_distribution = {}
        for metrics in self._quality_metrics.values():
            level = metrics.quality_level.value
            quality_distribution[level] = quality_distribution.get(level, 0) + 1

        # 常见问题
        all_issues = []
        for fb in filtered_feedback:
            all_issues.extend(fb.issues)
        issue_counter = Counter(all_issues)
        common_issues = issue_counter.most_common(10)

        # 常见建议
        all_suggestions = []
        for fb in filtered_feedback:
            all_suggestions.extend(fb.suggestions)
        suggestion_counter = Counter(all_suggestions)
        common_suggestions = suggestion_counter.most_common(10)

        return FeedbackStatistics(
            start_time=start_time,
            end_time=end_time,
            total_feedback=total_feedback,
            positive_feedback=positive_feedback,
            negative_feedback=negative_feedback,
            neutral_feedback=neutral_feedback,
            average_rating=average_rating,
            rating_distribution=rating_distribution,
            average_quality_score=average_quality_score,
            quality_distribution=quality_distribution,
            common_issues=common_issues,
            common_suggestions=common_suggestions,
        )

    def _generate_suggestions_from_metrics(
        self, quality_metrics: QualityMetrics
    ) -> list[str]:
        """从质量指标生成建议"""
        suggestions = []

        if quality_metrics.correctness_score < 0.7:
            suggestions.append("改进输出正确性")

        if quality_metrics.completeness_score < 0.7:
            suggestions.append("确保输出完整性")

        if quality_metrics.efficiency_score < 0.5:
            suggestions.append("优化执行效率")

        if quality_metrics.reliability_score < 0.7:
            suggestions.append("提高系统可靠性")

        if quality_metrics.error_count > 0:
            suggestions.append("修复错误")

        if quality_metrics.warning_count > 0:
            suggestions.append("处理警告")

        return suggestions

    def get_feedback_for_target(self, target_id: str) -> list[FeedbackEntry]:
        """获取特定目标的所有反馈"""
        return [fb for fb in self._feedback_entries if fb.target_id == target_id]

    def get_quality_metrics(self, target_id: str) -> Optional[QualityMetrics]:
        """获取特定目标的质量指标"""
        return self._quality_metrics.get(target_id)

    def get_stats(self) -> dict:
        """获取收集器统计"""
        return {
            "total_feedback": len(self._feedback_entries),
            "total_targets": len(self._quality_metrics),
            "positive_feedback": sum(
                1
                for fb in self._feedback_entries
                if fb.feedback_type == FeedbackType.POSITIVE
            ),
            "negative_feedback": sum(
                1
                for fb in self._feedback_entries
                if fb.feedback_type == FeedbackType.NEGATIVE
            ),
        }
