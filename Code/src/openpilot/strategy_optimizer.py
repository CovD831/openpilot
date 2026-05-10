"""
策略优化器

基于反思结果生成和应用优化策略。
"""

import uuid
from collections import defaultdict
from datetime import datetime
from typing import Any, Optional

from openpilot.memory_models import MemoryRecord, MemoryType
from openpilot.memory_store import MemoryStore
from openpilot.reflection_models import (
    LearningRecord,
    OptimizationResult,
    OptimizationStatistics,
    OptimizationStrategy,
    OptimizationTarget,
    PerformanceMetrics,
    ReflectionEntry,
    ReflectionReport,
    ReflectionType,
    StrategyType,
)


class StrategyOptimizer:
    """策略优化器"""

    def __init__(self, memory_store: Optional[MemoryStore] = None):
        """
        初始化策略优化器

        Args:
            memory_store: 记忆存储（可选）
        """
        self._strategies: dict[str, OptimizationStrategy] = {}
        self._optimization_results: list[OptimizationResult] = []
        self._memory_store = memory_store

    def generate_optimization_strategies(
        self,
        reflections: list[ReflectionEntry],
    ) -> list[OptimizationStrategy]:
        """
        基于反思生成优化策略

        Args:
            reflections: 反思条目列表

        Returns:
            list[OptimizationStrategy]: 优化策略列表
        """
        strategies = []

        # 分析失败反思，生成可靠性优化策略
        failure_reflections = [
            r for r in reflections if r.reflection_type == ReflectionType.FAILURE
        ]
        if failure_reflections:
            reliability_strategy = self._generate_reliability_strategy(
                failure_reflections
            )
            if reliability_strategy:
                strategies.append(reliability_strategy)

        # 分析改进反思，生成效率优化策略
        improvement_reflections = [
            r for r in reflections if r.reflection_type == ReflectionType.IMPROVEMENT
        ]
        if improvement_reflections:
            efficiency_strategy = self._generate_efficiency_strategy(
                improvement_reflections
            )
            if efficiency_strategy:
                strategies.append(efficiency_strategy)

        # 分析成功反思，生成最佳实践策略
        success_reflections = [
            r for r in reflections if r.reflection_type == ReflectionType.SUCCESS
        ]
        if success_reflections:
            best_practice_strategy = self._generate_best_practice_strategy(
                success_reflections
            )
            if best_practice_strategy:
                strategies.append(best_practice_strategy)

        # 分析工具使用模式，生成工具选择策略
        tool_strategy = self._generate_tool_selection_strategy(reflections)
        if tool_strategy:
            strategies.append(tool_strategy)

        # 保存策略
        for strategy in strategies:
            self._strategies[strategy.strategy_id] = strategy

        return strategies

    def apply_strategy(
        self,
        strategy_id: str,
        target_id: str,
        before_metrics: PerformanceMetrics,
    ) -> OptimizationResult:
        """
        应用优化策略

        Args:
            strategy_id: 策略ID
            target_id: 目标ID
            before_metrics: 优化前指标

        Returns:
            OptimizationResult: 优化结果
        """
        strategy = self._strategies.get(strategy_id)
        if not strategy:
            raise ValueError(f"策略不存在: {strategy_id}")

        # 模拟应用策略（实际应用需要具体实现）
        after_metrics = self._simulate_strategy_application(strategy, before_metrics)

        # 计算改进
        improvement = self._calculate_improvement(before_metrics, after_metrics)

        # 创建优化结果
        result = OptimizationResult(
            optimization_id=f"opt_{uuid.uuid4().hex[:8]}",
            strategy_id=strategy_id,
            target_id=target_id,
            before_metrics=before_metrics,
            after_metrics=after_metrics,
            improvement_percentage=improvement["overall"],
            improvement_details=improvement,
            success=improvement["overall"] > 0,
            actual_impact=improvement["overall"] / 100.0,
            side_effects=[],
        )

        # 更新策略统计
        strategy.application_count += 1
        strategy.last_applied_at = datetime.now()

        # 保存结果
        self._optimization_results.append(result)

        return result

    def update_memory_from_reflections(
        self,
        reflections: list[ReflectionEntry],
        learning_records: list[LearningRecord],
    ) -> list[MemoryRecord]:
        """
        从反思更新记忆系统

        Args:
            reflections: 反思条目列表
            learning_records: 学习记录列表

        Returns:
            list[MemoryRecord]: 创建的记忆记录
        """
        if not self._memory_store:
            return []

        memory_records = []

        # 从成功反思创建技能记忆
        success_reflections = [
            r for r in reflections if r.reflection_type == ReflectionType.SUCCESS
        ]
        for reflection in success_reflections:
            if reflection.confidence >= 0.7:
                memory = self._create_skill_memory_from_reflection(reflection)
                if memory:
                    self._memory_store.save(memory)
                    memory_records.append(memory)

        # 从失败反思创建长期记忆（教训）
        failure_reflections = [
            r for r in reflections if r.reflection_type == ReflectionType.FAILURE
        ]
        for reflection in failure_reflections:
            memory = self._create_lesson_memory_from_reflection(reflection)
            if memory:
                self._memory_store.save(memory)
                memory_records.append(memory)

        # 从学习记录创建技能记忆
        for record in learning_records:
            if record.effectiveness_score >= 0.6:
                memory = self._create_skill_memory_from_learning(record)
                if memory:
                    self._memory_store.save(memory)
                    memory_records.append(memory)

        return memory_records

    def generate_reflection_report(
        self,
        reflections: list[ReflectionEntry],
        learning_records: list[LearningRecord],
        start_time: datetime,
        end_time: datetime,
    ) -> ReflectionReport:
        """
        生成反思报告

        Args:
            reflections: 反思条目列表
            learning_records: 学习记录列表
            start_time: 开始时间
            end_time: 结束时间

        Returns:
            ReflectionReport: 反思报告
        """
        report_id = f"report_{uuid.uuid4().hex[:8]}"

        # 统计反思类型
        success_count = len(
            [r for r in reflections if r.reflection_type == ReflectionType.SUCCESS]
        )
        failure_count = len(
            [r for r in reflections if r.reflection_type == ReflectionType.FAILURE]
        )
        improvement_count = len(
            [r for r in reflections if r.reflection_type == ReflectionType.IMPROVEMENT]
        )

        # 提取关键发现
        key_findings = self._extract_key_findings(reflections)

        # 识别常见模式
        common_patterns = self._identify_common_patterns(reflections)

        # 识别重复问题
        recurring_issues = self._identify_recurring_issues(reflections)

        # 生成优化策略
        optimization_strategies = self.generate_optimization_strategies(reflections)

        # 生成优先行动
        priority_actions = self._generate_priority_actions(
            reflections, optimization_strategies
        )

        report = ReflectionReport(
            report_id=report_id,
            report_type="periodic",
            start_time=start_time,
            end_time=end_time,
            reflections=reflections,
            total_reflections=len(reflections),
            success_reflections=success_count,
            failure_reflections=failure_count,
            improvement_reflections=improvement_count,
            key_findings=key_findings,
            common_patterns=common_patterns,
            recurring_issues=recurring_issues,
            optimization_strategies=optimization_strategies,
            priority_actions=priority_actions,
            learning_records=learning_records,
        )

        return report

    def get_optimization_statistics(
        self,
        start_time: datetime,
        end_time: datetime,
    ) -> OptimizationStatistics:
        """
        获取优化统计

        Args:
            start_time: 开始时间
            end_time: 结束时间

        Returns:
            OptimizationStatistics: 优化统计
        """
        # 筛选时间范围内的优化结果
        results = [
            r
            for r in self._optimization_results
            if start_time <= r.optimized_at <= end_time
        ]

        if not results:
            return OptimizationStatistics(
                start_time=start_time,
                end_time=end_time,
                total_optimizations=0,
                successful_optimizations=0,
                failed_optimizations=0,
                average_improvement=0.0,
                best_improvement=0.0,
                worst_improvement=0.0,
                strategy_usage={},
                strategy_success_rate={},
                total_learning_records=0,
                applied_learning_records=0,
                validated_learning_records=0,
                performance_trend=[],
            )

        # 统计优化次数
        total = len(results)
        successful = len([r for r in results if r.success])
        failed = total - successful

        # 计算改进统计
        improvements = [r.improvement_percentage for r in results]
        avg_improvement = sum(improvements) / len(improvements)
        best_improvement = max(improvements)
        worst_improvement = min(improvements)

        # 统计策略使用
        strategy_usage = defaultdict(int)
        strategy_successes = defaultdict(int)
        for result in results:
            strategy_usage[result.strategy_id] += 1
            if result.success:
                strategy_successes[result.strategy_id] += 1

        # 计算策略成功率
        strategy_success_rate = {
            sid: strategy_successes[sid] / count
            for sid, count in strategy_usage.items()
        }

        # 性能趋势
        performance_trend = [r.improvement_percentage for r in results]

        return OptimizationStatistics(
            start_time=start_time,
            end_time=end_time,
            total_optimizations=total,
            successful_optimizations=successful,
            failed_optimizations=failed,
            average_improvement=avg_improvement,
            best_improvement=best_improvement,
            worst_improvement=worst_improvement,
            strategy_usage=dict(strategy_usage),
            strategy_success_rate=strategy_success_rate,
            total_learning_records=0,
            applied_learning_records=0,
            validated_learning_records=0,
            performance_trend=performance_trend,
        )

    # 私有辅助方法

    def _generate_reliability_strategy(
        self,
        reflections: list[ReflectionEntry],
    ) -> Optional[OptimizationStrategy]:
        """生成可靠性优化策略"""
        if not reflections:
            return None

        # 分析失败原因
        all_problems = []
        all_causes = []
        for reflection in reflections:
            all_problems.extend(reflection.problems_identified)
            all_causes.extend(reflection.root_causes)

        if not all_problems:
            return None

        strategy_id = f"strategy_{uuid.uuid4().hex[:8]}"

        return OptimizationStrategy(
            strategy_id=strategy_id,
            strategy_type=StrategyType.RETRY,
            optimization_target=OptimizationTarget.RELIABILITY,
            name="增强错误处理和重试机制",
            description="基于失败案例分析，改进错误处理和重试策略",
            parameters={
                "max_retries": 3,
                "retry_delay_seconds": 1,
                "exponential_backoff": True,
            },
            applicable_conditions=[
                "执行失败",
                "网络错误",
                "超时错误",
            ],
            constraints=["不适用于逻辑错误", "不适用于权限错误"],
            expected_improvement="减少临时性失败，提高成功率",
            expected_impact=0.3,
            implementation_steps=[
                "识别可重试的错误类型",
                "实现指数退避重试",
                "添加详细错误日志",
                "设置合理的超时时间",
            ],
            estimated_effort="medium",
            validation_criteria=[
                "成功率提升 > 20%",
                "临时性失败减少 > 50%",
            ],
            success_metrics=["success_rate", "retry_rate"],
            priority=8,
        )

    def _generate_efficiency_strategy(
        self,
        reflections: list[ReflectionEntry],
    ) -> Optional[OptimizationStrategy]:
        """生成效率优化策略"""
        if not reflections:
            return None

        # 分析性能问题
        slow_executions = [
            r for r in reflections if r.context.get("duration_seconds", 0) > 10
        ]

        if not slow_executions:
            return None

        strategy_id = f"strategy_{uuid.uuid4().hex[:8]}"

        return OptimizationStrategy(
            strategy_id=strategy_id,
            strategy_type=StrategyType.EXECUTION,
            optimization_target=OptimizationTarget.EFFICIENCY,
            name="优化执行效率",
            description="减少执行时间，提高响应速度",
            parameters={
                "enable_caching": True,
                "parallel_execution": True,
                "timeout_seconds": 30,
            },
            applicable_conditions=[
                "执行时间 > 10秒",
                "可并行执行",
                "结果可缓存",
            ],
            constraints=["不影响正确性", "不增加资源消耗"],
            expected_improvement="执行时间减少 30-50%",
            expected_impact=0.4,
            implementation_steps=[
                "识别性能瓶颈",
                "启用结果缓存",
                "实现并行执行",
                "优化算法复杂度",
            ],
            estimated_effort="high",
            validation_criteria=[
                "平均执行时间减少 > 30%",
                "P95 延迟降低 > 40%",
            ],
            success_metrics=["execution_time_ms", "throughput"],
            priority=7,
        )

    def _generate_best_practice_strategy(
        self,
        reflections: list[ReflectionEntry],
    ) -> Optional[OptimizationStrategy]:
        """生成最佳实践策略"""
        if not reflections:
            return None

        # 提取成功模式
        all_insights = []
        for reflection in reflections:
            all_insights.extend(reflection.insights)

        if not all_insights:
            return None

        strategy_id = f"strategy_{uuid.uuid4().hex[:8]}"

        return OptimizationStrategy(
            strategy_id=strategy_id,
            strategy_type=StrategyType.TOOL_SELECTION,
            optimization_target=OptimizationTarget.ACCURACY,
            name="应用成功模式",
            description="复用成功案例的最佳实践",
            parameters={
                "prefer_proven_tools": True,
                "use_successful_patterns": True,
            },
            applicable_conditions=[
                "相似任务类型",
                "相同工具可用",
            ],
            constraints=["不盲目复用", "需要验证适用性"],
            expected_improvement="提高首次成功率",
            expected_impact=0.25,
            implementation_steps=[
                "识别成功模式",
                "提取可复用要素",
                "建立模式库",
                "自动匹配应用",
            ],
            estimated_effort="medium",
            validation_criteria=[
                "首次成功率提升 > 15%",
                "用户满意度提升",
            ],
            success_metrics=["success_rate", "user_satisfaction"],
            priority=6,
        )

    def _generate_tool_selection_strategy(
        self,
        reflections: list[ReflectionEntry],
    ) -> Optional[OptimizationStrategy]:
        """生成工具选择策略"""
        # 分析工具使用情况
        tool_performance = defaultdict(list)
        for reflection in reflections:
            tool_name = reflection.context.get("tool_name")
            if tool_name:
                success = reflection.context.get("success", False)
                quality = reflection.context.get("quality_score", 0.0)
                tool_performance[tool_name].append((success, quality))

        if not tool_performance:
            return None

        # 计算工具评分
        tool_scores = {}
        for tool, performances in tool_performance.items():
            success_rate = sum(1 for s, _ in performances if s) / len(performances)
            avg_quality = sum(q for _, q in performances) / len(performances)
            tool_scores[tool] = (success_rate + avg_quality) / 2

        strategy_id = f"strategy_{uuid.uuid4().hex[:8]}"

        return OptimizationStrategy(
            strategy_id=strategy_id,
            strategy_type=StrategyType.TOOL_SELECTION,
            optimization_target=OptimizationTarget.ACCURACY,
            name="优化工具选择",
            description="基于历史表现选择最佳工具",
            parameters={
                "tool_scores": tool_scores,
                "min_score_threshold": 0.6,
            },
            applicable_conditions=[
                "多个工具可选",
                "有历史数据",
            ],
            constraints=["保持工具多样性", "定期重新评估"],
            expected_improvement="提高工具选择准确性",
            expected_impact=0.2,
            implementation_steps=[
                "收集工具使用数据",
                "计算工具评分",
                "更新选择策略",
                "监控效果",
            ],
            estimated_effort="low",
            validation_criteria=[
                "工具选择准确率提升 > 10%",
                "整体成功率提升",
            ],
            success_metrics=["tool_selection_accuracy", "success_rate"],
            priority=5,
        )

    def _simulate_strategy_application(
        self,
        strategy: OptimizationStrategy,
        before_metrics: PerformanceMetrics,
    ) -> PerformanceMetrics:
        """模拟策略应用（实际应用需要具体实现）"""
        # 根据策略类型和预期影响模拟改进
        impact = strategy.expected_impact

        after_metrics = PerformanceMetrics(
            target_id=before_metrics.target_id,
            metric_type=before_metrics.metric_type,
            execution_time_ms=int(before_metrics.execution_time_ms * (1 - impact * 0.5)),
            total_time_ms=int(before_metrics.total_time_ms * (1 - impact * 0.5)),
            wait_time_ms=before_metrics.wait_time_ms,
            cpu_usage_percent=before_metrics.cpu_usage_percent,
            memory_usage_mb=before_metrics.memory_usage_mb,
            disk_io_mb=before_metrics.disk_io_mb,
            network_io_mb=before_metrics.network_io_mb,
            success_rate=min(1.0, before_metrics.success_rate + impact * 0.3),
            error_rate=max(0.0, before_metrics.error_rate - impact * 0.3),
            retry_rate=max(0.0, before_metrics.retry_rate - impact * 0.2),
            throughput=before_metrics.throughput * (1 + impact * 0.4),
            requests_per_second=before_metrics.requests_per_second * (1 + impact * 0.4),
            sample_count=before_metrics.sample_count,
            measurement_period_seconds=before_metrics.measurement_period_seconds,
        )

        return after_metrics

    def _calculate_improvement(
        self,
        before: PerformanceMetrics,
        after: PerformanceMetrics,
    ) -> dict[str, float]:
        """计算改进百分比"""
        improvements = {}

        # 执行时间改进（越小越好）
        if before.execution_time_ms > 0:
            time_improvement = (
                (before.execution_time_ms - after.execution_time_ms)
                / before.execution_time_ms
                * 100
            )
            improvements["execution_time"] = time_improvement

        # 成功率改进（越大越好）
        if before.success_rate < 1.0:
            success_improvement = (
                (after.success_rate - before.success_rate) / (1.0 - before.success_rate) * 100
            )
            improvements["success_rate"] = success_improvement

        # 错误率改进（越小越好）
        if before.error_rate > 0:
            error_improvement = (
                (before.error_rate - after.error_rate) / before.error_rate * 100
            )
            improvements["error_rate"] = error_improvement

        # 吞吐量改进（越大越好）
        if before.throughput > 0:
            throughput_improvement = (
                (after.throughput - before.throughput) / before.throughput * 100
            )
            improvements["throughput"] = throughput_improvement

        # 计算总体改进
        if improvements:
            improvements["overall"] = sum(improvements.values()) / len(improvements)
        else:
            improvements["overall"] = 0.0

        return improvements

    def _create_skill_memory_from_reflection(
        self,
        reflection: ReflectionEntry,
    ) -> Optional[MemoryRecord]:
        """从反思创建技能记忆"""
        if not reflection.insights:
            return None

        memory_id = f"mem_{uuid.uuid4().hex[:8]}"
        content = f"成功经验: {reflection.analysis}\n洞察: {', '.join(reflection.insights)}"

        return MemoryRecord(
            id=memory_id,
            memory_type=MemoryType.SKILL,
            content=content,
            tags=[
                reflection.context.get("tool_name", "unknown"),
                "success_pattern",
                reflection.target_type,
            ],
            confidence=reflection.confidence,
            metadata={
                "reflection_id": reflection.reflection_id,
                "insights": reflection.insights,
                "lessons": reflection.lessons_learned,
            },
        )

    def _create_lesson_memory_from_reflection(
        self,
        reflection: ReflectionEntry,
    ) -> Optional[MemoryRecord]:
        """从反思创建教训记忆"""
        if not reflection.problems_identified:
            return None

        memory_id = f"mem_{uuid.uuid4().hex[:8]}"
        content = f"失败教训: {reflection.analysis}\n问题: {', '.join(reflection.problems_identified)}\n原因: {', '.join(reflection.root_causes)}"

        return MemoryRecord(
            id=memory_id,
            memory_type=MemoryType.LONG_TERM,
            content=content,
            tags=[
                reflection.context.get("tool_name", "unknown"),
                "failure_lesson",
                reflection.target_type,
            ],
            confidence=reflection.confidence,
            metadata={
                "reflection_id": reflection.reflection_id,
                "problems": reflection.problems_identified,
                "root_causes": reflection.root_causes,
            },
        )

    def _create_skill_memory_from_learning(
        self,
        record: LearningRecord,
    ) -> Optional[MemoryRecord]:
        """从学习记录创建技能记忆"""
        if not record.key_takeaways:
            return None

        memory_id = f"mem_{uuid.uuid4().hex[:8]}"
        content = f"学习内容: {record.content}\n关键要点: {', '.join(record.key_takeaways)}"

        return MemoryRecord(
            id=memory_id,
            memory_type=MemoryType.SKILL,
            content=content,
            tags=[
                record.category,
                record.topic,
                "learned_skill",
            ],
            confidence=record.confidence,
            metadata={
                "learning_record_id": record.record_id,
                "key_takeaways": record.key_takeaways,
                "best_practices": record.best_practices,
            },
        )

    def _extract_key_findings(
        self,
        reflections: list[ReflectionEntry],
    ) -> list[str]:
        """提取关键发现"""
        findings = []

        # 高置信度的洞察
        high_confidence_insights = []
        for reflection in reflections:
            if reflection.confidence >= 0.8:
                high_confidence_insights.extend(reflection.insights)

        if high_confidence_insights:
            findings.append(
                f"发现 {len(high_confidence_insights)} 个高置信度洞察"
            )

        # 成功率统计
        success_count = len(
            [r for r in reflections if r.reflection_type == ReflectionType.SUCCESS]
        )
        if reflections:
            success_rate = success_count / len(reflections) * 100
            findings.append(f"整体成功率: {success_rate:.1f}%")

        return findings

    def _identify_common_patterns(
        self,
        reflections: list[ReflectionEntry],
    ) -> list[str]:
        """识别常见模式"""
        patterns = []

        # 分析工具使用模式
        tool_usage = defaultdict(int)
        for reflection in reflections:
            tool_name = reflection.context.get("tool_name")
            if tool_name:
                tool_usage[tool_name] += 1

        if tool_usage:
            most_used = max(tool_usage.items(), key=lambda x: x[1])
            patterns.append(f"最常用工具: {most_used[0]} (使用{most_used[1]}次)")

        return patterns

    def _identify_recurring_issues(
        self,
        reflections: list[ReflectionEntry],
    ) -> list[str]:
        """识别重复问题"""
        issues = []

        # 统计问题出现次数
        problem_counter = defaultdict(int)
        for reflection in reflections:
            for problem in reflection.problems_identified:
                problem_counter[problem] += 1

        # 找出重复问题（出现3次以上）
        for problem, count in problem_counter.items():
            if count >= 3:
                issues.append(f"{problem} (出现{count}次)")

        return issues

    def _generate_priority_actions(
        self,
        reflections: list[ReflectionEntry],
        strategies: list[OptimizationStrategy],
    ) -> list[str]:
        """生成优先行动"""
        actions = []

        # 从高优先级策略提取行动
        high_priority_strategies = sorted(
            strategies, key=lambda s: s.priority, reverse=True
        )[:3]

        for strategy in high_priority_strategies:
            if strategy.implementation_steps:
                actions.append(
                    f"{strategy.name}: {strategy.implementation_steps[0]}"
                )

        return actions

    def get_strategies(
        self,
        strategy_type: Optional[StrategyType] = None,
        enabled_only: bool = True,
    ) -> list[OptimizationStrategy]:
        """获取策略列表"""
        strategies = list(self._strategies.values())

        if strategy_type:
            strategies = [s for s in strategies if s.strategy_type == strategy_type]

        if enabled_only:
            strategies = [s for s in strategies if s.enabled]

        return strategies

    def get_optimization_results(
        self,
        strategy_id: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> list[OptimizationResult]:
        """获取优化结果"""
        results = self._optimization_results

        if strategy_id:
            results = [r for r in results if r.strategy_id == strategy_id]

        if limit:
            results = results[-limit:]

        return results
