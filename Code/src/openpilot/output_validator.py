"""
输出验证器

验证工具执行结果和代码执行结果的输出格式、类型、范围等。
"""

import json
import re
import time
import uuid
from typing import Any, Callable, Optional

from openpilot.validation_models import (
    ValidationIssue,
    ValidationResult,
    ValidationRule,
    ValidationSeverity,
    ValidationType,
)


class OutputValidator:
    """输出验证器"""

    def __init__(self):
        """初始化验证器"""
        self._rules: dict[str, ValidationRule] = {}
        self._custom_validators: dict[str, Callable] = {}
        self._validation_count = 0

    def register_rule(self, rule: ValidationRule):
        """
        注册验证规则

        Args:
            rule: 验证规则
        """
        self._rules[rule.rule_id] = rule

    def register_custom_validator(self, name: str, validator: Callable):
        """
        注册自定义验证器

        Args:
            name: 验证器名称
            validator: 验证函数，接受 (value, rule) 返回 (bool, Optional[str])
        """
        self._custom_validators[name] = validator

    def validate(
        self,
        output: Any,
        rules: Optional[list[ValidationRule]] = None,
        target_id: Optional[str] = None,
    ) -> ValidationResult:
        """
        验证输出

        Args:
            output: 要验证的输出
            rules: 验证规则列表（如果为 None，使用所有已注册规则）
            target_id: 目标ID

        Returns:
            ValidationResult: 验证结果
        """
        start_time = time.time()
        validation_id = f"val_{uuid.uuid4().hex[:8]}"
        target_id = target_id or "unknown"

        # 确定要使用的规则
        if rules is None:
            rules = [r for r in self._rules.values() if r.enabled]

        issues = []
        passed_count = 0
        failed_count = 0

        # 严重程度计数
        severity_counts = {
            ValidationSeverity.CRITICAL: 0,
            ValidationSeverity.ERROR: 0,
            ValidationSeverity.WARNING: 0,
            ValidationSeverity.INFO: 0,
        }

        # 执行每个规则
        for rule in rules:
            is_valid, issue = self._validate_rule(output, rule)

            if is_valid:
                passed_count += 1
            else:
                failed_count += 1
                if issue:
                    issues.append(issue)
                    severity_counts[issue.severity] += 1

        # 计算验证时间
        validation_time_ms = int((time.time() - start_time) * 1000)

        # 更新统计
        self._validation_count += 1

        return ValidationResult(
            validation_id=validation_id,
            target_id=target_id,
            passed=len(issues) == 0,
            issues=issues,
            total_rules=len(rules),
            passed_rules=passed_count,
            failed_rules=failed_count,
            critical_count=severity_counts[ValidationSeverity.CRITICAL],
            error_count=severity_counts[ValidationSeverity.ERROR],
            warning_count=severity_counts[ValidationSeverity.WARNING],
            info_count=severity_counts[ValidationSeverity.INFO],
            validation_time_ms=validation_time_ms,
        )

    def _validate_rule(
        self, output: Any, rule: ValidationRule
    ) -> tuple[bool, Optional[ValidationIssue]]:
        """
        验证单个规则

        Args:
            output: 输出值
            rule: 验证规则

        Returns:
            tuple[bool, Optional[ValidationIssue]]: (是否通过, 问题描述)
        """
        try:
            if rule.validation_type == ValidationType.TYPE:
                return self._validate_type(output, rule)
            elif rule.validation_type == ValidationType.FORMAT:
                return self._validate_format(output, rule)
            elif rule.validation_type == ValidationType.RANGE:
                return self._validate_range(output, rule)
            elif rule.validation_type == ValidationType.PATTERN:
                return self._validate_pattern(output, rule)
            elif rule.validation_type == ValidationType.SCHEMA:
                return self._validate_schema(output, rule)
            elif rule.validation_type == ValidationType.CUSTOM:
                return self._validate_custom(output, rule)
            else:
                return True, None

        except Exception as e:
            # 验证过程出错
            issue = ValidationIssue(
                rule_id=rule.rule_id,
                severity=ValidationSeverity.ERROR,
                message=f"验证规则执行失败: {str(e)}",
                actual_value=output,
            )
            return False, issue

    def _validate_type(
        self, output: Any, rule: ValidationRule
    ) -> tuple[bool, Optional[ValidationIssue]]:
        """验证类型"""
        if rule.expected_type is None:
            return True, None

        expected_type = rule.expected_type.lower()
        actual_type = type(output).__name__.lower()

        # 类型映射
        type_mapping = {
            "str": "str",
            "string": "str",
            "int": "int",
            "integer": "int",
            "float": "float",
            "number": ["int", "float"],
            "bool": "bool",
            "boolean": "bool",
            "list": "list",
            "array": "list",
            "dict": "dict",
            "object": "dict",
            "none": "nonetype",
            "null": "nonetype",
        }

        expected = type_mapping.get(expected_type, expected_type)

        # 检查类型
        if isinstance(expected, list):
            is_valid = actual_type in expected
        else:
            is_valid = actual_type == expected

        if not is_valid:
            issue = ValidationIssue(
                rule_id=rule.rule_id,
                severity=rule.severity,
                message=f"类型不匹配: 期望 {rule.expected_type}, 实际 {type(output).__name__}",
                actual_value=actual_type,
                expected_value=rule.expected_type,
                suggestion=f"将输出转换为 {rule.expected_type} 类型",
            )
            return False, issue

        return True, None

    def _validate_format(
        self, output: Any, rule: ValidationRule
    ) -> tuple[bool, Optional[ValidationIssue]]:
        """验证格式"""
        if rule.expected_format is None:
            return True, None

        format_type = rule.expected_format.lower()

        # 格式验证函数
        format_validators = {
            "json": self._is_valid_json,
            "email": self._is_valid_email,
            "url": self._is_valid_url,
            "date": self._is_valid_date,
            "uuid": self._is_valid_uuid,
            "ipv4": self._is_valid_ipv4,
        }

        validator = format_validators.get(format_type)
        if validator is None:
            return True, None

        is_valid = validator(output)

        if not is_valid:
            issue = ValidationIssue(
                rule_id=rule.rule_id,
                severity=rule.severity,
                message=f"格式不正确: 期望 {rule.expected_format} 格式",
                actual_value=output,
                suggestion=f"确保输出符合 {rule.expected_format} 格式",
            )
            return False, issue

        return True, None

    def _validate_range(
        self, output: Any, rule: ValidationRule
    ) -> tuple[bool, Optional[ValidationIssue]]:
        """验证范围"""
        # 尝试转换为数字
        try:
            value = float(output)
        except (TypeError, ValueError):
            issue = ValidationIssue(
                rule_id=rule.rule_id,
                severity=rule.severity,
                message="无法转换为数字进行范围验证",
                actual_value=output,
            )
            return False, issue

        # 检查最小值
        if rule.min_value is not None and value < rule.min_value:
            issue = ValidationIssue(
                rule_id=rule.rule_id,
                severity=rule.severity,
                message=f"值小于最小值: {value} < {rule.min_value}",
                actual_value=value,
                expected_value=f">= {rule.min_value}",
                suggestion=f"确保值不小于 {rule.min_value}",
            )
            return False, issue

        # 检查最大值
        if rule.max_value is not None and value > rule.max_value:
            issue = ValidationIssue(
                rule_id=rule.rule_id,
                severity=rule.severity,
                message=f"值大于最大值: {value} > {rule.max_value}",
                actual_value=value,
                expected_value=f"<= {rule.max_value}",
                suggestion=f"确保值不大于 {rule.max_value}",
            )
            return False, issue

        return True, None

    def _validate_pattern(
        self, output: Any, rule: ValidationRule
    ) -> tuple[bool, Optional[ValidationIssue]]:
        """验证模式"""
        if rule.pattern is None:
            return True, None

        # 转换为字符串
        output_str = str(output)

        # 正则匹配
        try:
            if not re.match(rule.pattern, output_str):
                issue = ValidationIssue(
                    rule_id=rule.rule_id,
                    severity=rule.severity,
                    message=f"不匹配模式: {rule.pattern}",
                    actual_value=output_str,
                    suggestion="确保输出符合指定的正则模式",
                )
                return False, issue
        except re.error as e:
            issue = ValidationIssue(
                rule_id=rule.rule_id,
                severity=ValidationSeverity.ERROR,
                message=f"正则表达式错误: {str(e)}",
            )
            return False, issue

        return True, None

    def _validate_schema(
        self, output: Any, rule: ValidationRule
    ) -> tuple[bool, Optional[ValidationIssue]]:
        """验证结构（简化版 JSON Schema）"""
        if rule.schema is None:
            return True, None

        # 简化的 schema 验证
        schema = rule.schema

        # 检查类型
        if "type" in schema:
            expected_type = schema["type"]
            actual_type = type(output).__name__.lower()

            type_map = {
                "object": "dict",
                "array": "list",
                "string": "str",
                "number": ["int", "float"],
                "integer": "int",
                "boolean": "bool",
                "null": "nonetype",
            }

            expected = type_map.get(expected_type, expected_type)
            if isinstance(expected, list):
                is_valid = actual_type in expected
            else:
                is_valid = actual_type == expected

            if not is_valid:
                issue = ValidationIssue(
                    rule_id=rule.rule_id,
                    severity=rule.severity,
                    message=f"Schema 类型不匹配: 期望 {expected_type}",
                    actual_value=actual_type,
                )
                return False, issue

        # 检查必需字段（如果是字典）
        if isinstance(output, dict) and "required" in schema:
            for field in schema["required"]:
                if field not in output:
                    issue = ValidationIssue(
                        rule_id=rule.rule_id,
                        severity=rule.severity,
                        message=f"缺少必需字段: {field}",
                        field_path=field,
                        suggestion=f"添加必需字段 {field}",
                    )
                    return False, issue

        return True, None

    def _validate_custom(
        self, output: Any, rule: ValidationRule
    ) -> tuple[bool, Optional[ValidationIssue]]:
        """自定义验证"""
        if rule.custom_validator is None:
            return True, None

        validator = self._custom_validators.get(rule.custom_validator)
        if validator is None:
            issue = ValidationIssue(
                rule_id=rule.rule_id,
                severity=ValidationSeverity.ERROR,
                message=f"自定义验证器未找到: {rule.custom_validator}",
            )
            return False, issue

        # 调用自定义验证器
        try:
            is_valid, error_message = validator(output, rule)

            if not is_valid:
                issue = ValidationIssue(
                    rule_id=rule.rule_id,
                    severity=rule.severity,
                    message=error_message or "自定义验证失败",
                    actual_value=output,
                )
                return False, issue

            return True, None

        except Exception as e:
            issue = ValidationIssue(
                rule_id=rule.rule_id,
                severity=ValidationSeverity.ERROR,
                message=f"自定义验证器执行失败: {str(e)}",
            )
            return False, issue

    # 格式验证辅助函数

    def _is_valid_json(self, value: Any) -> bool:
        """验证 JSON 格式"""
        if not isinstance(value, str):
            return False
        try:
            json.loads(value)
            return True
        except (json.JSONDecodeError, TypeError):
            return False

    def _is_valid_email(self, value: Any) -> bool:
        """验证邮箱格式"""
        if not isinstance(value, str):
            return False
        pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
        return bool(re.match(pattern, value))

    def _is_valid_url(self, value: Any) -> bool:
        """验证 URL 格式"""
        if not isinstance(value, str):
            return False
        pattern = r"^https?://[^\s/$.?#].[^\s]*$"
        return bool(re.match(pattern, value))

    def _is_valid_date(self, value: Any) -> bool:
        """验证日期格式"""
        if not isinstance(value, str):
            return False
        # 支持常见日期格式
        patterns = [
            r"^\d{4}-\d{2}-\d{2}$",  # YYYY-MM-DD
            r"^\d{2}/\d{2}/\d{4}$",  # MM/DD/YYYY
            r"^\d{4}/\d{2}/\d{2}$",  # YYYY/MM/DD
        ]
        return any(re.match(p, value) for p in patterns)

    def _is_valid_uuid(self, value: Any) -> bool:
        """验证 UUID 格式"""
        if not isinstance(value, str):
            return False
        pattern = r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
        return bool(re.match(pattern, value.lower()))

    def _is_valid_ipv4(self, value: Any) -> bool:
        """验证 IPv4 格式"""
        if not isinstance(value, str):
            return False
        pattern = r"^(\d{1,3}\.){3}\d{1,3}$"
        if not re.match(pattern, value):
            return False
        # 检查每个部分是否在 0-255 范围内
        parts = value.split(".")
        return all(0 <= int(part) <= 255 for part in parts)

    def get_stats(self) -> dict:
        """获取验证统计"""
        return {
            "total_validations": self._validation_count,
            "registered_rules": len(self._rules),
            "custom_validators": len(self._custom_validators),
        }
