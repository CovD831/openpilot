# 源码重构计划

## 目标
将 `src/openpilot/` 扁平结构改为分类存储，提高代码可维护性和隔离性。

## 新的目录结构

```
src/
├── core/                    # 核心模块
│   ├── __init__.py
│   ├── config.py           # 配置管理
│   ├── exceptions.py       # 异常定义
│   ├── llm.py             # LLM 接口
│   └── risk.py            # 风险评估
│
├── memory/                  # 记忆系统
│   ├── __init__.py
│   ├── memory_manager.py
│   ├── memory_retriever.py
│   ├── memory_storage.py
│   └── models.py          # memory_models.py
│
├── planning/                # 规划系统
│   ├── __init__.py
│   ├── planner.py
│   ├── plan_generator.py
│   ├── plan_optimizer.py
│   └── models.py          # planning_models.py
│
├── execution/               # 执行系统
│   ├── __init__.py
│   ├── executor.py        # tool_executor.py
│   ├── orchestrator.py    # tool_orchestrator.py
│   ├── workflow.py        # workflow_executor.py
│   └── models.py          # executor_models.py
│
├── tools/                   # 工具系统
│   ├── __init__.py
│   ├── registry.py        # tool_registry.py
│   ├── builtin.py         # builtin_tools.py
│   └── models.py          # tool_models.py
│
├── validation/              # 验证系统
│   ├── __init__.py
│   ├── validator.py       # result_validator.py
│   └── models.py          # validation_models.py
│
├── reflection/              # 反思系统
│   ├── __init__.py
│   ├── reflector.py       # reflection_engine.py
│   └── models.py          # reflection_models.py
│
├── ui/                      # 用户界面
│   ├── __init__.py
│   ├── cli.py
│   └── terminal.py        # terminal_ui.py
│
├── utils/                   # 工具函数
│   ├── __init__.py
│   └── logging.py         # openpilot_log.py
│
└── __init__.py
```

## 迁移步骤

### Phase 1: 创建新目录结构
1. 创建所有新目录
2. 创建所有 `__init__.py` 文件

### Phase 2: 移动文件
1. 移动核心模块到 `core/`
2. 移动记忆模块到 `memory/`
3. 移动规划模块到 `planning/`
4. 移动执行模块到 `execution/`
5. 移动工具模块到 `tools/`
6. 移动验证模块到 `validation/`
7. 移动反思模块到 `reflection/`
8. 移动界面模块到 `ui/`
9. 移动日志模块到 `utils/`

### Phase 3: 更新导入路径
1. 更新所有文件中的 import 语句
2. 从 `from openpilot.xxx` 改为 `from core.xxx` 或 `from memory.xxx` 等

### Phase 4: 测试验证
1. 运行 CLI 测试所有命令
2. 测试 /autopilot 工作流
3. 确认所有功能正常

### Phase 5: 清理
1. 删除旧的 `src/openpilot/` 目录
2. 更新文档中的路径引用

## 增强日志输出

在以下位置增加详细日志：

1. **WorkflowExecutor** (`execution/workflow.py`)
   - 每个阶段开始/结束时输出详细信息
   - 工具选择和编排决策
   - 执行失败时的完整上下文

2. **ToolExecutor** (`execution/executor.py`)
   - 工具执行前的参数验证
   - 执行过程中的中间状态
   - 执行失败时的详细错误信息

3. **MemoryManager** (`memory/memory_manager.py`)
   - 记忆检索的查询条件和结果
   - 记忆保存的内容摘要

4. **PlanGenerator** (`planning/plan_generator.py`)
   - 计划生成的推理过程
   - LLM 调用的输入输出

## 日志格式规范

```python
# 阶段日志
logger.info(f"[{stage_name}] 开始执行")
logger.info(f"[{stage_name}] 输入: {input_summary}")
logger.info(f"[{stage_name}] 输出: {output_summary}")
logger.info(f"[{stage_name}] 完成 (耗时: {duration}s)")

# 错误日志
logger.error(f"[{stage_name}] 执行失败: {error_message}")
logger.error(f"[{stage_name}] 错误类型: {error_type}")
logger.error(f"[{stage_name}] 堆栈: {stack_trace}")
logger.error(f"[{stage_name}] 上下文: {context_info}")

# 决策日志
logger.info(f"[决策] {decision_point}: 选择 {choice} (原因: {reason})")
```
