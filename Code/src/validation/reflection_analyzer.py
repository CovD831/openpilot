"""
反思分析器

分析执行结果、识别问题、提取经验教训。
"""

import uuid
from collections import Counter
from typing import Any, Optional

from models.code_models import CodeExecutionResult
from models.executor_models import ExecutionResult
from models.reflection_models import (
    LearningRecord,
    LearningStatus,
    PerformanceMetrics,
    ReflectionEntry,
    ReflectionType,
)
from models.validation_models import QualityMetrics, ValidationResult


class ReflectionAnalyzer:
    """反思分析器"""

    def __init__(self):
        """初始化反思分析器"""
        self._reflections: list[ReflectionEntry] = []
        self._learning_records: list[LearningRecord] = []

    def analyze_execution_result(
        self,
        result: ExecutionResult,
        validation: Optional[ValidationResult] = None,
        quality_metrics: Optional[QualityMetrics] = None,
    ) -> ReflectionEntry:
        """
        分析工具执行结果

        Args:
            result: 执行结果
            validation: 验证结果
            quality_metrics: 质量指标

        Returns:
            ReflectionEntry: 反思条目
        """
        reflection_id = f"refl_{uuid.uuid4().hex[:8]}"

        # 确定反思类型
        if result.success and (quality_metrics is None or quality_metrics.overall_score >= 0.7):
            reflection_type = ReflectionType.SUCCESS
        elif not result.success:
            reflection_type = ReflectionType.FAILURE
        else:
            reflection_type = ReflectionType.IMPROVEMENT

        # 观察现象
        observation = self._observe_execution(result, validation, quality_metrics)

        # 分析结果
        analysis = self._analyze_execution(result, validation, quality_metrics)

        # 提取洞察
        insights = self._extract_insights(result, validation, quality_metrics)

        # 识别问题
        problems = self._identify_problems(result, validation, quality_metrics)
        root_causes = self._identify_root_causes(result, validation, quality_metrics)

        # 生成改进建议
        improvements = self._generate_improvements(result, validation, quality_metrics)
        actions = self._recommend_actions(result, validation, quality_metrics)

        # 提取经验教训
        lessons = self._extract_lessons(result, validation, quality_metrics)

        # 构建上下文
        context = {
            "tool_name": result.tool_name,
            "step_id": result.step_id,
            "duration_seconds": result.duration_seconds,
            "success": result.success,
        }

        if quality_metrics:
            context["quality_score"] = quality_metrics.overall_score
            context["quality_level"] = quality_metrics.quality_level.value

        reflection = ReflectionEntry(
            reflection_id=reflection_id,
            reflection_type=reflection_type,
            target_id=result.execution_id,
            target_type="execution",
            observation=observation,
            analysis=analysis,
            insights=insights,
            lessons_learned=lessons,
            problems_identified=problems,
            root_causes=root_causes,
            improvement_opportunities=improvements,
            recommended_actions=actions,
            context=context,
            confidence=self._calculate_confidence(result, validation, quality_metrics),
        )

        self._reflections.append(reflection)
        return reflection

    def analyze_code_execution_result(
        self,
        result: CodeExecutionResult,
        validation: Optional[ValidationResult] = None,
        quality_metrics: Optional[QualityMetrics] = None,
    ) -> ReflectionEntry:
        """
        分析代码执行结果

        Args:
            result: 代码执行结果
            validation: 验证结果
            quality_metrics: 质量指标

        Returns:
            ReflectionEntry: 反思条目
        """
        reflection_id = f"refl_{uuid.uuid4().hex[:8]}"

        # 确定反思类型
        if result.success and (quality_metrics is None or quality_metrics.overall_score >= 0.7):
            reflection_type = ReflectionType.SUCCESS
        elif not result.success:
            reflection_type = ReflectionType.FAILURE
        else:
            reflection_type = ReflectionType.IMPROVEMENT

        # 观察现象
        observation = self._observe_code_execution(result, validation, quality_metrics)

        # 分析结果
        analysis = self._analyze_code_execution(result, validation, quality_metrics)

        # 提取洞察
        insights = self._extract_code_insights(result, validation, quality_metrics)

        # 识别问题
        problems = self._identify_code_problems(result, validation, quality_metrics)
        root_causes = self._identify_code_root_causes(result, validation, quality_metrics)

        # 生成改进建议
        improvements = self._generate_code_improvements(result, validation, quality_metrics)
        actions = self._recommend_code_actions(result, validation, quality_metrics)

        # 提取经验教训
        lessons = self._extract_code_lessons(result, validation, quality_metrics)

        # 构建上下文
        context = {
            "code_id": result.code_id,
            "execution_time_ms": result.execution_time_ms,
            "success": result.success,
            "exit_code": result.exit_code,
        }

        if result.error_type:
            context["error_type"] = result.error_type

        if quality_metrics:
            context["quality_score"] = quality_metrics.overall_score
            context["quality_level"] = quality_metrics.quality_level.value

        reflection = ReflectionEntry(
            reflection_id=reflection_id,
            reflection_type=reflection_type,
            target_id=result.execution_id,
            target_type="code_execution",
            observation=observation,
            analysis=analysis,
            insights=insights,
            lessons_learned=lessons,
            problems_identified=problems,
            root_causes=root_causes,
            improvement_opportunities=improvements,
            recommended_actions=actions,
            context=context,
            confidence=self._calculate_code_confidence(result, validation, quality_metrics),
        )

        self._reflections.append(reflection)
        return reflection

    def identify_patterns(self, min_occurrences: int = 3) -> list[str]:
        """
        识别模式

        Args:
            min_occurrences: 最小出现次数

        Returns:
            list[str]: 识别的模式
        """
        patterns = []

        # 分析问题模式
        all_problems = []
        for reflection in self._reflections:
            all_problems.extend(reflection.problems_identified)

        problem_counter = Counter(all_problems)
        for problem, count in problem_counter.items():
            if count >= min_occurrences:
                patterns.append(f"重复问题: {problem} (出现{count}次)")

        # 分析成功模式
        success_reflections = [
            r for r in self._reflections if r.reflection_type == ReflectionType.SUCCESS
        ]

        if len(success_reflections) >= min_occurrences:
            common_insights = []
            for reflection in success_reflections:
                common_insights.extend(reflection.insights)

            insight_counter = Counter(common_insights)
            for insight, count in insight_counter.items():
                if count >= min_occurrences:
                    patterns.append(f"成功模式: {insight} (出现{count}次)")

        return patterns

    def create_learning_record(
        self,
        reflection: ReflectionEntry,
        topic: str,
        category: str,
    ) -> LearningRecord:
        """
        创建学习记录

        Args:
            reflection: 反思条目
            topic: 学习主题
            category: 学习类别

        Returns:
            LearningRecord: 学习记录
        """
        record_id = f"learn_{uuid.uuid4().hex[:8]}"

        # 提取关键要点
        key_takeaways = reflection.insights[:3]  # 取前3个洞察

        # 提取最佳实践
        best_practices = []
        if reflection.reflection_type == ReflectionType.SUCCESS:
            best_practices = reflection.recommended_actions[:2]

        # 确定适用场景
        applicable_scenarios = [
            f"类似于 {reflection.context.get('tool_name', 'unknown')} 的场景"
        ]

        record = LearningRecord(
            record_id=record_id,
            learning_status=LearningStatus.LEARNED,
            topic=topic,
            category=category,
            content=reflection.analysis,
            source_type="reflection",
            source_id=reflection.reflection_id,
            key_takeaways=key_takeaways,
            patterns_discovered=[],
            best_practices=best_practices,
            applicable_scenarios=applicable_scenarios,
            application_examples=[],
            validation_results=[],
            effectiveness_score=0.0,
            confidence=reflection.confidence,
        )

        self._learning_records.append(record)
        return record

    # 私有辅助方法 - 工具执行分析

    def _observe_execution(
        self,
        result: ExecutionResult,
        validation: Optional[ValidationResult],
        quality_metrics: Optional[QualityMetrics],
    ) -> str:
        """观察执行结果"""
        if result.success:
            return f"工具 {result.tool_name} 执行成功，耗时 {result.duration_seconds:.2f}秒"
        else:
            error_msg = result.error.error_message if result.error else "未知错误"
            return f"工具 {result.tool_name} 执行失败: {error_msg}"

    def _analyze_execution(
        self,
        result: ExecutionResult,
        validation: Optional[ValidationResult],
        quality_metrics: Optional[QualityMetrics],
    ) -> str:
        """分析执行结果"""
        if result.success:
            if quality_metrics and quality_metrics.overall_score >= 0.7:
                return "执行成功且质量良好，符合预期"
            else:
                return "执行成功但质量有待提高"
        else:
            return f"执行失败，需要分析失败原因并改进"

    def _extract_insights(
        self,
        result: ExecutionResult,
        validation: Optional[ValidationResult],
        quality_metrics: Optional[QualityMetrics],
    ) -> list[str]:
        """提取洞察"""
        insights = []

        if result.success:
            if result.duration_seconds < 1.0:
                insights.append("执行速度快，性能良好")

            if quality_metrics and quality_metrics.reliability_score >= 0.9:
                insights.append("可靠性高，适合生产环境")

        return insights

    def _identify_problems(
        self,
        result: ExecutionResult,
        validation: Optional[ValidationResult],
        quality_metrics: Optional[QualityMetrics],
    ) -> list[str]:
        """识别问题"""
        problems = []

        if not result.success:
            problems.append("执行失败")

        if result.duration_seconds > 30:
            problems.append("执行时间过长")

        if validation and not validation.passed:
            problems.append("验证未通过")

        if quality_metrics:
            if quality_metrics.correctness_score < 0.5:
                problems.append("正确性不足")
            if quality_metrics.efficiency_score < 0.5:
                problems.append("效率低下")

        return problems

    def _identify_root_causes(
        self,
        result: ExecutionResult,
        validation: Optional[ValidationResult],
        quality_metrics: Optional[QualityMetrics],
    ) -> list[str]:
        """识别根本原因"""
        causes = []

        if not result.success and result.error:
            causes.append(f"错误类型: {result.error.error_type}")

        if result.duration_seconds > 30:
            causes.append("可能存在性能瓶颈")

        return causes

    def _generate_improvements(
        self,
        result: ExecutionResult,
        validation: Optional[ValidationResult],
        quality_metrics: Optional[QualityMetrics],
    ) -> list[str]:
        """生成改进机会"""
        improvements = []

        if result.duration_seconds > 10:
            improvements.append("优化执行效率")

        if quality_metrics and quality_metrics.correctness_score < 0.7:
            improvements.append("提高输出正确性")

        return improvements

    def _recommend_actions(
        self,
        result: ExecutionResult,
        validation: Optional[ValidationResult],
        quality_metrics: Optional[QualityMetrics],
    ) -> list[str]:
        """推荐行动"""
        actions = []

        if not result.success:
            actions.append("分析错误日志并修复问题")

        if result.duration_seconds > 30:
            actions.append("进行性能分析和优化")

        return actions

    def _extract_lessons(
        self,
        result: ExecutionResult,
        validation: Optional[ValidationResult],
        quality_metrics: Optional[QualityMetrics],
    ) -> list[str]:
        """提取经验教训"""
        lessons = []

        if result.success and result.duration_seconds < 1.0:
            lessons.append("快速执行的工具更受欢迎")

        if not result.success:
            lessons.append("需要更好的错误处理机制")

        return lessons

    # 私有辅助方法 - 代码执行分析

    def _observe_code_execution(
        self,
        result: CodeExecutionResult,
        validation: Optional[ValidationResult],
        quality_metrics: Optional[QualityMetrics],
    ) -> str:
        """观察代码执行结果"""
        if result.success:
            return f"代码执行成功，耗时 {result.execution_time_ms}ms"
        else:
            return f"代码执行失败: {result.error_message or '未知错误'}"

    def _analyze_code_execution(
        self,
        result: CodeExecutionResult,
        validation: Optional[ValidationResult],
        quality_metrics: Optional[QualityMetrics],
    ) -> str:
        """分析代码执行结果"""
        if result.success:
            return "代码执行成功，逻辑正确"
        else:
            return f"代码执行失败，错误类型: {result.error_type}"

    def _extract_code_insights(
        self,
        result: CodeExecutionResult,
        validation: Optional[ValidationResult],
        quality_metrics: Optional[QualityMetrics],
    ) -> list[str]:
        """提取代码洞察"""
        insights = []

        if result.success and result.execution_time_ms < 100:
            insights.append("代码执行效率高")

        return insights

    def _identify_code_problems(
        self,
        result: CodeExecutionResult,
        validation: Optional[ValidationResult],
        quality_metrics: Optional[QualityMetrics],
    ) -> list[str]:
        """识别代码问题"""
        problems = []

        if not result.success:
            problems.append(f"代码错误: {result.error_type}")

        if result.execution_time_ms > 5000:
            problems.append("代码执行时间过长")

        return problems

    def _identify_code_root_causes(
        self,
        result: CodeExecutionResult,
        validation: Optional[ValidationResult],
        quality_metrics: Optional[QualityMetrics],
    ) -> list[str]:
        """识别代码根本原因"""
        causes = []

        if result.error_type:
            causes.append(f"错误类型: {result.error_type}")
            if result.error_line:
                causes.append(f"错误位置: 第{result.error_line}行")

        return causes

    def _generate_code_improvements(
        self,
        result: CodeExecutionResult,
        validation: Optional[ValidationResult],
        quality_metrics: Optional[QualityMetrics],
    ) -> list[str]:
        """生成代码改进机会"""
        improvements = []

        if result.execution_time_ms > 1000:
            improvements.append("优化代码性能")

        if not result.success:
            improvements.append("修复代码错误")

        return improvements

    def _recommend_code_actions(
        self,
        result: CodeExecutionResult,
        validation: Optional[ValidationResult],
        quality_metrics: Optional[QualityMetrics],
    ) -> list[str]:
        """推荐代码行动"""
        actions = []

        if not result.success:
            actions.append("检查代码逻辑并修复错误")

        if result.execution_time_ms > 5000:
            actions.append("分析性能瓶颈并优化")

        return actions

    def _extract_code_lessons(
        self,
        result: CodeExecutionResult,
        validation: Optional[ValidationResult],
        quality_metrics: Optional[QualityMetrics],
    ) -> list[str]:
        """提取代码经验教训"""
        lessons = []

        if not result.success and result.error_type == "SyntaxError":
            lessons.append("生成代码前需要更严格的语法检查")

        return lessons

    # 置信度计算

    def _calculate_confidence(
        self,
        result: ExecutionResult,
        validation: Optional[ValidationResult],
        quality_metrics: Optional[QualityMetrics],
    ) -> float:
        """计算置信度"""
        confidence = 0.5

        if result.success:
            confidence += 0.2

        if validation and validation.passed:
            confidence += 0.2

        if quality_metrics and quality_metrics.overall_score >= 0.7:
            confidence += 0.1

        return min(1.0, confidence)

    def _calculate_code_confidence(
        self,
        result: CodeExecutionResult,
        validation: Optional[ValidationResult],
        quality_metrics: Optional[QualityMetrics],
    ) -> float:
        """计算代码置信度"""
        confidence = 0.5

        if result.success:
            confidence += 0.2

        if validation and validation.passed:
            confidence += 0.2

        if quality_metrics and quality_metrics.overall_score >= 0.7:
            confidence += 0.1

        return min(1.0, confidence)

    def get_reflections(
        self,
        reflection_type: Optional[ReflectionType] = None,
        limit: Optional[int] = None,
    ) -> list[ReflectionEntry]:
        """获取反思条目"""
        reflections = self._reflections

        if reflection_type:
            reflections = [r for r in reflections if r.reflection_type == reflection_type]

        if limit:
            reflections = reflections[-limit:]

        return reflections

    def get_learning_records(
        self,
        status: Optional[LearningStatus] = None,
        limit: Optional[int] = None,
    ) -> list[LearningRecord]:
        """获取学习记录"""
        records = self._learning_records

        if status:
            records = [r for r in records if r.learning_status == status]

        if limit:
            records = records[-limit:]

        return records

    def get_stats(self) -> dict:
        """获取统计信息"""
        return {
            "total_reflections": len(self._reflections),
            "success_reflections": len(
                [r for r in self._reflections if r.reflection_type == ReflectionType.SUCCESS]
            ),
            "failure_reflections": len(
                [r for r in self._reflections if r.reflection_type == ReflectionType.FAILURE]
            ),
            "improvement_reflections": len(
                [r for r in self._reflections if r.reflection_type == ReflectionType.IMPROVEMENT]
            ),
            "total_learning_records": len(self._learning_records),
        }
