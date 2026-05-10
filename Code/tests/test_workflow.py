"""
测试工作流执行器
"""

import pytest
from unittest.mock import Mock, patch
from pathlib import Path

from openpilot.workflow_executor import WorkflowExecutor, WorkflowStage
from openpilot.planner_models import TaskCard, TaskType, RiskLevel, ExecutionPlan, PlanStep
from openpilot.memory_models import MemoryQueryResult


class TestWorkflowExecutor:
    """测试工作流执行器"""

    @pytest.fixture
    def mock_llm_client(self):
        """创建模拟LLM客户端"""
        return Mock()

    def test_workflow_stages_enum(self):
        """测试工作流阶段枚举"""
        assert WorkflowStage.GOAL_UNDERSTANDING == "goal_understanding"
        assert WorkflowStage.MEMORY_RETRIEVAL == "memory_retrieval"
        assert WorkflowStage.PLAN_GENERATION == "plan_generation"
        assert WorkflowStage.TOOL_ORCHESTRATION == "tool_orchestration"
        assert WorkflowStage.EXECUTION == "execution"
        assert WorkflowStage.VALIDATION == "validation"
        assert WorkflowStage.REFLECTION == "reflection"
        assert WorkflowStage.LOGGING == "logging"

    def test_executor_initialization(self, mock_llm_client):
        """测试执行器初始化"""
        executor = WorkflowExecutor(
            llm_client=mock_llm_client,
            dry_run=False,
            auto_approve=False,
        )

        assert executor.llm_client is not None
        assert executor.console is not None
        assert executor.goal_enhancer is not None
        assert executor.planner is not None
        assert executor.memory_store is not None
        assert executor.tool_registry is not None
        assert executor.orchestrator is not None
        assert executor.executor is not None
        assert executor.validator is not None
        assert executor.analyzer is not None
        assert executor.optimizer is not None
        assert executor.logger is not None

    def test_dry_run_mode(self, mock_llm_client):
        """测试仅规划模式"""
        executor = WorkflowExecutor(
            llm_client=mock_llm_client,
            dry_run=True,
            auto_approve=False,
        )
        assert executor.dry_run is True

    def test_auto_approve_mode(self, mock_llm_client):
        """测试自动批准模式"""
        executor = WorkflowExecutor(
            llm_client=mock_llm_client,
            dry_run=False,
            auto_approve=True,
        )
        assert executor.auto_approve is True

    def test_save_report_path(self, mock_llm_client, tmp_path):
        """测试报告保存路径"""
        report_file = tmp_path / "report.md"
        executor = WorkflowExecutor(
            llm_client=mock_llm_client,
            dry_run=False,
            auto_approve=False,
            save_report=str(report_file),
        )
        assert executor.save_report == str(report_file)

    @patch('openpilot.workflow_executor.GoalUnderstandingEnhancer')
    def test_stage_1_goal_understanding_called(self, mock_enhancer_class, mock_llm_client):
        """测试阶段1调用目标理解增强器"""
        mock_enhancer = Mock()
        mock_enhancer_class.return_value = mock_enhancer

        mock_task_card = TaskCard(
            goal="测试目标",
            task_type=TaskType.CODING,
            risk_level=RiskLevel.LOW
        )
        mock_enhancer.enhance_task_card.return_value = mock_task_card

        executor = WorkflowExecutor(
            llm_client=mock_llm_client,
            dry_run=False,
            auto_approve=False,
        )

        result = executor._stage_1_goal_understanding("测试目标")

        # 验证返回了TaskCard
        assert isinstance(result, TaskCard)

    @patch('openpilot.workflow_executor.MemoryStore')
    def test_stage_2_memory_retrieval_called(self, mock_store_class, mock_llm_client):
        """测试阶段2调用记忆检索"""
        mock_store = Mock()
        mock_store_class.return_value = mock_store
        mock_store.query.return_value = MemoryQueryResult(query="测试目标", memories=[])

        executor = WorkflowExecutor(
            llm_client=mock_llm_client,
            dry_run=False,
            auto_approve=False,
        )

        task_card = TaskCard(
            goal="测试目标",
            task_type=TaskType.CODING,
            risk_level=RiskLevel.LOW
        )

        result = executor._stage_2_memory_retrieval(task_card)

        # 验证返回了列表
        assert isinstance(result, list)

    @patch('openpilot.workflow_executor.TaskPlanner')
    def test_stage_3_plan_generation_called(self, mock_planner_class, mock_llm_client):
        """测试阶段3调用计划生成"""
        mock_planner = Mock()
        mock_planner_class.return_value = mock_planner

        mock_plan = ExecutionPlan(
            task_card=TaskCard(
                goal="测试目标",
                task_type=TaskType.CODING,
                risk_level=RiskLevel.LOW
            ),
            steps=[
                PlanStep(
                    id="step1",
                    title="测试步骤",
                    description="测试描述",
                    risk_level=RiskLevel.LOW,
                    expected_output="测试输出"
                )
            ],
            success_criteria=["完成测试"]
        )
        mock_planner.plan.return_value = mock_plan

        executor = WorkflowExecutor(
            llm_client=mock_llm_client,
            dry_run=False,
            auto_approve=False,
        )

        result = executor._stage_3_plan_generation("测试目标", [], [])

        # 验证返回了ExecutionPlan
        assert isinstance(result, ExecutionPlan)

    def test_stage_5_execution_dry_run_returns_empty(self, mock_llm_client):
        """测试阶段5在dry_run模式下返回空结果"""
        executor = WorkflowExecutor(
            llm_client=mock_llm_client,
            dry_run=True,
            auto_approve=False,
        )

        orchestration_plan = {"tools": ["tool1"]}
        result = executor._stage_5_execution(orchestration_plan)

        # dry_run模式应该返回空列表
        assert isinstance(result, list)
        assert len(result) == 0

    def test_stats_initialization(self, mock_llm_client):
        """测试统计信息初始化"""
        executor = WorkflowExecutor(
            llm_client=mock_llm_client,
            dry_run=False,
            auto_approve=False,
        )

        assert "start_time" in executor.stats
        assert "end_time" in executor.stats
        assert "stages_completed" in executor.stats
        assert "total_stages" in executor.stats
        assert "success" in executor.stats
        assert executor.stats["total_stages"] == 8
        assert executor.stats["success"] is False

    @patch('openpilot.workflow_executor.GoalUnderstandingEnhancer')
    @patch('openpilot.workflow_executor.TaskPlanner')
    @patch('openpilot.workflow_executor.MemoryStore')
    @patch('openpilot.workflow_executor.ToolOrchestrator')
    def test_execute_dry_run_workflow(
        self,
        mock_orchestrator_class,
        mock_store_class,
        mock_planner_class,
        mock_enhancer_class,
        mock_llm_client
    ):
        """测试dry_run模式的完整工作流"""
        # 设置所有模拟
        mock_enhancer = Mock()
        mock_enhancer_class.return_value = mock_enhancer
        mock_task_card = TaskCard(
            goal="测试目标",
            task_type=TaskType.CODING,
            risk_level=RiskLevel.LOW
        )
        mock_enhancer.enhance_task_card.return_value = mock_task_card

        mock_store = Mock()
        mock_store_class.return_value = mock_store
        mock_store.query.return_value = MemoryQueryResult(query="测试目标", memories=[])

        mock_planner = Mock()
        mock_planner_class.return_value = mock_planner
        mock_plan = ExecutionPlan(
            task_card=mock_task_card,
            steps=[
                PlanStep(
                    id="step1",
                    title="测试步骤",
                    description="测试描述",
                    risk_level=RiskLevel.LOW,
                    expected_output="测试输出"
                )
            ],
            success_criteria=["完成测试"]
        )
        mock_planner.plan.return_value = mock_plan

        mock_orchestrator = Mock()
        mock_orchestrator_class.return_value = mock_orchestrator
        mock_orch_plan = Mock()
        mock_orch_plan.tool_selections = []
        mock_orchestrator.orchestrate.return_value = mock_orch_plan

        # 创建执行器
        executor = WorkflowExecutor(
            llm_client=mock_llm_client,
            dry_run=True,
            auto_approve=True,
        )

        # 执行
        result = executor.execute("测试目标", constraints=[])

        # 验证
        assert isinstance(result, dict)
        assert "success" in result
        assert result["success"] is True

    def test_module_integration(self, mock_llm_client):
        """测试各模块正确集成"""
        executor = WorkflowExecutor(
            llm_client=mock_llm_client,
            dry_run=False,
            auto_approve=False,
        )

        # 验证所有模块都已初始化且类型正确
        from openpilot.goal_understanding import GoalUnderstandingEnhancer
        from openpilot.planner import TaskPlanner
        from openpilot.memory_store import MemoryStore
        from openpilot.tool_registry import ToolRegistry
        from openpilot.tool_orchestrator import ToolOrchestrator
        from openpilot.tool_executor import ToolExecutor
        from openpilot.result_validator import ResultValidator
        from openpilot.reflection_analyzer import ReflectionAnalyzer
        from openpilot.strategy_optimizer import StrategyOptimizer
        from openpilot.openpilot_log import OpenPilotLogger

        assert isinstance(executor.goal_enhancer, GoalUnderstandingEnhancer)
        assert isinstance(executor.planner, TaskPlanner)
        assert isinstance(executor.memory_store, MemoryStore)
        assert isinstance(executor.tool_registry, ToolRegistry)
        assert isinstance(executor.orchestrator, ToolOrchestrator)
        assert isinstance(executor.executor, ToolExecutor)
        assert isinstance(executor.validator, ResultValidator)
        assert isinstance(executor.analyzer, ReflectionAnalyzer)
        assert isinstance(executor.optimizer, StrategyOptimizer)
        assert isinstance(executor.logger, OpenPilotLogger)
