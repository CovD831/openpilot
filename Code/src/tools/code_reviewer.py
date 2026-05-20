"""Code Reviewer Tool - Review code quality and suggest improvements using LLM."""

from __future__ import annotations

import ast
import re
import uuid
from typing import Any

from metadata import ToolContractMetadata, ToolInputMetadata, ToolResultMetadata, metadata_tool_result

from core.tool_contracts import (
    PermissionLevel,
    ToolCapability,
    ToolDefinition,
    ToolFailureMode,
)
from tools.code_models import (
    CodeLanguage,
    CodeReviewResult,
    DangerLevel,
    DangerousOperation,
    GeneratedCode,
)


CODE_REVIEWER_DEFINITION = ToolDefinition(
    name="code_reviewer",
    display_name="Code Reviewer",
    description="Review code quality and suggest improvements using LLM",
    version="1.0.0",
    capabilities=[ToolCapability.CODE_EXECUTION, ToolCapability.LLM_CALL],
    permission_level=PermissionLevel.LOW,
    contract_metadata=ToolContractMetadata(
        tool_name='code_reviewer',
        input_metadata_type="ToolInputMetadata",
        output_metadata_type="ToolResultMetadata",
        required_input_fields=['code', 'language'],
        input_defaults={'prompt_context': {}},
    ),
    timeout_seconds=60,
    max_retries=2,
    failure_modes=[
        ToolFailureMode(
            error_type="llm_timeout",
            description="LLM request timed out",
            recovery_strategy="Retry with shorter code snippet"
        ),
        ToolFailureMode(
            error_type="llm_error",
            description="LLM returned error",
            recovery_strategy="Check LLM configuration and API key"
        )
    ],
    tags=["code", "review", "quality", "llm"],
    audit_required=True
)


@metadata_tool_result('code_reviewer')
def code_reviewer_executor(input_metadata: ToolInputMetadata) -> ToolResultMetadata:
    params = input_metadata.to_params()
    """
    Execute code reviewer tool.

    Args:
        params: Tool parameters (code, language)

    Returns:
        Dictionary with review, issues, suggestions, approved
    """
    code = params["code"]
    language_str = params["language"].lower()
    prompt_context = params.get("prompt_context") if isinstance(params.get("prompt_context"), dict) else {}

    # Map language string to CodeLanguage enum
    language_map = {
        "python": CodeLanguage.PYTHON,
        "shell": CodeLanguage.SHELL,
        "bash": CodeLanguage.BASH,
    }

    if language_str not in language_map:
        raise ValueError(f"Unsupported language: {language_str}. Use python, shell, or bash.")

    language = language_map[language_str]

    try:
        reviewer = CodeReviewer()

        # Create GeneratedCode object
        generated_code = GeneratedCode(
            code_id=f"code_{uuid.uuid4().hex[:8]}",
            request_id=f"req_{uuid.uuid4().hex[:8]}",
            language=language,
            code=code,
            line_count=len([line for line in code.split("\n") if line.strip()]),
            imports=[],
            functions=[],
            model_used="unknown",
            generation_time_ms=0
        )

        # Review code
        result = reviewer.review_code(generated_code)

        product_warnings = _product_fit_warnings(code, prompt_context)
        approved = bool(result.approved and not product_warnings)
        return {
            "review": (
                "Approved"
                if approved
                else "Review found issues"
            ),
            "issues": [issue.dict() if hasattr(issue, 'dict') else str(issue) for issue in result.dangerous_operations],
            "suggestions": result.recommendations + product_warnings,
            "approved": approved,
            "syntax_errors": result.syntax_errors,
            "warnings": result.warnings + product_warnings,
            "quality_score": result.quality_score,
            "complexity_score": result.complexity_score,
        }
    except Exception as e:
        raise Exception(f"Code review failed: {e}") from e


def _product_fit_warnings(code: str, prompt_context: dict[str, Any]) -> list[str]:
    product_judgment = prompt_context.get("product_judgment") or {}
    if product_judgment.get("preferred_stack") != "pygame":
        return []

    lowered = code.lower()
    if "pygame" in lowered:
        return []

    if "import curses" in lowered or "curses." in lowered or "stdscr" in lowered:
        return [
            "Product-fit rubric not satisfied: default Python snake game should migrate from terminal/curses to pygame unless terminal was requested."
        ]

    return [
        "Product-fit rubric not satisfied: default Python snake game should use a standalone pygame GUI unless terminal was requested."
    ]


class CodeReviewer:
    """代码审查器"""

    # 危险操作模式（Python）
    DANGEROUS_PATTERNS = {
        # 系统命令执行
        r"os\.system": (DangerLevel.CRITICAL, "直接执行系统命令", "使用 subprocess.run 并验证输入"),
        r"subprocess\.call": (DangerLevel.HIGH, "执行系统命令", "使用 subprocess.run 并验证输入"),
        r"subprocess\.Popen": (DangerLevel.HIGH, "执行系统命令", "使用 subprocess.run 并验证输入"),
        r"eval\(": (DangerLevel.CRITICAL, "动态执行代码", "避免使用 eval，使用安全的替代方案"),
        r"exec\(": (DangerLevel.CRITICAL, "动态执行代码", "避免使用 exec，使用安全的替代方案"),
        r"__import__": (DangerLevel.HIGH, "动态导入模块", "使用静态 import 语句"),

        # 文件操作
        r"os\.remove": (DangerLevel.MEDIUM, "删除文件", "确认文件路径安全"),
        r"os\.rmdir": (DangerLevel.MEDIUM, "删除目录", "确认目录路径安全"),
        r"shutil\.rmtree": (DangerLevel.HIGH, "递归删除目录", "确认目录路径安全"),
        r"os\.unlink": (DangerLevel.MEDIUM, "删除文件", "确认文件路径安全"),

        # 网络操作
        r"requests\.": (DangerLevel.LOW, "发起网络请求", "确认目标URL安全"),
        r"urllib\.request": (DangerLevel.LOW, "发起网络请求", "确认目标URL安全"),
        r"socket\.": (DangerLevel.MEDIUM, "使用网络套接字", "确认网络操作安全"),

        # 危险的内置函数
        r"compile\(": (DangerLevel.HIGH, "编译代码", "避免动态编译代码"),
        r"globals\(\)": (DangerLevel.MEDIUM, "访问全局变量", "限制全局变量访问"),
        r"locals\(\)": (DangerLevel.LOW, "访问局部变量", "谨慎使用"),

        # 文件权限
        r"os\.chmod": (DangerLevel.MEDIUM, "修改文件权限", "确认权限修改安全"),
        r"os\.chown": (DangerLevel.MEDIUM, "修改文件所有者", "确认所有者修改安全"),
    }

    # Shell 危险操作模式
    SHELL_DANGEROUS_PATTERNS = {
        r"\brm\s+-rf": (DangerLevel.CRITICAL, "强制递归删除", "避免使用 rm -rf"),
        r"\brm\s+": (DangerLevel.HIGH, "删除文件", "确认删除路径安全"),
        r"\bcurl\s+": (DangerLevel.LOW, "网络请求", "确认URL安全"),
        r"\bwget\s+": (DangerLevel.LOW, "网络下载", "确认URL安全"),
        r"\bchmod\s+": (DangerLevel.MEDIUM, "修改权限", "确认权限修改安全"),
        r"\bsudo\s+": (DangerLevel.CRITICAL, "提权执行", "避免使用 sudo"),
        r"\bsu\s+": (DangerLevel.CRITICAL, "切换用户", "避免使用 su"),
        r">\s*/dev/": (DangerLevel.HIGH, "写入设备文件", "避免直接操作设备"),
    }

    def __init__(self):
        """初始化审查器"""
        pass

    def review_code(self, generated_code: GeneratedCode) -> CodeReviewResult:
        """
        审查代码

        Args:
            generated_code: 生成的代码

        Returns:
            CodeReviewResult: 审查结果
        """
        if generated_code.language == CodeLanguage.PYTHON:
            return self._review_python_code(generated_code)
        elif generated_code.language in (CodeLanguage.SHELL, CodeLanguage.BASH):
            return self._review_shell_code(generated_code)
        else:
            raise ValueError(f"不支持的语言: {generated_code.language}")

    def _review_python_code(self, generated_code: GeneratedCode) -> CodeReviewResult:
        """审查 Python 代码"""
        dangerous_operations = []
        syntax_errors = []
        warnings = []

        # 1. 语法检查
        try:
            tree = ast.parse(generated_code.code)
        except SyntaxError as e:
            syntax_errors.append(f"语法错误 (行 {e.lineno}): {e.msg}")
            return CodeReviewResult(
                code_id=generated_code.code_id,
                approved=False,
                overall_danger_level=DangerLevel.CRITICAL,
                syntax_errors=syntax_errors,
            )

        # 2. AST 分析
        dangerous_operations.extend(self._analyze_python_ast(tree, generated_code.code))

        # 3. 正则模式匹配
        dangerous_operations.extend(
            self._check_patterns(generated_code.code, self.DANGEROUS_PATTERNS)
        )

        # 4. 代码质量检查
        quality_score, complexity_score, quality_warnings = self._assess_python_quality(
            tree, generated_code.code
        )
        warnings.extend(quality_warnings)

        # 5. 确定整体危险等级
        overall_danger_level = self._calculate_overall_danger_level(dangerous_operations)

        # 6. 生成建议
        recommendations = self._generate_recommendations(
            dangerous_operations, warnings, quality_score
        )

        # 7. 决定是否通过审查
        approved = self._should_approve(overall_danger_level, syntax_errors)

        return CodeReviewResult(
            code_id=generated_code.code_id,
            approved=approved,
            overall_danger_level=overall_danger_level,
            dangerous_operations=dangerous_operations,
            syntax_errors=syntax_errors,
            warnings=warnings,
            quality_score=quality_score,
            complexity_score=complexity_score,
            recommendations=recommendations,
        )

    def _review_shell_code(self, generated_code: GeneratedCode) -> CodeReviewResult:
        """审查 Shell 代码"""
        dangerous_operations = self._check_patterns(
            generated_code.code, self.SHELL_DANGEROUS_PATTERNS
        )

        warnings = []

        # 检查是否有未引用的变量
        if re.search(r"\$\w+", generated_code.code):
            warnings.append("使用了变量，确保变量已定义")

        # 检查管道命令
        if "|" in generated_code.code:
            warnings.append("使用了管道命令，确保命令链安全")

        overall_danger_level = self._calculate_overall_danger_level(dangerous_operations)
        approved = self._should_approve(overall_danger_level, [])

        recommendations = self._generate_recommendations(dangerous_operations, warnings, 0.7)

        return CodeReviewResult(
            code_id=generated_code.code_id,
            approved=approved,
            overall_danger_level=overall_danger_level,
            dangerous_operations=dangerous_operations,
            warnings=warnings,
            quality_score=0.7,
            complexity_score=0.5,
            recommendations=recommendations,
        )

    def _analyze_python_ast(
        self, tree: ast.AST, code: str
    ) -> list[DangerousOperation]:
        """分析 Python AST"""
        dangerous_ops = []
        code_lines = code.split("\n")

        for node in ast.walk(tree):
            # 检查函数调用
            if isinstance(node, ast.Call):
                func_name = self._get_function_name(node.func)

                # 检查 eval/exec
                if func_name in ("eval", "exec"):
                    dangerous_ops.append(
                        DangerousOperation(
                            operation=func_name,
                            line_number=node.lineno,
                            danger_level=DangerLevel.CRITICAL,
                            reason=f"使用了 {func_name}，可能执行任意代码",
                            suggestion=f"避免使用 {func_name}，使用安全的替代方案",
                        )
                    )

                # 检查 __import__
                elif func_name == "__import__":
                    dangerous_ops.append(
                        DangerousOperation(
                            operation="__import__",
                            line_number=node.lineno,
                            danger_level=DangerLevel.HIGH,
                            reason="动态导入模块",
                            suggestion="使用静态 import 语句",
                        )
                    )

            # 检查导入语句
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name in ("os", "subprocess", "sys"):
                        # 这些是常用模块，只是警告
                        pass

        return dangerous_ops

    def _get_function_name(self, node: ast.AST) -> str:
        """获取函数名"""
        if isinstance(node, ast.Name):
            return node.id
        elif isinstance(node, ast.Attribute):
            return f"{self._get_function_name(node.value)}.{node.attr}"
        else:
            return ""

    def _check_patterns(
        self, code: str, patterns: dict[str, tuple[DangerLevel, str, str]]
    ) -> list[DangerousOperation]:
        """检查代码中的危险模式"""
        dangerous_ops = []
        lines = code.split("\n")

        for line_num, line in enumerate(lines, start=1):
            for pattern, (danger_level, reason, suggestion) in patterns.items():
                if re.search(pattern, line):
                    # 提取操作名称
                    match = re.search(pattern, line)
                    operation = match.group(0) if match else pattern

                    dangerous_ops.append(
                        DangerousOperation(
                            operation=operation,
                            line_number=line_num,
                            danger_level=danger_level,
                            reason=reason,
                            suggestion=suggestion,
                        )
                    )

        return dangerous_ops

    def _assess_python_quality(
        self, tree: ast.AST, code: str
    ) -> tuple[float, float, list[str]]:
        """评估 Python 代码质量"""
        warnings = []
        quality_score = 1.0
        complexity_score = 1.0

        # 统计代码行数
        lines = [line for line in code.split("\n") if line.strip()]
        line_count = len(lines)

        # 行数过多降低质量分
        if line_count > 100:
            quality_score -= 0.2
            warnings.append("代码行数过多，建议拆分")

        # 统计函数数量
        function_count = sum(1 for node in ast.walk(tree) if isinstance(node, ast.FunctionDef))

        # 没有函数定义
        if function_count == 0 and line_count > 20:
            quality_score -= 0.1
            warnings.append("建议将代码封装到函数中")

        # 统计嵌套深度
        max_depth = self._calculate_max_depth(tree)
        if max_depth > 4:
            complexity_score -= 0.2
            warnings.append(f"嵌套深度过深 ({max_depth})，建议简化逻辑")

        # 检查是否有文档字符串
        has_docstring = False
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                if ast.get_docstring(node):
                    has_docstring = True
                    break

        if function_count > 0 and not has_docstring:
            quality_score -= 0.05
            warnings.append("建议添加文档字符串")

        # 确保分数在 0-1 范围内
        quality_score = max(0.0, min(1.0, quality_score))
        complexity_score = max(0.0, min(1.0, complexity_score))

        return quality_score, complexity_score, warnings

    def _calculate_max_depth(self, tree: ast.AST, current_depth: int = 0) -> int:
        """计算最大嵌套深度"""
        max_depth = current_depth

        for node in ast.iter_child_nodes(tree):
            if isinstance(node, (ast.If, ast.For, ast.While, ast.With, ast.Try)):
                depth = self._calculate_max_depth(node, current_depth + 1)
                max_depth = max(max_depth, depth)
            else:
                depth = self._calculate_max_depth(node, current_depth)
                max_depth = max(max_depth, depth)

        return max_depth

    def _calculate_overall_danger_level(
        self, dangerous_operations: list[DangerousOperation]
    ) -> DangerLevel:
        """计算整体危险等级"""
        if not dangerous_operations:
            return DangerLevel.SAFE

        # 取最高危险等级
        max_level = DangerLevel.SAFE
        level_order = [
            DangerLevel.SAFE,
            DangerLevel.LOW,
            DangerLevel.MEDIUM,
            DangerLevel.HIGH,
            DangerLevel.CRITICAL,
        ]

        for op in dangerous_operations:
            if level_order.index(op.danger_level) > level_order.index(max_level):
                max_level = op.danger_level

        return max_level

    def _generate_recommendations(
        self,
        dangerous_operations: list[DangerousOperation],
        warnings: list[str],
        quality_score: float,
    ) -> list[str]:
        """生成改进建议"""
        recommendations = []

        # 基于危险操作的建议
        if dangerous_operations:
            critical_ops = [op for op in dangerous_operations if op.danger_level == DangerLevel.CRITICAL]
            if critical_ops:
                recommendations.append(
                    f"发现 {len(critical_ops)} 个严重危险操作，必须修复后才能执行"
                )

            high_ops = [op for op in dangerous_operations if op.danger_level == DangerLevel.HIGH]
            if high_ops:
                recommendations.append(
                    f"发现 {len(high_ops)} 个高危操作，建议使用更安全的替代方案"
                )

        # 基于质量分数的建议
        if quality_score < 0.6:
            recommendations.append("代码质量较低，建议重构")
        elif quality_score < 0.8:
            recommendations.append("代码质量一般，可以进一步优化")

        # 添加警告中的建议
        recommendations.extend(warnings[:3])  # 最多添加3个警告

        return recommendations

    def _should_approve(
        self, danger_level: DangerLevel, syntax_errors: list[str]
    ) -> bool:
        """判断是否应该通过审查"""
        # 有语法错误，不通过
        if syntax_errors:
            return False

        # 严重危险，不通过
        if danger_level == DangerLevel.CRITICAL:
            return False

        # 其他情况通过（但可能需要用户确认）
        return True
