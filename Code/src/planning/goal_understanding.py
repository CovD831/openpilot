"""
目标理解增强模块

提供更智能的任务类型识别、资源推断和风险评估。
"""

from models.planner_models import TaskCard, TaskType, RiskLevel


class GoalUnderstandingEnhancer:
    """目标理解增强器"""

    def __init__(self):
        """初始化增强器"""
        pass

    def infer_resources_from_task_type(self, task_card: TaskCard) -> TaskCard:
        """
        根据任务类型推断所需资源

        Args:
            task_card: 任务卡片

        Returns:
            TaskCard: 增强后的任务卡片
        """
        # 如果已经有资源定义，不覆盖
        if task_card.required_resources:
            return task_card

        resources = set()

        # 基础资源：所有任务都可能需要LLM
        resources.add("llm")

        # 根据任务类型添加特定资源
        if task_card.task_type == TaskType.RESEARCH:
            resources.update(["web_search", "memory"])

        elif task_card.task_type == TaskType.DOCUMENT_SUMMARY:
            resources.update(["local_file", "memory"])

        elif task_card.task_type == TaskType.PLANNING:
            resources.update(["memory", "timeline", "task_log"])

        elif task_card.task_type == TaskType.FILE_WORKFLOW:
            resources.update(["local_file"])

        elif task_card.task_type == TaskType.CALENDAR_RELATED:
            resources.update(["calendar", "reminder_plan"])

        elif task_card.task_type == TaskType.COMMUNICATION:
            resources.update(["email"])

        elif task_card.task_type == TaskType.CODING:
            resources.update(["local_file", "python_runtime", "code_execution"])

        elif task_card.task_type == TaskType.DATA_ANALYSIS:
            # Phase 2: 数据分析需要文件读取、代码执行、可视化
            resources.update([
                "local_file",
                "python_runtime",
                "code_execution",
                "memory"
            ])

        elif task_card.task_type == TaskType.AUTOMATION:
            # Phase 2: 自动化需要代码执行、工具编排
            resources.update([
                "python_runtime",
                "code_execution",
                "tool_orchestration",
                "memory"
            ])

        task_card.required_resources = list(resources)
        return task_card

    def assess_risk_level(self, task_card: TaskCard) -> TaskCard:
        """
        评估任务风险等级

        Args:
            task_card: 任务卡片

        Returns:
            TaskCard: 更新风险等级后的任务卡片
        """
        # 如果已经明确设置了风险等级且不是MEDIUM，保持不变
        if task_card.risk_level != RiskLevel.MEDIUM:
            return task_card

        risk_score = 0

        # 基于任务类型评估风险
        high_risk_types = [
            TaskType.COMMUNICATION,  # 发送邮件等不可逆操作
            TaskType.AUTOMATION,  # 自动化脚本可能影响系统
        ]

        medium_risk_types = [
            TaskType.FILE_WORKFLOW,  # 文件操作有风险
            TaskType.CODING,  # 代码修改有风险
            TaskType.DATA_ANALYSIS,  # 数据处理可能出错
        ]

        low_risk_types = [
            TaskType.RESEARCH,  # 只读操作
            TaskType.DOCUMENT_SUMMARY,  # 只读操作
            TaskType.PLANNING,  # 规划操作
            TaskType.CALENDAR_RELATED,  # 日历操作相对安全
        ]

        if task_card.task_type in high_risk_types:
            risk_score += 2
        elif task_card.task_type in medium_risk_types:
            risk_score += 1
        elif task_card.task_type in low_risk_types:
            risk_score += 0

        # 基于资源需求评估风险
        high_risk_resources = ["email", "code_execution", "tool_orchestration"]
        medium_risk_resources = ["local_file", "python_runtime", "browser", "gui"]

        for resource in task_card.required_resources:
            if resource in high_risk_resources:
                risk_score += 1
            elif resource in medium_risk_resources:
                risk_score += 0.5

        # 基于关键词评估风险
        goal_lower = task_card.goal.lower()
        high_risk_keywords = [
            "删除", "delete", "remove", "发送", "send", "部署", "deploy",
            "修改", "modify", "更新", "update", "批量", "batch"
        ]

        for keyword in high_risk_keywords:
            if keyword in goal_lower:
                risk_score += 1
                break

        # 确定最终风险等级
        if risk_score >= 3:
            task_card.risk_level = RiskLevel.HIGH
        elif risk_score >= 1.5:
            task_card.risk_level = RiskLevel.MEDIUM
        else:
            task_card.risk_level = RiskLevel.LOW

        return task_card

    def enhance_task_card(self, task_card: TaskCard) -> TaskCard:
        """
        全面增强任务卡片

        Args:
            task_card: 原始任务卡片

        Returns:
            TaskCard: 增强后的任务卡片
        """
        # 推断资源
        task_card = self.infer_resources_from_task_type(task_card)

        # 评估风险
        task_card = self.assess_risk_level(task_card)

        # 确保有预期交付物
        if not task_card.expected_deliverables:
            task_card.expected_deliverables = self._infer_deliverables(task_card)

        return task_card

    def _infer_deliverables(self, task_card: TaskCard) -> list[str]:
        """推断预期交付物"""
        deliverables = []

        if task_card.task_type == TaskType.RESEARCH:
            deliverables = ["研究报告", "信息摘要"]

        elif task_card.task_type == TaskType.DOCUMENT_SUMMARY:
            deliverables = ["文档摘要"]

        elif task_card.task_type == TaskType.PLANNING:
            deliverables = ["任务树", "时间线", "提醒计划"]

        elif task_card.task_type == TaskType.FILE_WORKFLOW:
            deliverables = ["处理后的文件"]

        elif task_card.task_type == TaskType.CALENDAR_RELATED:
            deliverables = ["日程安排", "提醒"]

        elif task_card.task_type == TaskType.COMMUNICATION:
            deliverables = ["已发送的消息"]

        elif task_card.task_type == TaskType.CODING:
            deliverables = ["代码文件", "测试结果"]

        elif task_card.task_type == TaskType.DATA_ANALYSIS:
            deliverables = ["分析报告", "数据可视化", "统计结果"]

        elif task_card.task_type == TaskType.AUTOMATION:
            deliverables = ["自动化脚本", "执行日志"]

        else:
            deliverables = ["任务结果"]

        return deliverables

    def validate_and_normalize_resources(self, task_card: TaskCard) -> TaskCard:
        """
        验证和规范化资源标签

        Args:
            task_card: 任务卡片

        Returns:
            TaskCard: 规范化后的任务卡片
        """
        from models.planner_models import STANDARD_RESOURCES

        # 过滤掉不在标准资源列表中的资源
        valid_resources = [
            r for r in task_card.required_resources
            if r in STANDARD_RESOURCES
        ]

        # 去重
        task_card.required_resources = list(set(valid_resources))

        return task_card

    def suggest_constraints(self, task_card: TaskCard) -> list[str]:
        """
        根据任务类型建议约束条件

        Args:
            task_card: 任务卡片

        Returns:
            list[str]: 建议的约束条件
        """
        suggestions = []

        if task_card.task_type == TaskType.DATA_ANALYSIS:
            suggestions.extend([
                "确保数据文件格式正确",
                "检查数据完整性",
                "注意数据隐私保护"
            ])

        elif task_card.task_type == TaskType.AUTOMATION:
            suggestions.extend([
                "在测试环境中先验证",
                "设置执行超时时间",
                "记录详细执行日志"
            ])

        elif task_card.task_type == TaskType.COMMUNICATION:
            suggestions.extend([
                "确认收件人地址",
                "检查邮件内容",
                "避免敏感信息泄露"
            ])

        elif task_card.task_type == TaskType.FILE_WORKFLOW:
            suggestions.extend([
                "备份原始文件",
                "验证文件路径",
                "检查文件权限"
            ])

        elif task_card.task_type == TaskType.CODING:
            suggestions.extend([
                "遵循代码规范",
                "编写单元测试",
                "进行代码审查"
            ])

        return suggestions
