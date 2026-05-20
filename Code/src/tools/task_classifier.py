"""Task Classifier Tool - Route user tasks to the right execution mode."""

from __future__ import annotations

from typing import Any

from metadata import ToolContractMetadata, ToolInputMetadata, ToolResultMetadata, metadata_tool_result

from core.tool_contracts import (
    PermissionLevel,
    ToolDefinition,
    ToolFailureMode,
)


AGENT_GENERATOR_ROUTE = "agent_generator"
AUTONOMOUS_ITERATION_ROUTE = "autonomous_iteration"

CREATION_TERMS = (
    "生成",
    "创建",
    "构建",
    "设计",
    "产出",
    "制作",
    "沉淀",
    "固化",
    "封装",
    "generate",
    "create",
    "build",
    "design",
    "make",
    "scaffold",
    "package",
)
REUSABLE_TERMS = (
    "可复用",
    "复用",
    "重复使用",
    "沉淀",
    "固化",
    "reusable",
    "reuse",
)
AGENT_TARGET_TERMS = (
    "工作流",
    "自动化模板",
    "流程模板",
    "workflow",
    "automation template",
    "pipeline",
)
AGENT_TERMS = (
    "agent",
    "智能体",
    "代理",
    "可复用脚本",
    "reusable script",
    "reusable agent",
)
EXECUTION_TERMS = (
    "实现",
    "修改",
    "修复",
    "优化",
    "重构",
    "写代码",
    "创建项目",
    "项目",
    "文件",
    "目录",
    "路径",
    "bug",
    "测试",
    "运行",
    "implement",
    "modify",
    "fix",
    "optimize",
    "refactor",
    "code",
    "project",
    "file",
    "directory",
    "path",
    "test",
    "run",
    "install",
)
KNOWLEDGE_WORK_TERMS = (
    "调查",
    "研究",
    "调研",
    "资料整理",
    "整理资料",
    "总结",
    "概述",
    "介绍",
    "解释",
    "报告",
    "对比",
    "分析",
    "梳理",
    "review",
    "research",
    "investigate",
    "survey",
    "summarize",
    "summary",
    "report",
    "overview",
    "explain",
    "compare",
    "analysis",
    "analyze",
)
AMBIGUOUS_KNOWLEDGE_PHRASES = (
    "分析一下这个任务",
    "分析这个任务",
    "看看这个任务",
    "看一下这个任务",
    "analyze this task",
    "analyse this task",
)


TASK_CLASSIFIER_DEFINITION = ToolDefinition(
    name="task_classifier",
    display_name="Task Classifier",
    description="Classify a user task and choose agent generation or autonomous iteration",
    version="1.0.0",
    capabilities=[],
    permission_level=PermissionLevel.AUTO,
    contract_metadata=ToolContractMetadata(
        tool_name='task_classifier',
        input_metadata_type="ToolInputMetadata",
        output_metadata_type="ToolResultMetadata",
        required_input_fields=['task'],
        input_defaults={},
    ),
    timeout_seconds=5,
    max_retries=0,
    failure_modes=[
        ToolFailureMode(
            error_type="invalid_input",
            description="Task text is missing or empty",
            recovery_strategy="Provide a non-empty task string",
        ),
    ],
    tags=["classification", "routing", "agent", "autopilot"],
    audit_required=True,
)


@metadata_tool_result('task_classifier')
def task_classifier_executor(input_metadata: ToolInputMetadata) -> ToolResultMetadata:
    params = input_metadata.to_params()
    """Classify a task into the agent generator or autonomous iteration route."""
    task = " ".join(str(params.get("task") or "").strip().split())
    if not task:
        raise ValueError("task must not be empty")

    normalized = task.casefold()

    has_creation = _contains_any(normalized, CREATION_TERMS)
    has_reusable_intent = _contains_any(normalized, REUSABLE_TERMS)
    has_agent_target = _contains_any(normalized, AGENT_TERMS + AGENT_TARGET_TERMS)
    has_execution_intent = _contains_any(normalized, EXECUTION_TERMS)
    has_knowledge_work = (
        _contains_any(normalized, KNOWLEDGE_WORK_TERMS)
        and not _contains_any(normalized, AMBIGUOUS_KNOWLEDGE_PHRASES)
    )

    if has_creation and (has_agent_target or has_reusable_intent):
        return {
            "route": AGENT_GENERATOR_ROUTE,
            "confidence": 0.88 if has_agent_target and has_reusable_intent else 0.78,
            "reason": "Task asks to create a reusable agent, workflow, template, or automation, so route to agent_generator.",
        }

    if has_execution_intent:
        return {
            "route": AUTONOMOUS_ITERATION_ROUTE,
            "confidence": 0.86,
            "reason": "Task includes code, project, file, bug, test, or run/install execution intent, so route to autonomous_iteration.",
        }

    if has_knowledge_work:
        return {
            "route": AGENT_GENERATOR_ROUTE,
            "confidence": 0.84,
            "reason": "Task asks for research, investigation, summarization, reporting, explanation, or other knowledge work, so route to agent_generator.",
        }

    return {
        "route": AUTONOMOUS_ITERATION_ROUTE,
        "confidence": 0.82,
        "reason": "Task asks to modify/build directly or is ambiguous, so default execution path is autonomous iteration.",
    }


def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
    return any(term.casefold() in text for term in terms)
