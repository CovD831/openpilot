# OpenPilot 代码结构重构文档

**生成时间**: 2026-05-12

**目的**: 用于代码重构和性能优化分析

## 📋 使用说明

1. 请仔细阅读每个模块、类和函数的说明
2. 在 `**重构意见**` 部分添加你的建议，包括：
   - 🔴 **删除**: 标记需要删除的冗余代码
   - 🟡 **合并**: 标记可以合并的重复功能
   - 🟢 **优化**: 标记性能优化点
   - 🔵 **重构**: 标记需要重构的代码结构
   - ⚪ **保留**: 标记需要保留的核心功能
3. 完成后将此文档发回给我进行重构

---

## 📊 代码统计

- **总文件数**: 67
- **总类数**: 168
- **总函数数**: 92

---

## 📁 agents/

### 📄 `orchestrator.py`

**模块说明**: Agent orchestrator for coordinating multiple agents.

#### 类 (Classes)

##### `AgentOrchestrator`

**说明**: Orchestrates multiple agents working on tasks.

**方法列表**:

- `__init__(max_concurrent_tasks, task_timeout)`
  - Initialize orchestrator.
- `register_agent(agent)`
  - Register an agent.
- `unregister_agent(agent_id)`
  - Unregister an agent.
- `set_task_executor(executor)`
  - Set task executor function.
- `assign_task(task, agent_id)`
  - Assign a task to an agent.
- `execute_task_graph(task_graph, context)`
  - Execute tasks in a task graph.
- `monitor_progress()`
  - Monitor execution progress.
- `handle_task_failure(task, error)`
  - Handle task failure.
- `get_task_result(task_id)`
  - Get result for a task.
- `get_all_results()`
  - Get all task results.
- `clear_completed_tasks()`
  - Clear completed tasks from memory.
- `_find_suitable_agent(task)`
  - Find a suitable agent for a task.
- `_execute_task_sync(task, context)`
  - Execute a task synchronously.

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

---

### 📄 `task_decomposer.py`

**模块说明**: Task decomposition agent for breaking down complex tasks.

#### 类 (Classes)

##### `TaskDecomposer`

**说明**: Agent for decomposing complex tasks into subtasks.

**方法列表**:

- `__init__(llm_client, max_decomposition_depth, min_subtask_complexity)`
  - Initialize task decomposer.
- `should_decompose(task, current_depth)`
  - Determine if a task should be decomposed.
- `decompose(task_description, context, parent_task_id)`
  - Decompose a task into subtasks.
- `build_task_graph(tasks)`
  - Build a task dependency graph.
- `get_execution_order(task_graph)`
  - Get execution order for tasks using topological sort.
- `get_ready_tasks(tasks)`
  - Get tasks that are ready to execute.
- `assemble_results(parent_task, subtasks)`
  - Assemble results from subtasks.
- `_estimate_complexity(task)`
  - Estimate task complexity using LLM.
- `_generate_decomposition(task, context)`
  - Generate task decomposition using LLM.
- `_fallback_decomposition(task)`
  - Generate simple fallback decomposition.
- `_generate_graph_summary(graph, tasks)`
  - Generate summary of task graph.

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

---

## 📁 autonomy/

### 📄 `autonomy_controller.py`

**模块说明**: Autonomy controller for OP-19.

Implements confidence calculation, autonomy level decision-making,
and feedback-driven learning.

#### 类 (Classes)

##### `AutonomyController`

**说明**: Controls autonomy decisions based on confidence and user preferences.

**方法列表**:

- `__init__(memory_store, autonomy_profile)`
- `_default_profile()`
  - Create default autonomy profile with conservative settings.
- `decide_autonomy(step, task_card, goal)`
  - Decide autonomy level for a step.
- `_calculate_confidence_factors(step, task_card, goal)`
  - Calculate confidence based on multiple factors.
- `_get_historical_success_rate(task_type, risk_level)`
  - Get historical success rate for similar tasks from memory.
- `_get_preference_match_score(task_card, goal)`
  - Get preference match score from long-term memory.
- `_calculate_risk_penalty(risk_level)`
  - Calculate confidence penalty based on risk level.
- `_calculate_recency_bonus(task_type)`
  - Calculate bonus for recent similar successes.
- `_calculate_frequency_bonus(task_type)`
  - Calculate bonus for frequently used patterns.
- `_get_base_autonomy_level(risk_level, task_type)`
  - Get base autonomy level from profile.
- `_adjust_autonomy_by_confidence(base_level, confidence, risk_level)`
  - Adjust autonomy level based on confidence.
- `_build_decision_reason(base_level, final_level, factors)`
  - Build human-readable decision reason.
- `_build_intervention_reason(risk_level, confidence)`
  - Build human-readable intervention reason.
- `record_feedback(feedback, step, task_card)`
  - Record user feedback and update confidence.

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

---

## 📁 core/

### 📄 `embedding.py`

**模块说明**: Embedding service for semantic search and similarity matching.

This module provides embedding capabilities for:
- Memory vault semantic search
- Text similarity computation
- Batch processing with ca

#### 类 (Classes)

##### `EmbeddingError` ← `OpenPilotError`

**说明**: Embedding-related errors.

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

##### `EmbeddingService`

**说明**: Service for generating and managing text embeddings.

**方法列表**:

- `__init__(provider, model, cache_dir, batch_size, timeout)`
  - Initialize embedding service.
- `_get_openai_dimension(model)`
  - Get embedding dimension for OpenAI model.
- `_get_cache_key(text)`
  - Generate cache key for text.
- `_load_cache()`
  - Load embeddings cache from disk.
- `_save_cache()`
  - Save embeddings cache to disk.
- `embed_text(text, use_cache)`
  - Generate embedding for a single text.
- `embed_batch(texts, use_cache, show_progress)`
  - Generate embeddings for multiple texts.
- `compute_similarity(emb1, emb2, method)`
  - Compute similarity between two embeddings.
- `find_similar(query_emb, candidates, top_k, method, threshold)`
  - Find most similar embeddings to a query.
- `get_dimension()`
  - Get embedding dimension.
- `clear_cache()`
  - Clear the embedding cache.
- `get_cache_size()`
  - Get number of cached embeddings.
- `get_cache_stats()`
  - Get cache statistics.
- `__repr__()`
  - String representation.

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

---

### 📄 `graph.py`

**模块说明**: Graph data structure for OpenPilot.

This module provides a flexible, reusable graph data structure for:
- Memory vault relationships
- Task dependency graphs
- Agent orchestration

#### 类 (Classes)

##### `GraphType` ← `str, Enum`

**说明**: Graph type enumeration.

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

##### `GraphNode`

**说明**: Node in a graph structure.

**方法列表**:

- `to_dict()`
  - Convert node to dictionary.
- `from_dict(cls, data)`
  - Create node from dictionary.
- `update(data, metadata)`
  - Update node data and metadata.

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

##### `GraphEdge`

**说明**: Edge in a graph structure.

**方法列表**:

- `to_dict()`
  - Convert edge to dictionary.
- `from_dict(cls, data)`
  - Create edge from dictionary.
- `reverse()`
  - Create a reversed edge.

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

##### `Graph`

**说明**: Generic graph data structure with support for directed and undirected graphs.

**方法列表**:

- `__init__(graph_type)`
  - Initialize graph.
- `add_node(node)`
  - Add a node to the graph.
- `add_edge(edge)`
  - Add an edge to the graph.
- `get_node(node_id)`
  - Get a node by ID.
- `get_edge(source_id, target_id, edge_type)`
  - Get an edge between two nodes.
- `remove_node(node_id)`
  - Remove a node and all its edges.
- `remove_edge(source_id, target_id, edge_type)`
  - Remove an edge.
- `get_neighbors(node_id, edge_type)`
  - Get neighboring nodes.
- `get_predecessors(node_id, edge_type)`
  - Get predecessor nodes (nodes with edges pointing to this node).
- `get_all_nodes()`
  - Get all nodes in the graph.
- `get_all_edges()`
  - Get all edges in the graph.
- `node_count()`
  - Get number of nodes.
- `edge_count()`
  - Get number of edges.
- `has_node(node_id)`
  - Check if node exists.
- `has_edge(source_id, target_id, edge_type)`
  - Check if edge exists.
- `query_nodes(filter_fn)`
  - Query nodes using a filter function.
- `bfs(start_id, visit_fn)`
  - Breadth-first search traversal.
- `dfs(start_id, visit_fn)`
  - Depth-first search traversal.
- `find_path(start_id, end_id)`
  - Find a path between two nodes using BFS.
- `topological_sort()`
  - Perform topological sort on the graph.
- `detect_cycles()`
  - Detect cycles in the graph.
- `get_subgraph(node_ids)`
  - Extract a subgraph containing specified nodes.
- `to_dict()`
  - Convert graph to dictionary.
- `from_dict(cls, data)`
  - Create graph from dictionary.
- `save_json(file_path)`
  - Save graph to JSON file.
- `load_json(cls, file_path)`
  - Load graph from JSON file.
- `save_pickle(file_path)`
  - Save graph to pickle file.
- `load_pickle(cls, file_path)`
  - Load graph from pickle file.
- `__repr__()`
  - String representation.

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

---

### 📄 `instrumented_llm.py`

**模块说明**: Instrumented LLM client with UI progress tracking.

#### 类 (Classes)

##### `InstrumentedLLMClient` ← `LLMClient`

**说明**: LLM client that reports progress to UI.

**方法列表**:

- `__init__(settings, tracker)`
  - Initialize instrumented LLM client.
- `complete(request, use_cache, stream)`
  - Complete request with progress tracking.

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

---

### 📄 `semantic_analyzer.py`

**模块说明**: LLM-backed semantic analysis for OpenPilot goals and plan steps.

#### 类 (Classes)

##### `CompletionClient` ← `Protocol`

**方法列表**:

- `complete(request)`
  - Return a normalized LLM response.

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

##### `GoalSemanticAnalysis` ← `BaseModel`

**说明**: Semantic classification for a user goal.

**方法列表**:

- `log_payload()`

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

##### `StepSemanticAnalysis` ← `BaseModel`

**说明**: Semantic classification for a planner step.

**方法列表**:

- `log_payload()`

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

##### `SemanticAnalyzer`

**说明**: Use the configured LLM for goal and plan-step semantic analysis.

**方法列表**:

- `__init__(llm_client)`
- `analyze_goal(goal, constraints)`
- `analyze_plan_step(goal, step, available_tools)`
- `_response_payload(response)`

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

---

## 📁 execution/

### 📄 `code_executor.py`

**模块说明**: 代码执行器

在沙箱环境中安全执行生成的代码。

#### 类 (Classes)

##### `CodeExecutor`

**说明**: 代码执行器

**方法列表**:

- `__init__(default_timeout, max_memory_mb, enable_sandbox)`
  - 初始化执行器
- `execute(generated_code, input_data, timeout)`
  - 执行代码
- `_execute_python(code, input_data, timeout, execution_id)`
  - 执行 Python 代码
- `_execute_shell(code, input_data, timeout, execution_id)`
  - 执行 Shell 代码
- `execute_with_retry(generated_code, input_data, max_retries)`
  - 执行代码（带重试）
- `validate_output(result, expected_output, output_validator)`
  - 验证输出
- `get_stats()`
  - 获取执行统计

**重构意见**:
```
The code executor should also take a env parameter, which provides a virtual env to execute the code (e.g., conda) to correctly run the code. For those codes that do not need an env, just pass None as the env parameter.
```

---

### 📄 `code_generator.py`

**模块说明**: 代码生成器

使用 LLM 根据任务描述生成代码。

#### 类 (Classes)

##### `CodeGenerator`

**说明**: 代码生成器

**方法列表**:

- `__init__(llm_client)`
  - 初始化代码生成器
- `generate_code(request)`
  - 生成代码
- `_build_prompt(request)`
  - 构建提示词
- `_call_llm(prompt)`
  - 调用 LLM
- `_simulate_llm_response(prompt)`
  - 模拟 LLM 响应（用于测试）
- `_simulate_generation(request)`
  - 模拟代码生成（用于测试）
- `_extract_code(response, language)`
  - 从响应中提取代码
- `_extract_imports(code, language)`
  - 提取导入的模块
- `_extract_functions(code, language)`
  - 提取定义的函数
- `_get_model_name()`
  - 获取模型名称
- `_estimate_tokens(prompt, code)`
  - 估算使用的 token 数
- `get_stats()`
  - 获取生成统计

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

---

### 📄 `code_reviewer.py`

**模块说明**: 代码审查器

对生成的代码进行静态分析和安全检查。

#### 类 (Classes)

##### `CodeReviewer`

**说明**: 代码审查器

**方法列表**:

- `__init__()`
  - 初始化审查器
- `review_code(generated_code)`
  - 审查代码
- `_review_python_code(generated_code)`
  - 审查 Python 代码
- `_review_shell_code(generated_code)`
  - 审查 Shell 代码
- `_analyze_python_ast(tree, code)`
  - 分析 Python AST
- `_get_function_name(node)`
  - 获取函数名
- `_check_patterns(code, patterns)`
  - 检查代码中的危险模式
- `_assess_python_quality(tree, code)`
  - 评估 Python 代码质量
- `_calculate_max_depth(tree, current_depth)`
  - 计算最大嵌套深度
- `_calculate_overall_danger_level(dangerous_operations)`
  - 计算整体危险等级
- `_generate_recommendations(dangerous_operations, warnings, quality_score)`
  - 生成改进建议
- `_should_approve(danger_level, syntax_errors)`
  - 判断是否应该通过审查

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

---

### 📄 `intelligent_autopilot.py`

**模块说明**: Intelligent Autopilot Executor using Task Decomposition Agent.

Replaces the rigid 8-stage workflow with dynamic task decomposition and execution.

#### 类 (Classes)

##### `IntelligentAutopilot`

**说明**: Intelligent autopilot using dynamic task decomposition.

**方法列表**:

- `__init__(llm_client, console, auto_approve, logger, log_file, use_enhanced_ui)`
  - Initialize intelligent autopilot.
- `execute(goal, context)`
  - Execute goal using intelligent task decomposition.
- `_execute_with_enhanced_ui_v2(goal, context)`
- `_execute_standard(goal, context)`
  - Execute with standard console output.
- `_execute_tasks(tasks, goal)`
  - Execute tasks using orchestrator.
- `_execute_tasks_enhanced_ui(tasks, execution_order, goal)`
  - Execute tasks with enhanced UI (updates layout instead of printing).
- `_execute_tasks_standard(tasks, execution_order, goal)`
  - Execute tasks with standard console output.
- `_map_reason_to_enum(reason_text)`
  - Map free-form reason text to SelectionReason enum value.
- `_execute_task(task, context)`
  - Execute a single task by generating and executing tool calls.
- `_format_tools_for_llm(tools)`
  - Format available tools for LLM prompt.
- `_resolve_selection_inputs(selection, step_outputs)`
  - Resolve tool inputs from previous step outputs.
- `_show_start_panel(goal)`
  - Show start panel.
- `_show_task_tree(decomposition)`
  - Show task decomposition tree.
- `_show_completion_summary(decomposition, results)`
  - Show completion summary.
- `_build_task_graph_for_ui(decomposition)`
  - Build task graph structure for enhanced UI display.

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

---

### 📄 `workflow_executor.py`

**模块说明**: 工作流执行器

整合Phase 2所有模块，提供完整的8阶段执行流程。

#### 类 (Classes)

##### `WorkflowStage`

**说明**: 工作流阶段

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

##### `WorkflowExecutor`

**说明**: 工作流执行器

**方法列表**:

- `__init__(llm_client, console, dry_run, auto_approve, save_report, logger, log_file)`
  - 初始化工作流执行器
- `execute(goal, constraints)`
  - 执行完整的工作流
- `_show_start_panel(goal)`
  - 显示开始面板
- `_stage_1_goal_understanding(goal, constraints)`
  - 阶段1: 目标理解
- `_stage_2_memory_retrieval(task_card)`
  - 阶段2: 记忆检索
- `_stage_3_plan_generation(goal, constraints, memories)`
  - 阶段3: 计划生成
- `_stage_4_tool_orchestration(plan)`
  - 阶段4: 工具编排
- `_stage_5_execution(orchestration_plan)`
  - 阶段5: 执行步骤
- `_stage_6_validation(execution_results)`
  - 阶段6: 验证结果
- `_stage_7_reflection(execution_results, validation_results)`
  - 阶段7: 生成反思
- `_stage_8_logging(task_card, plan, execution_results, validation_results, reflections)`
  - 阶段8: 写入日志
- `_planned_steps_payload(plan)`
  - Create log-safe planned step payloads.
- `_tool_selections_payload(orchestration_plan)`
  - Create log-safe tool selection payloads.
- `_input_preview(input_params)`
  - Summarize inputs without logging large content.
- `_resolve_selection_with_diagnostics(selection, step_outputs)`
  - Resolve chained inputs and return diagnostics for logs.
- `_resolve_selection_inputs(selection, step_outputs)`
  - Fill tool inputs from a previous step output when source_step_id is set.
- `_missing_required_inputs(tool_name, input_params)`
  - Return missing required inputs before executing a built-in tool.
- `_get_tool_display_name(tool_name)`
  - Get a user-friendly display name for a tool.
- `_create_missing_input_result(selection, input_resolution)`
  - Create a failed execution result for missing required inputs.
- `_is_empty_llm_output(result)`
  - Return true when an LLM tool succeeded without useful text.
- `_retry_empty_llm_output(selection, first_result)`
  - Retry an empty LLM output once with a shorter text payload.
- `_create_empty_llm_result(selection, last_result)`
  - Create a clear failure for repeated empty LLM output.
- `_extract_files(output)`
  - Extract file paths from tool output.
- `_coerce_output_to_text(output)`
  - Convert a previous tool output into text for downstream tools.
- `_read_and_combine_files(file_paths)`
  - Read multiple files and combine their content.
- `_execution_log_payload(result)`
  - Create a compact, non-secret execution log payload.
- `_summarize_output(output)`
  - Summarize output shape without logging full content.
- `_preview_output(output, max_chars)`
  - Create a bounded text preview for diagnostics.
- `_workflow_success(execution_results, validation_results)`
  - Return true only when execution and validation actually pass.
- `_show_completion_summary(task_card, execution_results, validation_results)`
  - 显示完成摘要
- `_save_report(task_card, execution_results, validation_results)`
  - 保存执行报告
- `_generate_report(task_card, execution_results, validation_results)`
  - 生成执行报告

**重构意见**:
```
我们现在不使用这种固定的8阶段执行流程了，你应该将这个功能移除
```

---

## 📁 memory/

### 📄 `context_compressor.py`

**模块说明**: Context compression module for OpenPilot.

This module provides Claude Code-style context compression to manage token budgets.
Inspired by Claude Code's compaction system.

#### 类 (Classes)

##### `CompressionResult`

**说明**: Result of context compression.

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

##### `ContextCompressor`

**说明**: Compresses conversation context to manage token budget.

**方法列表**:

- `__init__(llm_client, compression_threshold, min_preserved_messages, target_compression_ratio)`
  - Initialize context compressor.
- `should_compress(messages)`
  - Check if compression is needed.
- `estimate_tokens(messages)`
  - Estimate token count for messages.
- `compress(messages)`
  - Compress context messages.
- `_generate_summary(messages)`
  - Generate summary of messages using LLM.
- `_fallback_summary(messages)`
  - Generate fallback summary without LLM.
- `_count_message_types(messages)`
  - Count message types.
- `compress_with_preservation(messages, preserve_patterns)`
  - Compress context while preserving messages matching patterns.
- `get_compression_stats(messages)`
  - Get compression statistics without actually compressing.

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

---

### 📄 `memory_store.py`

**模块说明**: Local JSONL-based memory storage for the four-layer memory system.

#### 类 (Classes)

##### `MemoryStore`

**说明**: Local file-based memory storage using JSONL format.

**方法列表**:

- `__init__(data_dir)`
  - Initialize memory store.
- `save(memory)`
  - Save a memory record.
- `load_all(memory_type)`
  - Load all memories of a specific type.
- `query(query, memory_types, tags, limit)`
  - Query memories by keyword matching.
- `update_usage(memory_id, memory_type)`
  - Update usage count and last_used timestamp for a memory.
- `delete(memory_id, memory_type)`
  - Delete a memory record.
- `clear_short_term()`
  - Clear all short-term memories (e.g., at session end).
- `_rewrite_file(memory_type, memories)`
  - Rewrite entire memory file with updated records.
- `get_by_id(memory_id, memory_type)`
  - Get a specific memory by ID.

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

---

### 📄 `memory_vault.py`

**模块说明**: Memory vault with graph-based structure and semantic search.

This module provides the core memory vault functionality with:
- Graph-based memory storage
- Semantic search using embeddings
- Memory re

#### 类 (Classes)

##### `MemoryVault`

**说明**: Graph-based memory vault with semantic search.

**方法列表**:

- `__init__(embedding_service, storage_dir, auto_relate, similarity_threshold)`
  - Initialize memory vault.
- `add_memory(content, memory_type, tags, confidence, metadata)`
  - Add a new memory to the vault.
- `recall(query, top_k, memory_types, min_confidence, boost_recent, boost_frequent)`
  - Recall memories relevant to query.
- `update_memory(memory_id, content, tags, confidence, metadata)`
  - Update an existing memory.
- `delete_memory(memory_id)`
  - Delete a memory.
- `find_related(memory_id, max_depth, relationship_types)`
  - Find memories related to a given memory.
- `detect_contradictions(threshold)`
  - Detect potentially contradicting memories.
- `get_memory_sketch(max_items)`
  - Generate memory sketch for short memory.
- `get_statistics()`
  - Get memory vault statistics.
- `_auto_relate_memory(memory_id, embedding)`
  - Automatically detect and create relationships.
- `_get_memory_age_days(memory)`
  - Get memory age in days.
- `_save_vault()`
  - Save memory vault to disk.
- `_load_vault()`
  - Load memory vault from disk.

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

---

### 📄 `short_memory.py`

**模块说明**: Short memory module for OpenPilot.

This module provides short-term memory management including:
- Git information collection
- Context management
- Memory sketch generation

#### 类 (Classes)

##### `GitInfo`

**说明**: Git repository information.

**方法列表**:

- `to_dict()`
  - Convert to dictionary.
- `to_prompt_text()`
  - Convert to human-readable prompt text.

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

##### `GitInfoCollector`

**说明**: Collects git repository information.

**方法列表**:

- `__init__(repo_path)`
  - Initialize collector.
- `_run_git_command()`
  - Run a git command and return output.
- `collect()`
  - Collect git information.

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

##### `Message` ← `BaseModel`

**说明**: A message in the conversation context.

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

##### `ContextManager`

**说明**: Manages conversation context.

**方法列表**:

- `__init__(max_messages)`
  - Initialize context manager.
- `add_message(role, content, metadata)`
  - Add a message to context.
- `get_messages(limit)`
  - Get messages from context.
- `get_recent_messages(count)`
  - Get recent messages.
- `clear()`
  - Clear all messages.
- `mark_compression_boundary()`
  - Mark current position as compression boundary.
- `get_messages_after_compression()`
  - Get messages after last compression boundary.
- `to_prompt_text(limit)`
  - Convert context to prompt text.

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

##### `MemorySketchGenerator`

**说明**: Generates memory sketch from memory vault.

**方法列表**:

- `__init__(max_items)`
  - Initialize generator.
- `generate(memories)`
  - Generate memory sketch.

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

##### `ShortMemory`

**说明**: Short-term memory management.

**方法列表**:

- `__init__(repo_path, max_context_messages)`
  - Initialize short memory.
- `get_git_info(use_cache)`
  - Get git repository information.
- `get_context(limit)`
  - Get conversation context.
- `add_message(role, content, metadata)`
  - Add message to context.
- `get_memory_sketch(memories)`
  - Get memory sketch.
- `update_memory_sketch(memories)`
  - Update cached memory sketch.
- `to_prompt_context(include_git, include_sketch)`
  - Convert short memory to prompt context.
- `clear_cache()`
  - Clear cached information.

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

---

## 📁 models/

### 📄 `autonomy_models.py`

**模块说明**: Autonomy decision models for OP-19.

Defines data structures for autonomy level decisions, confidence scoring,
and user preference tracking.

#### 类 (Classes)

##### `AutonomyLevel` ← `str, Enum`

**说明**: Autonomy level for task execution.

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

##### `AutonomyDecision` ← `BaseModel`

**说明**: Decision about whether and how to execute a step autonomously.

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

##### `PreferenceSignal` ← `BaseModel`

**说明**: A signal indicating user preference from past behavior.

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

##### `AutonomyProfile` ← `BaseModel`

**说明**: System-wide autonomy configuration based on learned preferences.

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

##### `UserFeedback` ← `BaseModel`

**说明**: User feedback on an autonomy decision or execution result.

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

##### `ConfidenceFactors` ← `BaseModel`

**说明**: Factors contributing to confidence calculation.

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

---

### 📄 `code_models.py`

**模块说明**: 代码生成数据模型

定义代码生成、审查、执行相关的数据结构。

#### 类 (Classes)

##### `CodeLanguage` ← `str, Enum`

**说明**: 代码语言

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

##### `DangerLevel` ← `str, Enum`

**说明**: 危险等级

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

##### `CodeGenerationRequest` ← `BaseModel`

**说明**: 代码生成请求

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

##### `GeneratedCode` ← `BaseModel`

**说明**: 生成的代码

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

##### `DangerousOperation` ← `BaseModel`

**说明**: 危险操作

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

##### `CodeReviewResult` ← `BaseModel`

**说明**: 代码审查结果

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

##### `CodeExecutionResult` ← `BaseModel`

**说明**: 代码执行结果

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

##### `CodeFixSuggestion` ← `BaseModel`

**说明**: 代码修复建议

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

##### `CodeCacheEntry` ← `BaseModel`

**说明**: 代码缓存条目

**方法列表**:

- `success_rate()`
  - 成功率

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

##### `CodeGenerationSummary` ← `BaseModel`

**说明**: 代码生成摘要

**方法列表**:

- `generation_success_rate()`
  - 生成成功率
- `execution_success_rate()`
  - 执行成功率
- `cache_hit_rate()`
  - 缓存命中率

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

---

### 📄 `executor_models.py`

**模块说明**: 执行器数据模型

定义工具执行相关的数据结构，包括执行上下文、结果、日志等。

#### 类 (Classes)

##### `ExecutionStatus` ← `str, Enum`

**说明**: 执行状态

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

##### `ExecutionPriority` ← `str, Enum`

**说明**: 执行优先级

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

##### `ResourceType` ← `str, Enum`

**说明**: 资源类型

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

##### `ExecutionContext` ← `BaseModel`

**说明**: 执行上下文

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

##### `ResourceUsage` ← `BaseModel`

**说明**: 资源使用情况

**方法列表**:

- `update_peaks()`
  - 更新峰值

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

##### `ExecutionLog` ← `BaseModel`

**说明**: 执行日志

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

##### `ExecutionError` ← `BaseModel`

**说明**: 执行错误

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

##### `ExecutionResult` ← `BaseModel`

**说明**: 执行结果

**方法列表**:

- `add_log(level, message, details)`
  - 添加日志
- `mark_success(output)`
  - 标记为成功
- `mark_failed(error)`
  - 标记为失败
- `mark_timeout(timeout_seconds)`
  - 标记为超时

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

##### `ParallelExecutionResult` ← `BaseModel`

**说明**: 并行执行结果

**方法列表**:

- `from_results(cls, group_id, results)`
  - 从执行结果列表创建

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

##### `ExecutionPlan` ← `BaseModel`

**说明**: 执行计划

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

##### `ExecutionSummary` ← `BaseModel`

**说明**: 执行摘要

**方法列表**:

- `success_rate()`
  - 成功率
- `average_duration_seconds()`
  - 平均执行时长

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

---

### 📄 `memory_models.py`

**模块说明**: Pydantic models for the four-layer memory system.

#### 类 (Classes)

##### `MemoryType` ← `str, Enum`

**说明**: Memory type taxonomy aligned with Claude Code.

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

##### `MemoryRecord` ← `BaseModel`

**说明**: A single memory entry.

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

##### `MemoryQueryResult` ← `BaseModel`

**说明**: Result of memory retrieval.

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

##### `MemoryUpdateProposal` ← `BaseModel`

**说明**: Proposal for updating memory.

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

---

### 📄 `reflection_models.py`

**模块说明**: 反思与优化数据模型

定义反思条目、优化策略、性能指标、学习记录等数据结构。

#### 类 (Classes)

##### `ReflectionType` ← `str, Enum`

**说明**: 反思类型

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

##### `OptimizationTarget` ← `str, Enum`

**说明**: 优化目标

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

##### `LearningStatus` ← `str, Enum`

**说明**: 学习状态

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

##### `StrategyType` ← `str, Enum`

**说明**: 策略类型

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

##### `ReflectionEntry` ← `BaseModel`

**说明**: 反思条目

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

##### `OptimizationStrategy` ← `BaseModel`

**说明**: 优化策略

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

##### `PerformanceMetrics` ← `BaseModel`

**说明**: 性能指标

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

##### `LearningRecord` ← `BaseModel`

**说明**: 学习记录

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

##### `OptimizationResult` ← `BaseModel`

**说明**: 优化结果

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

##### `ReflectionReport` ← `BaseModel`

**说明**: 反思报告

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

##### `OptimizationStatistics` ← `BaseModel`

**说明**: 优化统计

**方法列表**:

- `success_rate()`
  - 优化成功率
- `learning_application_rate()`
  - 学习应用率

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

---

### 📄 `reminder_models.py`

**模块说明**: Pydantic contracts for local reminder planning.

#### 类 (Classes)

##### `ReminderStatus` ← `str, Enum`

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

##### `ReminderType` ← `str, Enum`

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

##### `ReminderItem` ← `BaseModel`

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

##### `ReminderPlan` ← `BaseModel`

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

---

### 📄 `task_models.py`

**模块说明**: Task models for agent system.

#### 类 (Classes)

##### `TaskStatus` ← `str, Enum`

**说明**: Task execution status.

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

##### `TaskPriority` ← `str, Enum`

**说明**: Task priority levels.

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

##### `Task` ← `BaseModel`

**说明**: A task in the agent system.

**方法列表**:

- `is_ready(completed_task_ids)`
  - Check if task is ready to execute.
- `mark_started(agent_id)`
  - Mark task as started.
- `mark_completed(result)`
  - Mark task as completed.
- `mark_failed(error)`
  - Mark task as failed.
- `mark_blocked()`
  - Mark task as blocked.
- `get_duration()`
  - Get task duration in seconds.

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

##### `TaskDecompositionRequest` ← `BaseModel`

**说明**: Request for task decomposition.

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

##### `TaskDecompositionResult` ← `BaseModel`

**说明**: Result of task decomposition.

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

##### `AgentCapability` ← `str, Enum`

**说明**: Agent capabilities.

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

##### `Agent` ← `BaseModel`

**说明**: An agent in the system.

**方法列表**:

- `is_available()`
  - Check if agent is available for new tasks.
- `can_handle(task)`
  - Check if agent can handle a task.
- `assign_task(task_id)`
  - Assign a task to this agent.
- `complete_task(task_id, success)`
  - Mark a task as completed.

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

##### `TaskExecutionContext` ← `BaseModel`

**说明**: Context for task execution.

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

##### `TaskExecutionResult` ← `BaseModel`

**说明**: Result of task execution.

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

---

### 📄 `tool_models.py`

**模块说明**: Tool models for OpenPilot Phase 2.

#### 类 (Classes)

##### `PermissionLevel` ← `str, Enum`

**说明**: Tool permission levels.

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

##### `ToolCapability` ← `str, Enum`

**说明**: Tool capability categories.

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

##### `ToolInputSchema` ← `BaseModel`

**说明**: Schema for tool input parameters.

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

##### `ToolOutputSchema` ← `BaseModel`

**说明**: Schema for tool output.

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

##### `ToolFailureMode` ← `BaseModel`

**说明**: Describes how a tool can fail.

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

##### `ToolDependency` ← `BaseModel`

**说明**: Tool dependency specification.

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

##### `ToolDefinition` ← `BaseModel`

**说明**: Complete tool definition.

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

##### `ToolExecutionContext` ← `BaseModel`

**说明**: Context for tool execution.

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

##### `ToolExecutionResult` ← `BaseModel`

**说明**: Result of tool execution.

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

---

### 📄 `tool_orchestration_models.py`

**模块说明**: Tool orchestration models for OpenPilot Phase 2.

#### 类 (Classes)

##### `SelectionReason` ← `str, Enum`

**说明**: Reason for tool selection.

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

##### `ExecutionStrategy` ← `str, Enum`

**说明**: Execution strategy for tool.

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

##### `ToolSelection` ← `BaseModel`

**说明**: Selection of a tool for a specific step.

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

##### `ParallelExecutionGroup` ← `BaseModel`

**说明**: Group of tools that can execute in parallel.

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

##### `FallbackStrategy` ← `BaseModel`

**说明**: Fallback strategy when primary tool fails.

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

##### `ToolOrchestrationPlan` ← `BaseModel`

**说明**: Complete plan for tool orchestration.

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

##### `ToolMatchScore` ← `BaseModel`

**说明**: Score for how well a tool matches requirements.

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

##### `OrchestrationContext` ← `BaseModel`

**说明**: Context for tool orchestration.

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

##### `OrchestrationResult` ← `BaseModel`

**说明**: Result of orchestration planning.

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

---

### 📄 `validation_models.py`

**模块说明**: 结果验证与反馈数据模型

定义验证规则、验证结果、反馈条目等数据结构。

#### 类 (Classes)

##### `ValidationType` ← `str, Enum`

**说明**: 验证类型

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

##### `ValidationSeverity` ← `str, Enum`

**说明**: 验证严重程度

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

##### `FeedbackType` ← `str, Enum`

**说明**: 反馈类型

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

##### `QualityLevel` ← `str, Enum`

**说明**: 质量等级

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

##### `ValidationRule` ← `BaseModel`

**说明**: 验证规则

**方法列表**:

- `schema()`
  - Backward-compatible access for callers that used rule.schema.

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

##### `ValidationIssue` ← `BaseModel`

**说明**: 验证问题

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

##### `ValidationResult` ← `BaseModel`

**说明**: 验证结果

**方法列表**:

- `pass_rate()`
  - 通过率
- `has_critical_issues()`
  - 是否有严重问题

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

##### `FeedbackEntry` ← `BaseModel`

**说明**: 反馈条目

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

##### `QualityMetrics` ← `BaseModel`

**说明**: 质量指标

**方法列表**:

- `is_acceptable()`
  - 是否可接受

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

##### `ImprovementSuggestion` ← `BaseModel`

**说明**: 改进建议

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

##### `ValidationReport` ← `BaseModel`

**说明**: 验证报告

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

##### `FeedbackStatistics` ← `BaseModel`

**说明**: 反馈统计

**方法列表**:

- `positive_rate()`
  - 正面反馈率
- `satisfaction_score()`
  - 满意度分数（0-1）

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

---

## 📁 planning/

### 📄 `clarifier.py`

**模块说明**: Rule-based clarification for task-progress planning.

#### 类 (Classes)

##### `ClarificationQuestion` ← `BaseModel`

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

##### `ClarificationAnswer` ← `BaseModel`

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

##### `TaskBrief` ← `BaseModel`

**方法列表**:

- `planning_constraints()`
  - Return constraints suitable for planner input.

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

##### `Clarifier`

**说明**: Detect missing planning details with deterministic rules.

**方法列表**:

- `detect(goal, constraints)`
- `build_brief(goal, constraints, answers, assume_defaults)`

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

#### 函数 (Functions)

- `_normalize(goal, constraints)`

- `_has_deadline(text)`

- `_has_deliverable(text)`

- `_is_vague_goal(goal)`

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

---

### 📄 `goal_understanding.py`

**模块说明**: 目标理解增强模块

提供更智能的任务类型识别、资源推断和风险评估。

#### 类 (Classes)

##### `GoalUnderstandingEnhancer`

**说明**: 目标理解增强器

**方法列表**:

- `__init__()`
  - 初始化增强器
- `infer_resources_from_task_type(task_card)`
  - 根据任务类型推断所需资源
- `assess_risk_level(task_card)`
  - 评估任务风险等级
- `enhance_task_card(task_card)`
  - 全面增强任务卡片
- `_infer_deliverables(task_card)`
  - 推断预期交付物
- `validate_and_normalize_resources(task_card)`
  - 验证和规范化资源标签
- `suggest_constraints(task_card)`
  - 根据任务类型建议约束条件

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

---

### 📄 `timeline.py`

**模块说明**: Deterministic task-tree and timeline construction.

#### 函数 (Functions)

- `attach_timeline(plan)`
  - **说明**: Attach a normalized timeline derived from the validated execution steps.

- `build_timeline(plan)`
  - **说明**: Create a planning-only task tree and timeline from an execution plan.

- `_extract_time_horizon(plan)`

- `_timeline_labels(count, time_horizon)`

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

---

## 📁 reporting/

### 📄 `progress_report.py`

**模块说明**: Progress report generation module for daily and weekly reports.

This module generates structured progress reports based on task log entries,
providing daily summaries, weekly reviews, and retrospecti

#### 类 (Classes)

##### `ReportType` ← `str, Enum`

**说明**: Type of progress report.

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

##### `TaskSummary` ← `BaseModel`

**说明**: Summary of a single task in a report.

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

##### `ProgressReport` ← `BaseModel`

**说明**: Structured progress report.

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

##### `ProgressReportGenerator`

**说明**: Generate daily and weekly progress reports from task logs.

**方法列表**:

- `__init__(task_log_store)`
  - Initialize report generator.
- `generate_daily_report(date, user_preferences)`
  - Generate a daily progress report.
- `generate_weekly_report(week_start, user_preferences)`
  - Generate a weekly progress report.
- `_create_task_summary(task_id, entries)`
  - Create a task summary from log entries.
- `format_daily_report_markdown(report)`
  - Format daily report as Markdown.
- `format_weekly_report_markdown(report)`
  - Format weekly report as Markdown.

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

---

### 📄 `reminder_scheduler.py`

**模块说明**: Build local reminder plans from task timelines.

#### 类 (Classes)

##### `ReminderScheduler`

**说明**: Create planning-only reminders without triggering notifications.

**方法列表**:

- `build(plan)`

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

#### 函数 (Functions)

- `_stable_label(value, fallback)`

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

---

### 📄 `task_log.py`

**模块说明**: Task log module for recording task progress and state changes.

This module provides structured logging for task lifecycle events, separate from
the audit log. Task logs are used for product features 

#### 类 (Classes)

##### `TaskLogEventType` ← `str, Enum`

**说明**: Event types for task log entries.

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

##### `TaskLogEntry` ← `BaseModel`

**说明**: Single task log entry.

**方法列表**:

- `model_post_init(__context)`
  - Validate blocked events have a reason.

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

##### `TaskLogStore`

**说明**: Local JSONL storage for task logs.

**方法列表**:

- `__init__(log_dir)`
  - Initialize task log store.
- `_get_log_file(task_id)`
  - Get log file path for a specific task.
- `append(entry)`
  - Append a task log entry.
- `get_entries(task_id, event_type, since, until)`
  - Query task log entries.
- `get_all_task_ids()`
  - Get all task IDs that have log entries.
- `get_entries_by_date_range(since, until, event_type)`
  - Get all task log entries within a date range.
- `get_status_history(task_id)`
  - Get status change history for a task.
- `get_blocked_entries(task_id)`
  - Get all blocked events for a task.

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

#### 函数 (Functions)

- `create_task_log_entry(task_id, event_type, old_status, new_status, blocked_reason, note, metadata)`
  - **说明**: Create a task log entry with automatic timestamp and ID.

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

---

## 📁 root/

### 📄 `update_imports.py`

**模块说明**: 批量更新导入路径的脚本

#### 函数 (Functions)

- `update_file(file_path)`
  - **说明**: 更新单个文件的导入

- `main()`
  - **说明**: 主函数

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

---

## 📁 tools/

### 📄 `builtin_tools.py`

**模块说明**: Built-in tools for OpenPilot - Re-exports from individual tool modules.

#### 函数 (Functions)

- `register_builtin_tools(registry)`
  - **说明**: Register all built-in tools to a registry.

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

---

### 📄 `code_executor.py`

**模块说明**: Code Executor Tool - Execute code in a sandboxed environment.

#### 函数 (Functions)

- `code_executor_executor(params)`
  - **说明**: Execute code executor tool.

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

---

### 📄 `code_generator.py`

**模块说明**: Code Generator Tool - Generate code using LLM based on task description.

#### 函数 (Functions)

- `code_generator_executor(params)`
  - **说明**: Execute code generator tool.

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

---

### 📄 `code_reviewer.py`

**模块说明**: Code Reviewer Tool - Review code quality and suggest improvements using LLM.

#### 函数 (Functions)

- `code_reviewer_executor(params)`
  - **说明**: Execute code reviewer tool.

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

---

### 📄 `command_tool.py`

**模块说明**: Enhanced command tool with risk assessment and confidence scoring.

#### 类 (Classes)

##### `RiskLevel` ← `str, Enum`

**说明**: Command risk levels.

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

##### `ExecutionMode` ← `str, Enum`

**说明**: Command execution modes.

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

##### `RiskAssessment`

**说明**: Risk assessment for a command.

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

##### `CommandResult` ← `BaseModel`

**说明**: Result of command execution.

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

##### `CommandTool`

**说明**: Enhanced command execution with risk assessment.

**方法列表**:

- `__init__(default_timeout)`
  - Initialize command tool.
- `assess_risk(command)`
  - Assess risk of a command.
- `estimate_confidence(command)`
  - Estimate confidence in command execution.
- `execute(command, mode, timeout, cwd, env)`
  - Execute a command.
- `_extract_paths(command)`
  - Extract file paths from command.
- `_generate_recommendation(risk_level, risk_factors)`
  - Generate recommendation based on risk.

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

---

### 📄 `directory_lister.py`

**模块说明**: Directory Lister Tool - List local files in a directory using a glob pattern.

#### 函数 (Functions)

- `directory_lister_executor(params)`
  - **说明**: List files in a directory.

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

---

### 📄 `env_tools.py`

**模块说明**: Environment management tools for virtual environments.

#### 类 (Classes)

##### `EnvType` ← `str, Enum`

**说明**: Virtual environment types.

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

##### `EnvStatus` ← `str, Enum`

**说明**: Environment status.

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

##### `EnvInfo`

**说明**: Virtual environment information.

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

##### `EnvOperationResult` ← `BaseModel`

**说明**: Result of environment operation.

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

##### `EnvironmentManager`

**说明**: Manager for virtual environments.

**方法列表**:

- `__init__(base_dir)`
  - Initialize environment manager.
- `create_env(name, python_version, env_type)`
  - Create a virtual environment.
- `delete_env(name)`
  - Delete a virtual environment.
- `list_envs()`
  - List all virtual environments.
- `get_env_info(name)`
  - Get information about an environment.
- `install_package(env_name, package, upgrade)`
  - Install a package in an environment.
- `install_requirements(env_name, requirements_file)`
  - Install packages from requirements file.
- `list_packages(env_name)`
  - List installed packages in an environment.
- `_create_venv(env_path, python_version)`
  - Create venv environment.
- `_create_virtualenv(env_path, python_version)`
  - Create virtualenv environment.
- `_create_conda(name, python_version)`
  - Create conda environment.
- `_detect_env_type(env_path)`
  - Detect environment type.
- `_get_python_version(env_path)`
  - Get Python version in environment.
- `_get_python_path(env_path)`
  - Get Python executable path in environment.
- `_get_pip_path(env_path)`
  - Get pip executable path in environment.
- `_is_env_active(env_path)`
  - Check if environment is currently active.
- `_find_python_executable(version)`
  - Find Python executable for specific version.

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

---

### 📄 `file_reader.py`

**模块说明**: File Reader Tool - Read contents from a local file.

#### 函数 (Functions)

- `file_reader_executor(params)`
  - **说明**: Execute file reader tool.

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

---

### 📄 `file_tools.py`

**模块说明**: Enhanced file reading tools with adaptive strategies.

#### 类 (Classes)

##### `FileType` ← `str, Enum`

**说明**: File type categories.

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

##### `FileReadStrategy`

**说明**: Strategy for reading a file.

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

##### `FileReadResult` ← `BaseModel`

**说明**: Result of file reading operation.

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

##### `AdaptiveFileReader`

**说明**: File reader with adaptive strategies based on file type.

**方法列表**:

- `__init__(default_encoding)`
  - Initialize file reader.
- `detect_file_type(file_path)`
  - Detect file type based on extension and content.
- `get_read_strategy(file_path)`
  - Get reading strategy for a file.
- `read_file(file_path, strategy, offset)`
  - Read a file using adaptive strategy.
- `read_file_sample(file_path, num_lines)`
  - Read a sample of lines from a file.
- `read_file_tail(file_path, num_lines)`
  - Read the last N lines of a file.

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

---

### 📄 `file_writer.py`

**模块说明**: File Writer Tool - Write contents to a local file.

#### 函数 (Functions)

- `file_writer_executor(params)`
  - **说明**: Execute file writer tool.

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

---

### 📄 `instrumented_executor.py`

**模块说明**: Instrumented tool executor with UI progress tracking.

#### 类 (Classes)

##### `InstrumentedToolExecutor` ← `ToolExecutor`

**说明**: Tool executor that reports progress to UI.

**方法列表**:

- `__init__(registry, tracker, max_workers)`
  - Initialize instrumented tool executor.
- `execute(tool, executor_func, params, timeout)`
  - Execute tool with progress tracking.

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

---

### 📄 `llm_summarizer.py`

**模块说明**: LLM Summarizer Tool - Generate summary or analysis using LLM.

#### 函数 (Functions)

- `llm_summarizer_executor(params)`
  - **说明**: Execute LLM summarizer tool.

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

---

### 📄 `multi_file_reader.py`

**模块说明**: Multi File Reader Tool - Read and combine contents from multiple local files.

#### 函数 (Functions)

- `multi_file_reader_executor(params)`
  - **说明**: Read multiple files and combine them into one text payload.

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

---

### 📄 `tool_executor.py`

**模块说明**: 安全工具执行器

在受控环境中安全执行工具，支持超时、资源限制、错误处理。

#### 类 (Classes)

##### `ToolExecutor`

**说明**: 安全工具执行器

**方法列表**:

- `__init__(registry, max_workers)`
  - 初始化执行器
- `execute_single(tool_selection, context)`
  - 执行单个工具
- `execute_sequential(tool_selections, stop_on_failure)`
  - 顺序执行多个工具
- `execute_parallel(parallel_group)`
  - 并行执行工具组
- `execute_with_retry(tool_selection, max_retries, retry_delay)`
  - 执行工具（带重试）
- `execute_with_fallback(tool_selection, fallback_tools)`
  - 执行工具（带降级）
- `_create_context(tool_selection)`
  - 创建执行上下文
- `_pre_execution_check(tool_selection, context)`
  - 执行前检查
- `_post_execution_validation(tool_selection, output, context)`
  - 执行后验证
- `_execute_with_timeout(tool_executor, params, timeout)`
  - 带超时的执行
- `shutdown()`
  - 关闭执行器

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

---

### 📄 `tool_orchestrator.py`

**模块说明**: Tool orchestrator for generating execution plans.

#### 类 (Classes)

##### `ToolOrchestrator`

**说明**: Orchestrates tool selection and execution planning.

**方法列表**:

- `__init__(registry, semantic_analyzer)`
- `create_orchestration_plan(execution_plan, context)`
  - Create a complete tool orchestration plan from an execution plan.
- `_map_steps_to_tools(execution_plan, context)`
  - Map execution steps to tool selections.
- `_extract_semantic_input_params(step, semantic, known_directory)`
  - Create tool inputs from LLM semantics plus deterministic path extraction.
- `_preferred_tool_from_semantics(semantic)`
  - Use the LLM-selected tool without keyword reinterpretation.
- `_instruction_for_operation(operation_type)`
  - Return stable instructions for a semantically selected LLM operation.
- `_select_preferred_tool(step, required_capability, context, input_params, preferred_tool)`
  - Select a specific preferred tool when the step semantics are clear.
- `_step_text(step)`
  - Return searchable text for a plan step.
- `_step_raw_text(step)`
  - Return original-casing text for a plan step.
- `_extract_output_path_from_text(text)`
  - Extract an explicit output file path or filename from free text.
- `_extract_path_from_text(text)`
  - Extract a Windows or WSL path from free text.
- `_clean_path_candidate(candidate)`
  - Trim common natural-language suffixes around extracted paths.
- `_identify_parallel_groups(tool_selections, context)`
  - Identify groups of tools that can execute in parallel.
- `_generate_fallback_strategies(tool_selections)`
  - Generate fallback strategies for tool selections.
- `_determine_execution_strategy(tool_selections, parallel_groups, context)`
  - Determine overall execution strategy.
- `_estimate_duration(tool_selections)`
  - Estimate total execution duration in seconds.
- `_estimate_cost(tool_selections)`
  - Estimate total execution cost.
- `_determine_risk_level(tool_selections)`
  - Determine overall risk level.
- `_generate_recommendations(plan, context)`
  - Generate recommendations for the user.
- `_generate_warnings(plan, context)`
  - Generate warnings about potential issues.

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

---

### 📄 `tool_registry.py`

**模块说明**: Tool registry for managing and discovering tools.

#### 类 (Classes)

##### `ToolRegistryError` ← `OpenPilotError`

**说明**: Tool registry related errors.

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

##### `ToolRegistry`

**说明**: Central registry for tool management.

**方法列表**:

- `__init__()`
- `register(definition, executor, allow_override)`
  - Register a tool with its definition and executor function.
- `unregister(tool_name)`
  - Unregister a tool.
- `get(tool_name)`
  - Get tool definition by name.
- `get_executor(tool_name)`
  - Get tool executor function.
- `list_all()`
  - List all registered tools.
- `find_by_capability(capability, max_permission)`
  - Find tools by capability.
- `find_by_tags(tags, match_all)`
  - Find tools by tags.
- `check_dependencies(tool_name)`
  - Check if all dependencies for a tool are satisfied.
- `get_stats()`
  - Get registry statistics.

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

#### 函数 (Functions)

- `get_global_registry()`
  - **说明**: Get or create the global tool registry.

- `reset_global_registry()`
  - **说明**: Reset the global registry (mainly for testing).

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

---

### 📄 `tool_selector.py`

**模块说明**: Tool selector for intelligent tool matching.

#### 类 (Classes)

##### `ToolSelector`

**说明**: Intelligent tool selector based on requirements and context.

**方法列表**:

- `__init__(registry)`
- `select_tool(step_id, required_capability, context, input_params)`
  - Select the best tool for a given capability and context.
- `_score_tool(tool, context)`
  - Score how well a tool matches the requirements.
- `_determine_reason(score, num_candidates, context)`
  - Determine the reason for tool selection.
- `_requires_confirmation(tool, score, context)`
  - Determine if user confirmation is required.
- `select_multiple_tools(steps, context)`
  - Select tools for multiple steps.

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

---

## 📁 ui/

### 📄 `commands.py`

**模块说明**: Unified command registry for OpenPilot CLI.

#### 类 (Classes)

##### `CommandCategory` ← `str, Enum`

**说明**: Command categories for organization.

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

##### `Command`

**说明**: A CLI command definition.

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

##### `CommandRegistry`

**说明**: Central registry for all OpenPilot commands.

**方法列表**:

- `__init__()`
- `_initialize_commands()`
  - Initialize all available commands.
- `register(command)`
  - Register a command and its aliases.
- `get(name)`
  - Get a command by name or alias.
- `get_all_names()`
  - Get all command names (including aliases) for autocomplete.
- `get_commands_by_category(category)`
  - Get all commands in a category.
- `get_all_commands()`
  - Get all registered commands.
- `is_valid_command(name)`
  - Check if a command name is valid.
- `format_help()`
  - Format help text for all commands.

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

#### 函数 (Functions)

- `get_command_registry()`
  - **说明**: Get the global command registry.

- `get_all_command_names()`
  - **说明**: Get all command names for autocomplete.

- `is_valid_command(name)`
  - **说明**: Check if a command is valid.

- `get_command(name)`
  - **说明**: Get a command by name or alias.

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

---

### 📄 `enhanced_cli.py`

**模块说明**: Enhanced CLI entry point with improved UI.

#### 函数 (Functions)

- `run_enhanced_cli(args, console, llm_client)`
  - **说明**: Run OpenPilot with enhanced UI.

- `_run_once_mode(goal, ui, tracker, planner, logger, settings)`
  - **说明**: Run a single goal and exit.

- `_run_interactive_mode(ui, tracker, planner, logger, settings, args, llm_client)`
  - **说明**: Run interactive REPL mode.

- `_execute_goal_interactive(goal, ui, tracker, planner)`
  - **说明**: Execute a goal in interactive mode.

- `_show_help(ui)`
  - **说明**: Show help information.

- `_show_config(ui, settings)`
  - **说明**: Show current configuration.

- `_execute_autopilot(goal, ui, tracker, llm_client, logger)`
  - **说明**: Execute goal using intelligent autopilot with enhanced UI.

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

---

### 📄 `enhanced_ui.py`

**模块说明**: Enhanced UI components with Claude Code-style interface.

#### 类 (Classes)

##### `EnhancedUI`

**说明**: Enhanced UI with Claude Code-style interface and real-time updates.

**方法列表**:

- `__init__(console)`
- `show_banner()`
  - Display OpenPilot banner.
- `show_menu(title, options, selected)`
  - Create an interactive menu panel.
- `create_status_panel(status, details)`
  - Create a status panel.
- `create_activity_panel()`
  - Create activity log panel showing recent actions.
- `log_activity(action_type, message)`
  - Add an activity to the log.
- `live_session(title)`
  - Context manager for live updating display.
- `update_main_content(content)`
  - Update the main content area.
- `show_progress_with_activity(task_description, total_steps)`
  - Show progress bar with activity log.
- `show_tool_execution(tool_name, params)`
  - Display tool execution in progress.
- `show_llm_thinking(prompt_preview, model)`
  - Display LLM thinking process.
- `create_executing_panel(task_description)`
  - Create an executing panel with spinner animation.
- `create_task_tree_panel(decomposition)`
  - Create a panel containing the task decomposition tree.
- `show_task_tree(task_graph)`
- `show_error(error_message, details)`
  - Display error message.
- `show_success(message, details)`
  - Display success message.
- `prompt_choice(question, choices, default)`
  - Prompt user to select from choices.

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

---

### 📄 `progress_tracker.py`

**模块说明**: Real-time progress tracker for tool calls and LLM operations.

#### 类 (Classes)

##### `OperationType` ← `Enum`

**说明**: Type of operation being tracked.

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

##### `Operation`

**说明**: Represents an ongoing operation.

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

##### `ProgressTracker`

**说明**: Track and display real-time progress of operations.

**方法列表**:

- `__init__(ui)`
  - Initialize progress tracker with UI instance.
- `start_tracking()`
  - Start background thread for UI updates.
- `stop_tracking()`
  - Stop background thread.
- `_update_loop()`
  - Background loop to update UI.
- `track_tool_call(tool_name, params)`
  - Context manager to track a tool call.
- `track_llm_call(model, prompt_preview)`
  - Context manager to track an LLM call.
- `track_task(task_name, details)`
  - Context manager to track a task execution.
- `_start_operation(op_type, name, details)`
  - Start tracking an operation.
- `_end_operation(op_id, success, error)`
  - Mark an operation as completed.
- `get_active_operations()`
  - Get list of currently active operations.
- `get_completed_operations(limit)`
  - Get list of recently completed operations.
- `clear_old_operations(max_age_seconds)`
  - Clear operations older than max_age_seconds.

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

---

## 📁 utils/

### 📄 `cache.py`

**模块说明**: Caching and memoization utilities inspired by Claude Code.

Provides LRU cache, TTL cache with write-through pattern, and async TTL cache
with in-flight deduplication to reduce redundant computations.

#### 类 (Classes)

##### `LRUCache`

**说明**: Thread-safe LRU (Least Recently Used) cache with bounded size.

**方法列表**:

- `__init__(maxsize)`
  - Initialize LRU cache.
- `get(key)`
  - Get value from cache.
- `put(key, value)`
  - Put value into cache.
- `clear()`
  - Clear all cached items.
- `size()`
  - Get current cache size.
- `stats()`
  - Get cache statistics.

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

##### `TTLCache`

**说明**: Thread-safe TTL (Time To Live) cache with write-through pattern.

**方法列表**:

- `__init__(ttl_seconds)`
  - Initialize TTL cache.
- `get(key)`
  - Get value from cache.
- `put(key, value)`
  - Put value into cache with current timestamp.
- `clear()`
  - Clear all cached items.
- `size()`
  - Get current cache size.
- `stats()`
  - Get cache statistics.

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

##### `AsyncTTLCache`

**说明**: Async TTL cache with in-flight deduplication.

**方法列表**:

- `__init__(ttl_seconds)`
  - Initialize async TTL cache.

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

#### 函数 (Functions)

- `memoize_with_lru(maxsize)`
  - **说明**: Decorator for LRU memoization of function results.

- `memoize_with_ttl(ttl_seconds)`
  - **说明**: Decorator for TTL memoization with write-through pattern.

- `memoize_with_ttl_async(ttl_seconds)`
  - **说明**: Decorator for async TTL memoization with in-flight deduplication.

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

---

### 📄 `concurrency.py`

**模块说明**: Concurrency control utilities inspired by Claude Code.

Provides sequential execution decorator, cancellable sleep, timeout management,
and hierarchical cancellation tokens for async operations.

#### 类 (Classes)

##### `CancellationToken`

**说明**: Cancellation token for cooperative cancellation.

**方法列表**:

- `__init__(parent)`
  - Initialize cancellation token.
- `cancel()`
  - Cancel this token and all children.
- `is_cancelled()`
  - Check if token is cancelled.
- `wait(timeout)`
  - Wait for cancellation.
- `throw_if_cancelled(error_class)`
  - Raise exception if cancelled.

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

##### `RateLimiter`

**说明**: Rate limiter for controlling operation frequency.

**方法列表**:

- `__init__(max_calls, time_window)`
  - Initialize rate limiter.
- `acquire(blocking, timeout)`
  - Acquire permission to make a call.
- `__enter__()`
  - Context manager support.
- `__exit__(exc_type, exc_val, exc_tb)`
  - Context manager support.

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

##### `Debouncer`

**说明**: Debouncer for delaying function execution until calls stop.

**方法列表**:

- `__init__(wait_seconds)`
  - Initialize debouncer.
- `debounce(func)`
  - Debounce function call.
- `cancel()`
  - Cancel pending debounced call.

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

#### 函数 (Functions)

- `create_child_cancel_token(parent)`
  - **说明**: Create child cancellation token.

- `sleep_with_cancel(seconds, cancel_token, check_interval)`
  - **说明**: Sleep with cancellation support.

- `with_timeout(timeout_seconds, error_msg)`
  - **说明**: Decorator to add timeout to function.

- `with_timeout_async(timeout_seconds, error_msg)`
  - **说明**: Decorator to add timeout to async function.

- `sequential(func)`
  - **说明**: Decorator to force sequential execution of function.

- `sequential_async(func)`
  - **说明**: Decorator to force sequential execution of async function.

- `rate_limited(max_calls, time_window)`
  - **说明**: Decorator to rate limit function calls.

- `retry_with_backoff(max_retries, initial_delay, backoff_factor, max_delay, retryable_exceptions)`
  - **说明**: Decorator to retry function with exponential backoff.

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

---

### 📄 `data_structures.py`

**模块说明**: Data structures for bounded memory usage inspired by Claude Code.

Provides circular buffers and truncating accumulators to prevent
unbounded memory growth in long-running processes.

#### 类 (Classes)

##### `CircularBuffer`

**说明**: Fixed-size circular buffer with automatic eviction of oldest items.

**方法列表**:

- `__init__(maxsize)`
  - Initialize circular buffer.
- `add(item)`
  - Add item to buffer.
- `add_all(items)`
  - Add multiple items to buffer.
- `get_recent(count)`
  - Get most recent N items.
- `to_list()`
  - Convert buffer to list.
- `clear()`
  - Clear all items from buffer.
- `length()`
  - Get current number of items in buffer.
- `is_full()`
  - Check if buffer is full.
- `__len__()`
  - Get length of buffer.
- `__iter__()`
  - Iterate over buffer items.
- `__repr__()`
  - String representation.

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

##### `EndTruncatingAccumulator`

**说明**: Safe string accumulator that truncates from the end when size limit exceeded.

**方法列表**:

- `__init__(max_size)`
  - Initialize accumulator.
- `add(text)`
  - Add text to accumulator.
- `_truncate_to_bytes(text, max_bytes)`
  - Truncate text to fit within byte limit (UTF-8 safe).
- `get_value()`
  - Get accumulated text.
- `get_stats()`
  - Get accumulator statistics.
- `clear()`
  - Clear accumulator.
- `is_truncated()`
  - Check if any truncation has occurred.
- `__len__()`
  - Get current size in bytes.
- `__repr__()`
  - String representation.

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

---

### 📄 `diff_utils.py`

**模块说明**: Diff and patch utilities inspired by Claude Code.

Provides functions for generating patches, counting changes,
and applying patches for code review and file modifications.

#### 函数 (Functions)

- `get_patch_from_contents(old_content, new_content, context_lines, old_name, new_name)`
  - **说明**: Generate unified diff patch from old and new content.

- `count_lines_changed(patch)`
  - **说明**: Count additions and deletions from a patch.

- `apply_patch(content, patch)`
  - **说明**: Apply a unified diff patch to content.

- `get_diff_stats(patch)`
  - **说明**: Get statistics from a patch.

- `format_diff_stats(additions, deletions)`
  - **说明**: Format diff statistics as a string.

- `get_changed_lines(old_content, new_content)`
  - **说明**: Get line numbers that changed between old and new content.

- `highlight_diff(old_content, new_content, context_lines)`
  - **说明**: Generate highlighted diff with line types.

- `is_whitespace_only_change(old_content, new_content)`
  - **说明**: Check if changes are whitespace-only.

- `get_similarity_ratio(old_content, new_content)`
  - **说明**: Calculate similarity ratio between two contents.

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

---

### 📄 `formatters.py`

**模块说明**: Formatting utilities inspired by Claude Code.

Provides consistent formatting for file sizes, durations, numbers,
and relative times for better user experience.

#### 函数 (Functions)

- `format_file_size(bytes_size)`
  - **说明**: Format file size in human-readable format.

- `format_duration(milliseconds)`
  - **说明**: Format duration in human-readable format.

- `format_seconds_short(seconds)`
  - **说明**: Format seconds in short format (always keeps decimal).

- `format_number_compact(num)`
  - **说明**: Format number in compact notation.

- `format_tokens(tokens)`
  - **说明**: Format token count (removes .0 from compact numbers).

- `format_relative_time(timestamp, now, max_units)`
  - **说明**: Format timestamp as relative time.

- `format_percentage(value, total, decimals)`
  - **说明**: Format percentage.

- `format_log_metadata(timestamp, file_size, branch, pr_number)`
  - **说明**: Format log metadata combining time, size, branch, PR info.

- `format_count(count, singular, plural)`
  - **说明**: Format count with singular/plural form.

- `format_list(items, max_items, conjunction)`
  - **说明**: Format list of items with conjunction.

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

---

### 📄 `json_utils.py`

**模块说明**: Efficient JSONL (JSON Lines) processing utilities inspired by Claude Code.

Provides safe JSON parsing with caching, efficient JSONL file handling,
and atomic append operations for log files.

#### 函数 (Functions)

- `safe_parse_json(text, default)`
  - **说明**: Parse JSON with LRU caching and safe error handling.

- `parse_jsonl(data)`
  - **说明**: Parse JSONL data from string or bytes.

- `read_jsonl_file(path, max_bytes, skip_first_partial)`
  - **说明**: Read JSONL file efficiently, optionally reading only the tail.

- `append_jsonl(path, data, ensure_newline)`
  - **说明**: Atomically append JSON object(s) to JSONL file.

- `read_last_n_lines(path, n, max_line_length)`
  - **说明**: Read last N lines from file efficiently.

- `parse_last_n_jsonl(path, n)`
  - **说明**: Parse last N lines from JSONL file.

- `count_jsonl_lines(path)`
  - **说明**: Count number of lines in JSONL file efficiently.

- `truncate_jsonl_file(path, max_lines)`
  - **说明**: Truncate JSONL file to keep only last N lines.

- `validate_jsonl_file(path)`
  - **说明**: Validate JSONL file and return statistics.

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

---

### 📄 `text_utils.py`

**模块说明**: String processing and manipulation utilities inspired by Claude Code.

Provides robust string handling with proper CJK (Chinese, Japanese, Korean)
support, emoji handling, and safe truncation operatio

#### 函数 (Functions)

- `truncate_middle(text, max_length, separator)`
  - **说明**: Truncate string in the middle, preserving start and end.

- `truncate_to_bytes(text, max_bytes, encoding, suffix)`
  - **说明**: Truncate string to fit within byte limit (UTF-8 safe).

- `safe_join_lines(lines, max_size, separator, truncation_msg)`
  - **说明**: Join lines with truncation if total size exceeds limit.

- `normalize_cjk_text(text)`
  - **说明**: Normalize CJK full-width characters to half-width.

- `count_graphemes(text)`
  - **说明**: Count grapheme clusters (user-perceived characters).

- `escape_regex(text)`
  - **说明**: Escape special regex characters in string.

- `capitalize_first(text)`
  - **说明**: Capitalize only the first character.

- `plural(count, singular, plural_form)`
  - **说明**: Return singular or plural form based on count.

- `count_char_in_string(text, char)`
  - **说明**: Count occurrences of character in string efficiently.

- `normalize_whitespace(text)`
  - **说明**: Normalize whitespace in text.

- `remove_ansi_codes(text)`
  - **说明**: Remove ANSI color/formatting codes from text.

- `truncate_lines(text, max_lines, suffix)`
  - **说明**: Truncate text to maximum number of lines.

- `indent_text(text, indent, skip_first)`
  - **说明**: Indent all lines in text.

- `extract_between(text, start, end, include_markers)`
  - **说明**: Extract text between two markers.

- `split_preserve_quotes(text, delimiter)`
  - **说明**: Split text by delimiter, preserving quoted sections.

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

---

### 📄 `tree_viz.py`

**模块说明**: Tree visualization utilities inspired by Claude Code.

Provides functions for rendering nested objects as ASCII trees
with support for circular reference detection and custom styling.

#### 函数 (Functions)

- `treeify(obj, max_depth, current_depth, prefix, is_last, seen, show_types)`
  - **说明**: Render nested object as ASCII tree.

- `treeify_compact(obj, max_depth)`
  - **说明**: Render object as compact tree (less verbose).

- `treeify_with_types(obj, max_depth)`
  - **说明**: Render object as tree with type information.

- `format_tree_node(key, value, is_last)`
  - **说明**: Format a single tree node.

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

---

## 📁 validation/

### 📄 `feedback_collector.py`

**模块说明**: 反馈收集器

收集用户反馈、自动评分、生成改进建议。

#### 类 (Classes)

##### `FeedbackCollector`

**说明**: 反馈收集器

**方法列表**:

- `__init__()`
  - 初始化反馈收集器
- `collect_feedback(target_id, feedback_type, rating, comment, tags, issues, suggestions, source, user_id)`
  - 收集反馈
- `collect_automatic_feedback(target_id, quality_metrics, validation_result)`
  - 自动收集反馈（基于质量指标和验证结果）
- `generate_improvement_suggestions(target_id, quality_metrics, validation_result)`
  - 生成改进建议
- `get_feedback_statistics(start_time, end_time)`
  - 获取反馈统计
- `_generate_suggestions_from_metrics(quality_metrics)`
  - 从质量指标生成建议
- `get_feedback_for_target(target_id)`
  - 获取特定目标的所有反馈
- `get_quality_metrics(target_id)`
  - 获取特定目标的质量指标
- `get_stats()`
  - 获取收集器统计

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

---

### 📄 `output_validator.py`

**模块说明**: 输出验证器

验证工具执行结果和代码执行结果的输出格式、类型、范围等。

#### 类 (Classes)

##### `OutputValidator`

**说明**: 输出验证器

**方法列表**:

- `__init__()`
  - 初始化验证器
- `register_rule(rule)`
  - 注册验证规则
- `register_custom_validator(name, validator)`
  - 注册自定义验证器
- `validate(output, rules, target_id)`
  - 验证输出
- `_validate_rule(output, rule)`
  - 验证单个规则
- `_validate_type(output, rule)`
  - 验证类型
- `_validate_format(output, rule)`
  - 验证格式
- `_validate_range(output, rule)`
  - 验证范围
- `_validate_pattern(output, rule)`
  - 验证模式
- `_validate_schema(output, rule)`
  - 验证结构（简化版 JSON Schema）
- `_validate_custom(output, rule)`
  - 自定义验证
- `_is_valid_json(value)`
  - 验证 JSON 格式
- `_is_valid_email(value)`
  - 验证邮箱格式
- `_is_valid_url(value)`
  - 验证 URL 格式
- `_is_valid_date(value)`
  - 验证日期格式
- `_is_valid_uuid(value)`
  - 验证 UUID 格式
- `_is_valid_ipv4(value)`
  - 验证 IPv4 格式
- `get_stats()`
  - 获取验证统计

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

---

### 📄 `reflection_analyzer.py`

**模块说明**: 反思分析器

分析执行结果、识别问题、提取经验教训。

#### 类 (Classes)

##### `ReflectionAnalyzer`

**说明**: 反思分析器

**方法列表**:

- `__init__()`
  - 初始化反思分析器
- `analyze_execution_result(result, validation, quality_metrics)`
  - 分析工具执行结果
- `analyze_code_execution_result(result, validation, quality_metrics)`
  - 分析代码执行结果
- `identify_patterns(min_occurrences)`
  - 识别模式
- `create_learning_record(reflection, topic, category)`
  - 创建学习记录
- `_observe_execution(result, validation, quality_metrics)`
  - 观察执行结果
- `_analyze_execution(result, validation, quality_metrics)`
  - 分析执行结果
- `_extract_insights(result, validation, quality_metrics)`
  - 提取洞察
- `_identify_problems(result, validation, quality_metrics)`
  - 识别问题
- `_identify_root_causes(result, validation, quality_metrics)`
  - 识别根本原因
- `_generate_improvements(result, validation, quality_metrics)`
  - 生成改进机会
- `_recommend_actions(result, validation, quality_metrics)`
  - 推荐行动
- `_extract_lessons(result, validation, quality_metrics)`
  - 提取经验教训
- `_observe_code_execution(result, validation, quality_metrics)`
  - 观察代码执行结果
- `_analyze_code_execution(result, validation, quality_metrics)`
  - 分析代码执行结果
- `_extract_code_insights(result, validation, quality_metrics)`
  - 提取代码洞察
- `_identify_code_problems(result, validation, quality_metrics)`
  - 识别代码问题
- `_identify_code_root_causes(result, validation, quality_metrics)`
  - 识别代码根本原因
- `_generate_code_improvements(result, validation, quality_metrics)`
  - 生成代码改进机会
- `_recommend_code_actions(result, validation, quality_metrics)`
  - 推荐代码行动
- `_extract_code_lessons(result, validation, quality_metrics)`
  - 提取代码经验教训
- `_calculate_confidence(result, validation, quality_metrics)`
  - 计算置信度
- `_calculate_code_confidence(result, validation, quality_metrics)`
  - 计算代码置信度
- `get_reflections(reflection_type, limit)`
  - 获取反思条目
- `get_learning_records(status, limit)`
  - 获取学习记录
- `get_stats()`
  - 获取统计信息

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

---

### 📄 `result_validator.py`

**模块说明**: 结果验证器

验证工具执行结果和代码执行结果的正确性。

#### 类 (Classes)

##### `ResultValidator`

**说明**: 结果验证器

**方法列表**:

- `__init__(output_validator)`
  - 初始化结果验证器
- `validate_execution_result(result, validation_rules, expected_output)`
  - 验证工具执行结果
- `validate_code_execution_result(result, validation_rules, expected_output)`
  - 验证代码执行结果
- `calculate_quality_metrics(result, validation_result, user_rating)`
  - 计算质量指标
- `calculate_code_quality_metrics(result, validation_result, user_rating)`
  - 计算代码执行质量指标
- `_calculate_efficiency_score(duration_seconds)`
  - 计算效率评分
- `_determine_quality_level(score)`
  - 确定质量等级
- `_create_passed_validation(target_id)`
  - 创建通过的验证结果
- `_create_failed_validation(target_id, message)`
  - 创建失败的验证结果
- `get_stats()`
  - 获取验证统计

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

---

### 📄 `strategy_optimizer.py`

**模块说明**: 策略优化器

基于反思结果生成和应用优化策略。

#### 类 (Classes)

##### `StrategyOptimizer`

**说明**: 策略优化器

**方法列表**:

- `__init__(memory_store)`
  - 初始化策略优化器
- `generate_optimization_strategies(reflections)`
  - 基于反思生成优化策略
- `apply_strategy(strategy_id, target_id, before_metrics)`
  - 应用优化策略
- `update_memory_from_reflections(reflections, learning_records)`
  - 从反思更新记忆系统
- `generate_reflection_report(reflections, learning_records, start_time, end_time)`
  - 生成反思报告
- `get_optimization_statistics(start_time, end_time)`
  - 获取优化统计
- `_generate_reliability_strategy(reflections)`
  - 生成可靠性优化策略
- `_generate_efficiency_strategy(reflections)`
  - 生成效率优化策略
- `_generate_best_practice_strategy(reflections)`
  - 生成最佳实践策略
- `_generate_tool_selection_strategy(reflections)`
  - 生成工具选择策略
- `_simulate_strategy_application(strategy, before_metrics)`
  - 模拟策略应用（实际应用需要具体实现）
- `_calculate_improvement(before, after)`
  - 计算改进百分比
- `_create_skill_memory_from_reflection(reflection)`
  - 从反思创建技能记忆
- `_create_lesson_memory_from_reflection(reflection)`
  - 从反思创建教训记忆
- `_create_skill_memory_from_learning(record)`
  - 从学习记录创建技能记忆
- `_extract_key_findings(reflections)`
  - 提取关键发现
- `_identify_common_patterns(reflections)`
  - 识别常见模式
- `_identify_recurring_issues(reflections)`
  - 识别重复问题
- `_generate_priority_actions(reflections, strategies)`
  - 生成优先行动
- `get_strategies(strategy_type, enabled_only)`
  - 获取策略列表
- `get_optimization_results(strategy_id, limit)`
  - 获取优化结果

**重构意见**:
```
[ 在此处添加你的重构建议 ]
```

---


## 🎯 重构优先级建议

### 高优先级
- [ ] 执行层 (execution/) - 核心执行逻辑优化
- [ ] 工具层 (tools/) - 工具调用和数据传递
- [ ] UI层 (ui/) - 用户交互体验

### 中优先级
- [ ] 规划层 (planning/) - 任务规划逻辑
- [ ] 验证层 (validation/) - 结果验证
- [ ] 模型层 (models/) - 数据模型优化

### 低优先级
- [ ] 工具函数 (utils/) - 辅助函数
- [ ] 报告层 (reporting/) - 报告生成

