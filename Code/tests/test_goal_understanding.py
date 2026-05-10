"""
目标理解增强模块测试
"""

import pytest

from openpilot.goal_understanding import GoalUnderstandingEnhancer
from openpilot.planner import apply_task_type_fallback
from openpilot.planner_models import TaskCard, TaskType, RiskLevel


class TestTaskTypeFallback:
    """测试任务类型回退逻辑"""

    def test_data_analysis_keywords(self):
        """测试数据分析关键词识别"""
        task_card = TaskCard(
            goal="帮我分析这个CSV文件的销售数据",
            task_type=TaskType.UNKNOWN
        )

        result = apply_task_type_fallback(task_card, task_card.goal)

        assert result.task_type == TaskType.DATA_ANALYSIS

    def test_automation_keywords(self):
        """测试自动化关键词识别"""
        task_card = TaskCard(
            goal="写个脚本批量重命名文件",
            task_type=TaskType.UNKNOWN
        )

        result = apply_task_type_fallback(task_card, task_card.goal)

        assert result.task_type == TaskType.AUTOMATION

    def test_research_keywords(self):
        """测试研究关键词识别"""
        task_card = TaskCard(
            goal="研究一下Rust语言的内存管理机制",
            task_type=TaskType.UNKNOWN
        )

        result = apply_task_type_fallback(task_card, task_card.goal)

        assert result.task_type == TaskType.RESEARCH

    def test_coding_keywords(self):
        """测试编程关键词识别"""
        task_card = TaskCard(
            goal="修复登录页面的bug",
            task_type=TaskType.UNKNOWN
        )

        result = apply_task_type_fallback(task_card, task_card.goal)

        assert result.task_type == TaskType.CODING

    def test_planning_keywords(self):
        """测试规划关键词识别"""
        task_card = TaskCard(
            goal="制定下个月的项目计划",
            task_type=TaskType.UNKNOWN
        )

        result = apply_task_type_fallback(task_card, task_card.goal)

        assert result.task_type == TaskType.PLANNING

    def test_already_set_type_not_changed(self):
        """测试已设置的类型不会被改变"""
        task_card = TaskCard(
            goal="分析数据",
            task_type=TaskType.RESEARCH
        )

        result = apply_task_type_fallback(task_card, task_card.goal)

        assert result.task_type == TaskType.RESEARCH


class TestGoalUnderstandingEnhancer:
    """测试目标理解增强器"""

    def test_infer_resources_for_data_analysis(self):
        """测试数据分析任务的资源推断"""
        enhancer = GoalUnderstandingEnhancer()

        task_card = TaskCard(
            goal="分析销售数据",
            task_type=TaskType.DATA_ANALYSIS
        )

        result = enhancer.infer_resources_from_task_type(task_card)

        assert "llm" in result.required_resources
        assert "local_file" in result.required_resources
        assert "python_runtime" in result.required_resources
        assert "code_execution" in result.required_resources

    def test_infer_resources_for_automation(self):
        """测试自动化任务的资源推断"""
        enhancer = GoalUnderstandingEnhancer()

        task_card = TaskCard(
            goal="批量处理文件",
            task_type=TaskType.AUTOMATION
        )

        result = enhancer.infer_resources_from_task_type(task_card)

        assert "python_runtime" in result.required_resources
        assert "code_execution" in result.required_resources
        assert "tool_orchestration" in result.required_resources

    def test_infer_resources_for_research(self):
        """测试研究任务的资源推断"""
        enhancer = GoalUnderstandingEnhancer()

        task_card = TaskCard(
            goal="研究AI技术",
            task_type=TaskType.RESEARCH
        )

        result = enhancer.infer_resources_from_task_type(task_card)

        assert "web_search" in result.required_resources
        assert "memory" in result.required_resources

    def test_assess_risk_for_automation(self):
        """测试自动化任务的风险评估"""
        enhancer = GoalUnderstandingEnhancer()

        task_card = TaskCard(
            goal="批量删除临时文件",
            task_type=TaskType.AUTOMATION,
            required_resources=["code_execution", "tool_orchestration"]
        )

        result = enhancer.assess_risk_level(task_card)

        assert result.risk_level == RiskLevel.HIGH

    def test_assess_risk_for_research(self):
        """测试研究任务的风险评估"""
        enhancer = GoalUnderstandingEnhancer()

        task_card = TaskCard(
            goal="研究技术文档",
            task_type=TaskType.RESEARCH,
            required_resources=["web_search", "memory"]
        )

        result = enhancer.assess_risk_level(task_card)

        assert result.risk_level == RiskLevel.LOW

    def test_assess_risk_for_communication(self):
        """测试通信任务的风险评估"""
        enhancer = GoalUnderstandingEnhancer()

        task_card = TaskCard(
            goal="发送项目报告邮件",
            task_type=TaskType.COMMUNICATION,
            required_resources=["email"]
        )

        result = enhancer.assess_risk_level(task_card)

        assert result.risk_level == RiskLevel.HIGH

    def test_assess_risk_with_high_risk_keywords(self):
        """测试包含高风险关键词的任务"""
        enhancer = GoalUnderstandingEnhancer()

        task_card = TaskCard(
            goal="批量删除旧文件",
            task_type=TaskType.FILE_WORKFLOW,
            required_resources=["local_file"]
        )

        result = enhancer.assess_risk_level(task_card)

        # 包含"删除"和"批量"关键词，应该是高风险
        assert result.risk_level in [RiskLevel.MEDIUM, RiskLevel.HIGH]

    def test_enhance_task_card_complete(self):
        """测试完整的任务卡片增强"""
        enhancer = GoalUnderstandingEnhancer()

        task_card = TaskCard(
            goal="分析用户行为数据并生成报告",
            task_type=TaskType.DATA_ANALYSIS
        )

        result = enhancer.enhance_task_card(task_card)

        # 应该有资源
        assert len(result.required_resources) > 0
        assert "code_execution" in result.required_resources

        # 应该有风险等级
        assert result.risk_level in [RiskLevel.LOW, RiskLevel.MEDIUM, RiskLevel.HIGH]

        # 应该有交付物
        assert len(result.expected_deliverables) > 0

    def test_infer_deliverables_for_data_analysis(self):
        """测试数据分析任务的交付物推断"""
        enhancer = GoalUnderstandingEnhancer()

        task_card = TaskCard(
            goal="分析数据",
            task_type=TaskType.DATA_ANALYSIS
        )

        result = enhancer.enhance_task_card(task_card)

        assert "分析报告" in result.expected_deliverables
        assert "数据可视化" in result.expected_deliverables

    def test_infer_deliverables_for_automation(self):
        """测试自动化任务的交付物推断"""
        enhancer = GoalUnderstandingEnhancer()

        task_card = TaskCard(
            goal="自动化处理",
            task_type=TaskType.AUTOMATION
        )

        result = enhancer.enhance_task_card(task_card)

        assert "自动化脚本" in result.expected_deliverables
        assert "执行日志" in result.expected_deliverables

    def test_validate_and_normalize_resources(self):
        """测试资源验证和规范化"""
        enhancer = GoalUnderstandingEnhancer()

        task_card = TaskCard(
            goal="测试任务",
            task_type=TaskType.RESEARCH,
            required_resources=["llm", "web_search", "invalid_resource", "llm"]  # 包含无效和重复
        )

        result = enhancer.validate_and_normalize_resources(task_card)

        # 应该移除无效资源
        assert "invalid_resource" not in result.required_resources

        # 应该去重
        assert result.required_resources.count("llm") == 1

    def test_suggest_constraints_for_data_analysis(self):
        """测试数据分析任务的约束建议"""
        enhancer = GoalUnderstandingEnhancer()

        task_card = TaskCard(
            goal="分析数据",
            task_type=TaskType.DATA_ANALYSIS
        )

        suggestions = enhancer.suggest_constraints(task_card)

        assert len(suggestions) > 0
        assert any("数据" in s for s in suggestions)

    def test_suggest_constraints_for_automation(self):
        """测试自动化任务的约束建议"""
        enhancer = GoalUnderstandingEnhancer()

        task_card = TaskCard(
            goal="自动化脚本",
            task_type=TaskType.AUTOMATION
        )

        suggestions = enhancer.suggest_constraints(task_card)

        assert len(suggestions) > 0
        assert any("测试" in s or "日志" in s for s in suggestions)

    def test_existing_resources_not_overwritten(self):
        """测试已有资源不会被覆盖"""
        enhancer = GoalUnderstandingEnhancer()

        existing_resources = ["custom_resource", "llm"]
        task_card = TaskCard(
            goal="测试任务",
            task_type=TaskType.RESEARCH,
            required_resources=existing_resources.copy()
        )

        result = enhancer.infer_resources_from_task_type(task_card)

        # 已有资源应该保持不变
        assert result.required_resources == existing_resources


class TestIntegration:
    """集成测试"""

    def test_full_enhancement_pipeline(self):
        """测试完整的增强流程"""
        enhancer = GoalUnderstandingEnhancer()

        # 1. 创建原始任务卡片
        task_card = TaskCard(
            goal="分析sales_data.csv文件，生成月度销售报告",
            task_type=TaskType.UNKNOWN
        )

        # 2. 应用类型回退
        task_card = apply_task_type_fallback(task_card, task_card.goal)
        assert task_card.task_type == TaskType.DATA_ANALYSIS

        # 3. 增强任务卡片
        task_card = enhancer.enhance_task_card(task_card)

        # 验证结果
        assert task_card.task_type == TaskType.DATA_ANALYSIS
        assert len(task_card.required_resources) > 0
        assert "code_execution" in task_card.required_resources
        assert task_card.risk_level in [RiskLevel.LOW, RiskLevel.MEDIUM, RiskLevel.HIGH]
        assert len(task_card.expected_deliverables) > 0

        # 4. 验证和规范化
        task_card = enhancer.validate_and_normalize_resources(task_card)

        # 5. 获取约束建议
        suggestions = enhancer.suggest_constraints(task_card)
        assert len(suggestions) > 0

    def test_automation_task_full_flow(self):
        """测试自动化任务的完整流程"""
        enhancer = GoalUnderstandingEnhancer()

        task_card = TaskCard(
            goal="写个脚本批量转换图片格式",
            task_type=TaskType.UNKNOWN
        )

        # 类型识别
        task_card = apply_task_type_fallback(task_card, task_card.goal)
        assert task_card.task_type == TaskType.AUTOMATION

        # 增强
        task_card = enhancer.enhance_task_card(task_card)

        # 验证
        assert "tool_orchestration" in task_card.required_resources
        assert task_card.risk_level in [RiskLevel.MEDIUM, RiskLevel.HIGH]
        assert "自动化脚本" in task_card.expected_deliverables


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
