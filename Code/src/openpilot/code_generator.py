"""
代码生成器

使用 LLM 根据任务描述生成代码。
"""

import ast
import re
import time
import uuid
from typing import Optional

from openpilot.code_models import (
    CodeGenerationRequest,
    CodeLanguage,
    GeneratedCode,
)


class CodeGenerator:
    """代码生成器"""

    # Python 代码生成模板
    PYTHON_TEMPLATE = """你是一个专业的 Python 代码生成助手。请根据以下任务描述生成 Python 代码。

任务描述：
{task_description}

要求：
1. 生成完整、可执行的 Python 代码
2. 代码应该简洁、高效、易读
3. 包含必要的错误处理
4. 添加适当的注释说明关键逻辑
5. 遵循 PEP 8 代码规范
{constraints}

请只返回 Python 代码，不要包含任何解释文字。代码应该用 ```python 代码块包裹。
"""

    # Shell 代码生成模板
    SHELL_TEMPLATE = """你是一个专业的 Shell 脚本生成助手。请根据以下任务描述生成 Shell 脚本。

任务描述：
{task_description}

要求：
1. 生成完整、可执行的 Shell 脚本
2. 脚本应该健壮、安全
3. 包含必要的错误检查
4. 添加适当的注释
5. 使用 bash 语法
{constraints}

请只返回 Shell 代码，不要包含任何解释文字。代码应该用 ```bash 代码块包裹。
"""

    def __init__(self, llm_client: Optional[object] = None):
        """
        初始化代码生成器

        Args:
            llm_client: LLM 客户端（如果为 None，使用模拟生成）
        """
        self.llm_client = llm_client
        self._generation_count = 0

    def generate_code(self, request: CodeGenerationRequest) -> GeneratedCode:
        """
        生成代码

        Args:
            request: 代码生成请求

        Returns:
            GeneratedCode: 生成的代码
        """
        start_time = time.time()

        # 1. 构建提示词
        prompt = self._build_prompt(request)

        # 2. 调用 LLM 生成代码
        if self.llm_client:
            raw_response = self._call_llm(prompt)
        else:
            # 模拟生成（用于测试）
            raw_response = self._simulate_generation(request)

        # 3. 解析响应，提取代码
        code = self._extract_code(raw_response, request.language)

        # 4. 分析代码元信息
        line_count = len([line for line in code.split("\n") if line.strip()])
        imports = self._extract_imports(code, request.language)
        functions = self._extract_functions(code, request.language)

        # 5. 生成代码 ID
        code_id = f"code_{uuid.uuid4().hex[:8]}"

        # 6. 计算生成时间
        generation_time_ms = int((time.time() - start_time) * 1000)

        # 7. 更新统计
        self._generation_count += 1

        return GeneratedCode(
            code_id=code_id,
            request_id=request.request_id,
            language=request.language,
            code=code,
            line_count=line_count,
            imports=imports,
            functions=functions,
            model_used=self._get_model_name(),
            generation_time_ms=generation_time_ms,
            tokens_used=self._estimate_tokens(prompt, code),
        )

    def _build_prompt(self, request: CodeGenerationRequest) -> str:
        """构建提示词"""
        # 选择模板
        if request.language == CodeLanguage.PYTHON:
            template = self.PYTHON_TEMPLATE
        elif request.language in (CodeLanguage.SHELL, CodeLanguage.BASH):
            template = self.SHELL_TEMPLATE
        else:
            raise ValueError(f"不支持的语言: {request.language}")

        # 构建约束条件
        constraints = []

        if request.max_lines:
            constraints.append(f"6. 代码行数不超过 {request.max_lines} 行")

        if request.allowed_imports:
            imports_str = ", ".join(request.allowed_imports)
            constraints.append(f"7. 只能使用以下模块: {imports_str}")

        if request.forbidden_operations:
            ops_str = ", ".join(request.forbidden_operations)
            constraints.append(f"8. 禁止使用以下操作: {ops_str}")

        if request.context:
            constraints.append(f"9. 上下文信息: {request.context}")

        constraints_text = "\n".join(constraints) if constraints else ""

        # 填充模板
        prompt = template.format(
            task_description=request.task_description,
            constraints=constraints_text,
        )

        return prompt

    def _call_llm(self, prompt: str) -> str:
        """调用 LLM"""
        # 这里应该调用实际的 LLM API
        # 例如: self.llm_client.generate(prompt)
        # 为了演示，这里返回模拟响应
        return self._simulate_llm_response(prompt)

    def _simulate_llm_response(self, prompt: str) -> str:
        """模拟 LLM 响应（用于测试）"""
        if "Python" in prompt:
            return """```python
def process_data(data):
    \"\"\"处理数据\"\"\"
    result = []
    for item in data:
        if item > 0:
            result.append(item * 2)
    return result

if __name__ == "__main__":
    data = [1, 2, 3, -1, 4]
    result = process_data(data)
    print(f"Result: {result}")
```"""
        else:
            return """```bash
#!/bin/bash
# 处理文件

if [ -f "$1" ]; then
    echo "Processing file: $1"
    cat "$1" | wc -l
else
    echo "File not found: $1"
    exit 1
fi
```"""

    def _simulate_generation(self, request: CodeGenerationRequest) -> str:
        """模拟代码生成（用于测试）"""
        if request.language == CodeLanguage.PYTHON:
            # 根据任务描述生成简单的 Python 代码
            if "read" in request.task_description.lower():
                return """```python
def read_file(file_path):
    \"\"\"读取文件内容\"\"\"
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        return content
    except FileNotFoundError:
        print(f"File not found: {file_path}")
        return None
    except Exception as e:
        print(f"Error reading file: {e}")
        return None

if __name__ == "__main__":
    result = read_file("example.txt")
    if result:
        print(result)
```"""
            elif "write" in request.task_description.lower():
                return """```python
def write_file(file_path, content):
    \"\"\"写入文件内容\"\"\"
    try:
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)
        return True
    except Exception as e:
        print(f"Error writing file: {e}")
        return False

if __name__ == "__main__":
    success = write_file("output.txt", "Hello, World!")
    if success:
        print("File written successfully")
```"""
            else:
                return """```python
def main():
    \"\"\"主函数\"\"\"
    print("Task completed")
    return True

if __name__ == "__main__":
    main()
```"""
        else:
            # Shell 脚本
            return """```bash
#!/bin/bash
echo "Task completed"
exit 0
```"""

    def _extract_code(self, response: str, language: CodeLanguage) -> str:
        """从响应中提取代码"""
        # 尝试提取代码块
        patterns = [
            r"```python\n(.*?)```",
            r"```bash\n(.*?)```",
            r"```shell\n(.*?)```",
            r"```\n(.*?)```",
        ]

        for pattern in patterns:
            match = re.search(pattern, response, re.DOTALL)
            if match:
                return match.group(1).strip()

        # 如果没有代码块标记，返回整个响应
        return response.strip()

    def _extract_imports(self, code: str, language: CodeLanguage) -> list[str]:
        """提取导入的模块"""
        imports = []

        if language == CodeLanguage.PYTHON:
            try:
                tree = ast.parse(code)
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        for alias in node.names:
                            imports.append(alias.name)
                    elif isinstance(node, ast.ImportFrom):
                        if node.module:
                            imports.append(node.module)
            except SyntaxError:
                # 如果解析失败，使用正则表达式
                import_pattern = r"^(?:from\s+(\S+)\s+)?import\s+(.+)$"
                for line in code.split("\n"):
                    match = re.match(import_pattern, line.strip())
                    if match:
                        if match.group(1):
                            imports.append(match.group(1))
                        else:
                            imports.extend(
                                [m.strip() for m in match.group(2).split(",")]
                            )

        return list(set(imports))  # 去重

    def _extract_functions(self, code: str, language: CodeLanguage) -> list[str]:
        """提取定义的函数"""
        functions = []

        if language == CodeLanguage.PYTHON:
            try:
                tree = ast.parse(code)
                for node in ast.walk(tree):
                    if isinstance(node, ast.FunctionDef):
                        functions.append(node.name)
            except SyntaxError:
                # 如果解析失败，使用正则表达式
                func_pattern = r"^def\s+(\w+)\s*\("
                for line in code.split("\n"):
                    match = re.match(func_pattern, line.strip())
                    if match:
                        functions.append(match.group(1))
        elif language in (CodeLanguage.SHELL, CodeLanguage.BASH):
            # Shell 函数
            func_pattern = r"^(\w+)\s*\(\s*\)\s*\{"
            for line in code.split("\n"):
                match = re.match(func_pattern, line.strip())
                if match:
                    functions.append(match.group(1))

        return functions

    def _get_model_name(self) -> str:
        """获取模型名称"""
        if self.llm_client and hasattr(self.llm_client, "model_name"):
            return self.llm_client.model_name
        return "simulated"

    def _estimate_tokens(self, prompt: str, code: str) -> int:
        """估算使用的 token 数"""
        # 简单估算：每 4 个字符约等于 1 个 token
        total_chars = len(prompt) + len(code)
        return total_chars // 4

    def get_stats(self) -> dict:
        """获取生成统计"""
        return {
            "total_generations": self._generation_count,
            "model": self._get_model_name(),
        }
