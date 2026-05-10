#!/usr/bin/env python3
"""调试工具执行问题"""

import sys
sys.path.insert(0, '/mnt/c/Users/14235/Desktop/Projects/openPilot/Code/src')

from openpilot.tool_registry import ToolRegistry
from openpilot.builtin_tools import register_builtin_tools
from openpilot.tool_models import ToolCapability
from openpilot.tool_orchestration_models import ToolSelection, SelectionReason

# 初始化工具注册表
registry = ToolRegistry()
register_builtin_tools(registry)

print("=" * 60)
print("工具注册表调试")
print("=" * 60)
print()

# 列出所有注册的工具
print("已注册的工具:")
all_tools = registry.list_all()
for tool in all_tools:
    print(f"  - {tool.name}: {tool.display_name}")

    # 处理能力（可能是字符串或枚举）
    capabilities = []
    for c in tool.capabilities:
        if hasattr(c, 'value'):
            capabilities.append(c.value)
        else:
            capabilities.append(str(c))
    print(f"    能力: {capabilities}")

    # 处理权限（可能是字符串或枚举）
    if hasattr(tool.permission_level, 'value'):
        perm = tool.permission_level.value
    else:
        perm = str(tool.permission_level)
    print(f"    权限: {perm}")

    # 检查执行器
    executor = registry.get_executor(tool.name)
    print(f"    执行器: {'✓ 已注册' if executor else '✗ 未注册'}")
    print()

# 测试工具执行
print("=" * 60)
print("测试工具执行")
print("=" * 60)
print()

# 测试 file_reader
print("测试 file_reader:")
try:
    from openpilot.tool_executor import ToolExecutor

    executor = ToolExecutor(registry)

    # 创建测试选择
    selection = ToolSelection(
        step_id="test-1",
        tool_name="file_reader",
        reason=SelectionReason.CAPABILITY_MATCH,
        confidence=0.9,
        input_params={
            "file_path": "/mnt/c/Users/14235/Desktop/Projects/openPilot/Code/README.md"
        }
    )

    print(f"  执行工具: {selection.tool_name}")
    print(f"  参数: {selection.input_params}")

    result = executor.execute_single(selection)

    print(f"  结果: {'✓ 成功' if result.success else '✗ 失败'}")
    print(f"  状态: {result.status.value}")

    if result.error:
        print(f"  错误类型: {result.error.error_type}")
        print(f"  错误信息: {result.error.error_message}")

    if result.output:
        output_preview = str(result.output)[:200]
        print(f"  输出预览: {output_preview}...")

    # 检查日志字段
    if hasattr(result, 'logs'):
        print(f"  执行日志:")
        for log in result.logs:
            print(f"    [{log.level}] {log.message}")
    elif hasattr(result, 'execution_logs'):
        print(f"  执行日志:")
        for log in result.execution_logs:
            print(f"    [{log.level}] {log.message}")
    else:
        print(f"  执行日志: (无日志字段)")

except Exception as e:
    print(f"  ✗ 执行失败: {e}")
    import traceback
    traceback.print_exc()

print()
print("=" * 60)
