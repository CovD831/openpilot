# Command Registry System

## 概述

统一的命令管理系统，确保所有 CLI 命令在一个地方定义和管理。

## 架构

### 核心组件

1. **CommandRegistry** (`src/ui/commands.py`)
   - 中央命令注册表
   - 管理所有命令及其别名
   - 提供命令查询和验证功能

2. **Command** 数据类
   - `name`: 命令名称（如 `/autopilot`）
   - `aliases`: 命令别名列表（如 `exit`, `quit`, `:q` 都映射到 `/exit`）
   - `description`: 命令描述
   - `usage`: 使用示例
   - `category`: 命令分类
   - `requires_args`: 是否需要参数

3. **CommandCategory** 枚举
   - `PLANNING`: 规划相关命令
   - `EXECUTION`: 执行相关命令
   - `TASK_MANAGEMENT`: 任务管理命令
   - `MEMORY`: 记忆系统命令
   - `SYSTEM`: 系统命令

## 已注册的命令

### 规划与执行
- `/plan <goal>` - 生成任务计划（不执行）
- `/execute <goal>` - 使用完整工作流执行（8阶段管道）
- `/autopilot <goal>` - AGI 模式：完全自主执行

### 任务管理
- `/task` - 任务管理命令
- `/report` - 生成进度报告

### 记忆系统
- `/memory` - 记忆系统状态和管理

### 系统命令
- `/config` - 显示当前 LLM 配置
- `/clear` - 清屏
- `/help` (别名: `/?`) - 显示帮助信息
- `/exit` (别名: `/quit`, `exit`, `quit`, `:q`) - 退出 OpenPilot

## 使用方法

### 添加新命令

在 `src/ui/commands.py` 的 `_initialize_commands()` 方法中添加：

```python
Command(
    name="/mycommand",
    aliases=["/mc"],
    description="My custom command",
    usage="/mycommand <arg>",
    category=CommandCategory.SYSTEM,
    requires_args=True
)
```

### 在 CLI 中使用

```python
from ui.commands import get_all_command_names, get_command, is_valid_command

# 获取所有命令名称（用于自动完成）
commands = get_all_command_names()

# 检查命令是否有效
if is_valid_command(user_input):
    cmd = get_command(user_input)
    if cmd.requires_args and not args:
        print(f"Usage: {cmd.usage}")
```

### 获取帮助文本

```python
from ui.commands import get_command_registry

registry = get_command_registry()
help_text = registry.format_help()
console.print(help_text)
```

## 优势

1. **单一数据源**: 所有命令在一个地方定义，避免不同文件中的重复和不一致
2. **自动完成**: 命令列表自动用于 prompt_toolkit 的自动完成
3. **别名支持**: 轻松定义命令别名（如 `exit` → `/exit`）
4. **分类组织**: 命令按类别组织，便于维护和显示
5. **验证**: 统一的命令验证逻辑
6. **可扩展**: 轻松添加新命令而不修改多个文件

## 修复的问题

- ✅ `/exit` 和 `/autopilot` 现在在下拉菜单中显示
- ✅ 所有命令别名（`exit`, `quit`, `:q`）都被正确识别
- ✅ 命令定义集中管理，避免遗漏
- ✅ 自动完成列表自动包含所有注册的命令

## 未来改进

1. 添加命令处理器（handler）到 Command 类
2. 支持命令参数验证
3. 添加命令权限系统
4. 支持动态命令注册（插件系统）
