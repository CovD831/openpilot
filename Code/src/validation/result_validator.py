"""
结果验证器

验证工具执行结果和代码执行结果的正确性。
"""

import time
import uuid
from typing import Any, Optional

from models.code_models import CodeExecutionResult
from models.executor_models import ExecutionResult, ExecutionStatus
from validation.output_validator import OutputValidator
from models.validation_models import (
    QualityLevel,
    QualityMetrics,
    ValidationResult,
    ValidationRule,
    ValidationSeverity,
    ValidationType,
)


class ResultValidator:
    """结果验证器"""

    def __init__(self, output_validator: Optional[OutputValidator] = None):
        """
        初始化结果验证器

        Args:
            output_validator: 输出验证器（如果为 None，创建新实例）
        """
        self.output_validator = output_validator or OutputValidator()
        self._validation_count = 0

    def validate_execution_result(
        self,
        result: ExecutionResult,
        validation_rules: Optional[list[ValidationRule]] = None,
        expected_output: Optional[Any] = None,
    ) -> ValidationResult:
        """
        验证工具执行结果

        Args:
            result: 执行结果
            validation_rules: 验证规则
            expected_output: 期望的输出

        Returns:
            ValidationResult: 验证结果
        """
        # 如果执行失败，直接返回失败的验证结果
        if not result.success:
            return self._create_failed_validation(
                result.execution_id,
                f"执行失败: {result.error.error_message if result.error else '未知错误'}",
            )

        # 验证输出
        if result.output is not None:
            validation_result = self.output_validator.validate(
                result.output,
                rules=validation_rules,
                target_id=result.execution_id,
            )

            # 如果提供了期望输出，额外检查
            if expected_output is not None:
                if result.output != expected_output:
                    # 添加输出不匹配的问题
                    from models.validation_models import ValidationIssue

                    validation_result.issues.append(
                        ValidationIssue(
                            rule_id="output_match",
                            severity=ValidationSeverity.ERROR,
                            message="输出与期望不匹配",
                            actual_value=result.output,
                            expected_value=expected_output,
                            suggestion="检查工具执行逻辑",
                        )
                    )
                    validation_result.passed = False
                    validation_result.failed_rules += 1
                    validation_result.error_count += 1

            self._validation_count += 1
            return validation_result

        # 没有输出，返回通过
        return self._create_passed_validation(result.execution_id)

    def validate_code_execution_result(
        self,
        result: CodeExecutionResult,
        validation_rules: Optional[list[ValidationRule]] = None,
        expected_output: Optional[Any] = None,
    ) -> ValidationResult:
        """
        验证代码执行结果

        Args:
            result: 代码执行结果
            validation_rules: 验证规则
            expected_output: 期望的输出

        Returns:
            ValidationResult: 验证结果
        """
        # 如果执行失败，直接返回失败的验证结果
        if not result.success:
            return self._create_failed_validation(
                result.execution_id,
                f"代码执行失败: {result.error_message or '未知错误'}",
            )

        # 验证返回值
        if result.return_value is not None:
            validation_result = self.output_validator.validate(
                result.return_value,
                rules=validation_rules,
                target_id=result.execution_id,
            )

            # 如果提供了期望输出，额外检查
            if expected_output is not None:
                if result.return_value != expected_output:
                    from models.validation_models import ValidationIssue

                    validation_result.issues.append(
                        ValidationIssue(
                            rule_id="return_value_match",
                            severity=ValidationSeverity.ERROR,
                            message="返回值与期望不匹配",
                            actual_value=result.return_value,
                            expected_value=expected_output,
                            suggestion="检查代码逻辑",
                        )
                    )
                    validation_result.passed = False
                    validation_result.failed_rules += 1
                    validation_result.error_count += 1

            self._validation_count += 1
            return validation_result

        # 没有返回值，检查标准输出
        if result.stdout:
            validation_result = self.output_validator.validate(
                result.stdout,
                rules=validation_rules,
                target_id=result.execution_id,
            )
            self._validation_count += 1
            return validation_result

        # 没有输出，返回通过
        return self._create_passed_validation(result.execution_id)

    def calculate_quality_metrics(
        self,
        result: ExecutionResult,
        validation_result: ValidationResult,
        user_rating: Optional[float] = None,
    ) -> QualityMetrics:
        """
        计算质量指标

        Args:
            result: 执行结果
            validation_result: 验证结果
            user_rating: 用户评分

        Returns:
            QualityMetrics: 质量指标
        """
        # 1. 正确性评分（基于验证结果）
        if result.success:
            correctness_score = validation_result.pass_rate
        else:
            correctness_score = 0.0

        # 2. 完整性评分（基于是否有输出和错误）
        completeness_score = 1.0
        if result.output is None and result.success:
            completeness_score -= 0.2  # 没有输出降低完整性
        if result.error:
            completeness_score -= 0.3  # 有错误降低完整性
        completeness_score = max(0.0, completeness_score)

        # 3. 效率评分（基于执行时间）
        efficiency_score = self._calculate_efficiency_score(result.duration_seconds)

        # 4. 可靠性评分（基于重试次数和错误）
        reliability_score = 1.0
        if hasattr(result, "retry_count") and result.retry_count > 0:
            reliability_score -= 0.1 * result.retry_count
        if validation_result.critical_count > 0:
            reliability_score -= 0.3
        if validation_result.error_count > 0:
            reliability_score -= 0.2
        reliability_score = max(0.0, reliability_score)

        # 5. 综合评分（加权平均）
        overall_score = (
            correctness_score * 0.4
            + completeness_score * 0.2
            + efficiency_score * 0.2
            + reliability_score * 0.2
        )

        # 6. 确定质量等级
        quality_level = self._determine_quality_level(overall_score)

        return QualityMetrics(
            target_id=result.execution_id,
            correctness_score=correctness_score,
            completeness_score=completeness_score,
            efficiency_score=efficiency_score,
            reliability_score=reliability_score,
            overall_score=overall_score,
            quality_level=quality_level,
            execution_time_ms=int(result.duration_seconds * 1000),
            error_count=validation_result.error_count,
            warning_count=validation_result.warning_count,
            retry_count=getattr(result, "retry_count", 0),
            user_rating=user_rating,
            feedback_count=1 if user_rating is not None else 0,
        )

    def calculate_code_quality_metrics(
        self,
        result: CodeExecutionResult,
        validation_result: ValidationResult,
        user_rating: Optional[float] = None,
    ) -> QualityMetrics:
        """
        计算代码执行质量指标

        Args:
            result: 代码执行结果
            validation_result: 验证结果
            user_rating: 用户评分

        Returns:
            QualityMetrics: 质量指标
        """
        # 1. 正确性评分
        if result.success:
            correctness_score = validation_result.pass_rate
        else:
            correctness_score = 0.0

        # 2. 完整性评分
        completeness_score = 1.0
        if result.return_value is None and not result.stdout and result.success:
            completeness_score -= 0.2
        if result.error_message:
            completeness_score -= 0.3
        completeness_score = max(0.0, completeness_score)

        # 3. 效率评分
        efficiency_score = self._calculate_efficiency_score(
            result.execution_time_ms / 1000.0
        )

        # 4. 可靠性评分
        reliability_score = 1.0
        if result.error_type:
            reliability_score -= 0.3
        if validation_result.critical_count > 0:
            reliability_score -= 0.3
        if validation_result.error_count > 0:
            reliability_score -= 0.2
        reliability_score = max(0.0, reliability_score)

        # 5. 综合评分
        overall_score = (
            correctness_score * 0.4
            + completeness_score * 0.2
            + efficiency_score * 0.2
            + reliability_score * 0.2
        )

        # 6. 质量等级
        quality_level = self._determine_quality_level(overall_score)

        return QualityMetrics(
            target_id=result.execution_id,
            correctness_score=correctness_score,
            completeness_score=completeness_score,
            efficiency_score=efficiency_score,
            reliability_score=reliability_score,
            overall_score=overall_score,
            quality_level=quality_level,
            execution_time_ms=result.execution_time_ms,
            error_count=validation_result.error_count,
            warning_count=validation_result.warning_count,
            retry_count=0,
            user_rating=user_rating,
            feedback_count=1 if user_rating is not None else 0,
        )

    def _calculate_efficiency_score(self, duration_seconds: float) -> float:
        """
        计算效率评分

        Args:
            duration_seconds: 执行时间（秒）

        Returns:
            float: 效率评分（0-1）
        """
        # 基于执行时间的评分
        # < 1s: 1.0
        # 1-5s: 0.8
        # 5-10s: 0.6
        # 10-30s: 0.4
        # > 30s: 0.2

        if duration_seconds < 1:
            return 1.0
        elif duration_seconds < 5:
            return 0.8
        elif duration_seconds < 10:
            return 0.6
        elif duration_seconds < 30:
            return 0.4
        else:
            return 0.2

    def _determine_quality_level(self, score: float) -> QualityLevel:
        """
        确定质量等级

        Args:
            score: 综合评分

        Returns:
            QualityLevel: 质量等级
        """
        if score >= 0.9:
            return QualityLevel.EXCELLENT
        elif score >= 0.7:
            return QualityLevel.GOOD
        elif score >= 0.5:
            return QualityLevel.FAIR
        elif score >= 0.3:
            return QualityLevel.POOR
        else:
            return QualityLevel.VERY_POOR

    def _create_passed_validation(self, target_id: str) -> ValidationResult:
        """创建通过的验证结果"""
        return ValidationResult(
            validation_id=f"val_{uuid.uuid4().hex[:8]}",
            target_id=target_id,
            passed=True,
            issues=[],
            total_rules=0,
            passed_rules=0,
            failed_rules=0,
        )

    def _create_failed_validation(
        self, target_id: str, message: str
    ) -> ValidationResult:
        """创建失败的验证结果"""
        from models.validation_models import ValidationIssue

        issue = ValidationIssue(
            rule_id="execution_status",
            severity=ValidationSeverity.CRITICAL,
            message=message,
        )

        return ValidationResult(
            validation_id=f"val_{uuid.uuid4().hex[:8]}",
            target_id=target_id,
            passed=False,
            issues=[issue],
            total_rules=1,
            passed_rules=0,
            failed_rules=1,
            critical_count=1,
        )

    def get_stats(self) -> dict:
        """获取验证统计"""
        return {
            "total_validations": self._validation_count,
            "output_validator_stats": self.output_validator.get_stats(),
        }
