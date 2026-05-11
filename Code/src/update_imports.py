#!/usr/bin/env python3
"""批量更新导入路径的脚本"""

import os
import re
from pathlib import Path

# 导入映射表
IMPORT_MAPPING = {
    # Core 模块
    'from openpilot.llm import': 'from core.llm import',
    'from openpilot.config import': 'from core.config import',
    'from openpilot.exceptions import': 'from core.exceptions import',
    'from openpilot.openpilot_log import': 'from core.openpilot_log import',
    'from openpilot.risk import': 'from core.risk import',
    'from openpilot.semantic_analyzer import': 'from core.semantic_analyzer import',

    # Planning 模块
    'from openpilot.planner import': 'from planning.planner import',
    'from openpilot.timeline import': 'from planning.timeline import',
    'from openpilot.clarifier import': 'from planning.clarifier import',
    'from openpilot.goal_understanding import': 'from planning.goal_understanding import',

    # Memory 模块
    'from openpilot.memory_store import': 'from memory.memory_store import',

    # Tools 模块
    'from openpilot.tool_registry import': 'from tools.tool_registry import',
    'from openpilot.tool_selector import': 'from tools.tool_selector import',
    'from openpilot.tool_orchestrator import': 'from tools.tool_orchestrator import',
    'from openpilot.tool_executor import': 'from tools.tool_executor import',
    'from openpilot.builtin_tools import': 'from tools.builtin_tools import',

    # Execution 模块
    'from openpilot.workflow_executor import': 'from execution.workflow_executor import',
    'from openpilot.code_executor import': 'from execution.code_executor import',
    'from openpilot.code_generator import': 'from execution.code_generator import',
    'from openpilot.code_reviewer import': 'from execution.code_reviewer import',

    # Validation 模块
    'from openpilot.result_validator import': 'from validation.result_validator import',
    'from openpilot.output_validator import': 'from validation.output_validator import',
    'from openpilot.feedback_collector import': 'from validation.feedback_collector import',
    'from openpilot.reflection_analyzer import': 'from validation.reflection_analyzer import',
    'from openpilot.strategy_optimizer import': 'from validation.strategy_optimizer import',

    # Autonomy 模块
    'from openpilot.autonomy_controller import': 'from autonomy.autonomy_controller import',

    # Reporting 模块
    'from openpilot.progress_report import': 'from reporting.progress_report import',
    'from openpilot.task_log import': 'from reporting.task_log import',
    'from openpilot.reminder_scheduler import': 'from reporting.reminder_scheduler import',

    # UI 模块
    'from openpilot.terminal_ui import': 'from ui.terminal_ui import',
    'from openpilot.openpilot_session import': 'from ui.openpilot_session import',

    # Models 模块
    'from openpilot.planner_models import': 'from models.planner_models import',
    'from openpilot.memory_models import': 'from models.memory_models import',
    'from openpilot.tool_models import': 'from models.tool_models import',
    'from openpilot.tool_orchestration_models import': 'from models.tool_orchestration_models import',
    'from openpilot.executor_models import': 'from models.executor_models import',
    'from openpilot.code_models import': 'from models.code_models import',
    'from openpilot.validation_models import': 'from models.validation_models import',
    'from openpilot.reflection_models import': 'from models.reflection_models import',
    'from openpilot.autonomy_models import': 'from models.autonomy_models import',
    'from openpilot.reminder_models import': 'from models.reminder_models import',
}

def update_file(file_path):
    """更新单个文件的导入"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()

        original_content = content

        # 应用所有导入映射
        for old_import, new_import in IMPORT_MAPPING.items():
            content = content.replace(old_import, new_import)

        # 如果内容有变化，写回文件
        if content != original_content:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(content)
            return True
        return False
    except Exception as e:
        print(f"Error updating {file_path}: {e}")
        return False

def main():
    """主函数"""
    src_dir = Path(__file__).parent
    updated_count = 0

    # 遍历所有模块目录
    modules = ['core', 'planning', 'memory', 'tools', 'execution',
               'validation', 'autonomy', 'reporting', 'ui', 'models']

    for module in modules:
        module_dir = src_dir / module
        if not module_dir.exists():
            continue

        # 更新该模块下的所有 Python 文件
        for py_file in module_dir.glob('*.py'):
            if py_file.name == '__init__.py':
                continue
            if update_file(py_file):
                print(f"✓ Updated: {py_file.relative_to(src_dir)}")
                updated_count += 1

    print(f"\n✓ Total files updated: {updated_count}")

if __name__ == '__main__':
    main()
