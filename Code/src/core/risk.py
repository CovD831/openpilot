"""Deterministic risk classification safeguards."""

from __future__ import annotations

from models.planner_models import ExecutionPlan, RiskLevel

RISK_ORDER = {
    RiskLevel.LOW: 0,
    RiskLevel.MEDIUM: 1,
    RiskLevel.HIGH: 2,
    RiskLevel.FORBIDDEN: 3,
}

KEYWORDS: dict[RiskLevel, tuple[str, ...]] = {
    RiskLevel.FORBIDDEN: (
        "payment",
        "pay ",
        "transfer money",
        "wire transfer",
        "system setting",
        "unknown code",
        "production data",
        "付款",
        "支付",
        "转账",
        "修改系统设置",
        "未知代码",
        "生产数据",
    ),
    RiskLevel.HIGH: (
        "send email",
        "delete",
        "calendar",
        "sensitive account",
        "login",
        "password",
        "发送邮件",
        "删除",
        "修改日历",
        "访问账号",
        "登录",
        "密码",
    ),
    RiskLevel.MEDIUM: (
        "create file",
        "write file",
        "batch download",
        "paid model",
        "api quota",
        "创建文件",
        "写入文件",
        "批量下载",
        "付费模型",
        "模型额度",
    ),
}


def higher_risk(left: RiskLevel, right: RiskLevel) -> RiskLevel:
    """Return the higher risk level."""

    return left if RISK_ORDER[left] >= RISK_ORDER[right] else right


def classify_text_risk(text: str) -> RiskLevel:
    """Classify text using conservative keyword safeguards."""

    normalized = f" {text.lower()} "
    for risk in (RiskLevel.FORBIDDEN, RiskLevel.HIGH, RiskLevel.MEDIUM):
        if any(keyword in normalized for keyword in KEYWORDS[risk]):
            return risk
    return RiskLevel.LOW


def enforce_risk_policy(plan: ExecutionPlan) -> ExecutionPlan:
    """Prevent model output from downgrading obvious risk."""

    plan = plan.model_copy(deep=True)
    task_risk = classify_text_risk(plan.task_card.goal)
    plan.task_card.risk_level = higher_risk(plan.task_card.risk_level, task_risk)

    confirmation_points = set(plan.confirmation_points)
    for step in plan.steps:
        text = f"{step.title}\n{step.description}\n{step.expected_output}"
        step.risk_level = higher_risk(step.risk_level, classify_text_risk(text))
        if step.risk_level in {RiskLevel.HIGH, RiskLevel.FORBIDDEN}:
            step.confirmation_required = True
            confirmation_points.add(step.id)
        plan.task_card.risk_level = higher_risk(plan.task_card.risk_level, step.risk_level)

    if plan.task_card.risk_level in {RiskLevel.HIGH, RiskLevel.FORBIDDEN}:
        confirmation_points.add("task")
    plan.confirmation_points = sorted(confirmation_points)
    return plan


