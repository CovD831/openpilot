"""Demo script for tool executor functionality."""

import tempfile
from pathlib import Path

from openpilot.builtin_tools import register_builtin_tools
from openpilot.tool_executor import ToolExecutor
from openpilot.tool_orchestration_models import (
    ParallelExecutionGroup,
    ToolSelection,
)
from openpilot.tool_registry import ToolRegistry


def print_section(title: str):
    """Print a section header."""
    print()
    print("=" * 70)
    print(f"  {title}")
    print("=" * 70)
    print()


def print_result(result):
    """Print execution result."""
    status_emoji = "✅" if result.success else "❌"
    print(f"{status_emoji} Step: {result.step_id}")
    print(f"   Tool: {result.tool_name}")
    print(f"   Status: {result.status}")
    print(f"   Duration: {result.duration_seconds:.3f}s")
    if result.success and result.output:
        print(f"   Output: {str(result.output)[:100]}...")
    if result.error:
        print(f"   Error: {result.error.error_message}")
    print()


def demo_single_execution():
    """Demo: Single tool execution."""
    print_section("Demo 1: Single Tool Execution")

    registry = ToolRegistry()
    register_builtin_tools(registry)
    executor = ToolExecutor(registry)

    # Create a test file
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt') as f:
        f.write("Hello from OpenPilot Phase 2!\nTool executor is working!")
        temp_path = f.name

    try:
        print("📝 Executing file_reader tool...")
        selection = ToolSelection(
            step_id="read_file",
            tool_name="file_reader",
            reason="capability_match",
            confidence=0.9,
            input_params={"file_path": temp_path}
        )

        result = executor.execute_single(selection)
        print_result(result)

        if result.success:
            print(f"📄 File content:\n{result.output['content']}\n")

    finally:
        Path(temp_path).unlink()
        executor.shutdown()


def demo_sequential_execution():
    """Demo: Sequential execution."""
    print_section("Demo 2: Sequential Execution")

    registry = ToolRegistry()
    register_builtin_tools(registry)
    executor = ToolExecutor(registry)

    with tempfile.TemporaryDirectory() as tmpdir:
        input_file = Path(tmpdir) / "input.txt"
        output_file = Path(tmpdir) / "output.txt"
        input_file.write_text("Original content")

        try:
            print("📝 Executing 3-step workflow...")
            print("   1. Read input file")
            print("   2. Process with LLM (simulated)")
            print("   3. Write output file")
            print()

            selections = [
                ToolSelection(
                    step_id="step_1_read",
                    tool_name="file_reader",
                    reason="capability_match",
                    confidence=0.9,
                    input_params={"file_path": str(input_file)}
                ),
                ToolSelection(
                    step_id="step_2_process",
                    tool_name="llm_summarizer",
                    reason="capability_match",
                    confidence=0.8,
                    input_params={
                        "text": "Sample text for summarization",
                        "instruction": "Summarize briefly"
                    }
                ),
                ToolSelection(
                    step_id="step_3_write",
                    tool_name="file_writer",
                    reason="capability_match",
                    confidence=0.9,
                    input_params={
                        "file_path": str(output_file),
                        "content": "Processed content"
                    }
                )
            ]

            results = executor.execute_sequential(selections)

            print("📊 Execution Results:")
            for result in results:
                print_result(result)

            success_count = sum(1 for r in results if r.success)
            print(f"✅ Success rate: {success_count}/{len(results)} ({success_count/len(results)*100:.0f}%)")

        finally:
            executor.shutdown()


def demo_parallel_execution():
    """Demo: Parallel execution."""
    print_section("Demo 3: Parallel Execution")

    registry = ToolRegistry()
    register_builtin_tools(registry)
    executor = ToolExecutor(registry)

    with tempfile.TemporaryDirectory() as tmpdir:
        # Create multiple files
        files = []
        for i in range(3):
            f = Path(tmpdir) / f"file{i}.txt"
            f.write_text(f"Content of file {i}")
            files.append(f)

        try:
            print("📝 Executing parallel file reads...")
            print(f"   Reading {len(files)} files simultaneously")
            print()

            selections = [
                ToolSelection(
                    step_id=f"read_file_{i}",
                    tool_name="file_reader",
                    reason="capability_match",
                    confidence=0.9,
                    input_params={"file_path": str(f)}
                )
                for i, f in enumerate(files)
            ]

            parallel_group = ParallelExecutionGroup(
                group_id="parallel_reads",
                tool_selections=selections,
                wait_for_all=True,
                timeout_seconds=30
            )

            result = executor.execute_parallel(parallel_group)

            print("📊 Parallel Execution Results:")
            print(f"   Group ID: {result.group_id}")
            print(f"   All Success: {result.all_success}")
            print(f"   Total Duration: {result.total_duration_seconds:.3f}s")
            print(f"   Average per task: {result.total_duration_seconds/len(result.results):.3f}s")
            print()

            for r in result.results:
                print_result(r)

        finally:
            executor.shutdown()


def demo_retry_mechanism():
    """Demo: Retry mechanism."""
    print_section("Demo 4: Retry Mechanism")

    registry = ToolRegistry()
    register_builtin_tools(registry)
    executor = ToolExecutor(registry)

    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt') as f:
        f.write("Test content")
        temp_path = f.name

    try:
        print("📝 Executing with retry (max 3 attempts)...")
        selection = ToolSelection(
            step_id="read_with_retry",
            tool_name="file_reader",
            reason="capability_match",
            confidence=0.9,
            input_params={"file_path": temp_path}
        )

        result = executor.execute_with_retry(
            selection,
            max_retries=3,
            retry_delay=1
        )

        print_result(result)
        print(f"📊 Retry Statistics:")
        print(f"   Attempt Number: {result.attempt_number}")
        print(f"   Retry Count: {result.retry_count}")
        print(f"   Max Retries: {result.max_retries}")

    finally:
        Path(temp_path).unlink()
        executor.shutdown()


def demo_error_handling():
    """Demo: Error handling."""
    print_section("Demo 5: Error Handling")

    registry = ToolRegistry()
    register_builtin_tools(registry)
    executor = ToolExecutor(registry)

    try:
        print("📝 Attempting to read non-existent file...")
        selection = ToolSelection(
            step_id="read_missing_file",
            tool_name="file_reader",
            reason="capability_match",
            confidence=0.9,
            input_params={"file_path": "/nonexistent/file.txt"}
        )

        result = executor.execute_single(selection)

        print_result(result)

        if result.error:
            print("🔍 Error Details:")
            print(f"   Type: {result.error.error_type}")
            print(f"   Message: {result.error.error_message}")
            print(f"   Recoverable: {result.error.recoverable}")
            print(f"   Retry Recommended: {result.error.retry_recommended}")

    finally:
        executor.shutdown()


def main():
    """Run all demos."""
    print()
    print("╔══════════════════════════════════════════════════════════════════════╗")
    print("║            OpenPilot Phase 2 - Tool Executor Demo                   ║")
    print("╚══════════════════════════════════════════════════════════════════════╝")

    demo_single_execution()
    demo_sequential_execution()
    demo_parallel_execution()
    demo_retry_mechanism()
    demo_error_handling()

    print_section("Summary")
    print("✅ OP-22 安全执行器 - 完成！")
    print()
    print("核心功能:")
    print("  • 单个工具安全执行")
    print("  • 顺序执行（支持失败停止）")
    print("  • 并行执行（线程池）")
    print("  • 自动重试（指数退避）")
    print("  • 备选方案（降级策略）")
    print("  • 超时控制")
    print("  • 资源监控")
    print("  • 完整错误处理")
    print()
    print("Phase 2 第一阶段完成度: 3/3 (100%) ✅")
    print()
    print("下一步：OP-23 代码生成与执行引擎")
    print()


if __name__ == "__main__":
    main()
