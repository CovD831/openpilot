from __future__ import annotations

import json
import sys
from types import SimpleNamespace

from core.openpilot_log import OpenPilotLogger
from tools.code_reviewer import code_reviewer_executor
from tools.builtin_tools import register_builtin_tools
from tools.web_searcher import web_searcher_executor
from tools.tool_executor import ToolExecutor
from core.tool_contracts import (
    PermissionLevel,
    ToolDefinition,
    ToolOutputSchema,
)
from tools.tool_selection import ToolSelection
from tools.tool_registry import ToolRegistry


def _registered_registry() -> ToolRegistry:
    registry = ToolRegistry()
    register_builtin_tools(registry)
    return registry


class FakeCleanupLLM:
    def __init__(self, payload: dict | None = None, *, fail: bool = False) -> None:
        self.payload = payload or {
            "research_summary": "Clean summary",
            "key_points": ["Useful fact"],
            "source_notes": [{"url": "https://example.com/alpha", "note": "Primary source"}],
            "follow_up_queries": ["openpilot follow up"],
        }
        self.fail = fail
        self.requests = []

    def complete(self, request):
        self.requests.append(request)
        if self.fail:
            raise RuntimeError("llm unavailable")
        return SimpleNamespace(
            parsed_json=self.payload,
            content=json.dumps(self.payload),
        )


def test_builtin_tools_register_expected_contracts() -> None:
    registry = _registered_registry()

    names = {tool.name for tool in registry.list_all()}
    removed_directory_tool = "directory" + "_lister"

    assert len(names) == 11
    assert {
        "command_executor",
        "embedder",
        "file_reader",
        "file_writer",
        "multi_file_reader",
        "web_searcher",
    }.issubset(names)
    assert removed_directory_tool not in names
    assert "autonomy_tool" not in names
    assert "project_environment_tool" not in names
    assert "memory_context" not in names
    assert "project_state_reader" not in names
    assert "project_improvement_tool" not in names


def test_core_imports_remain_available() -> None:
    from core.openpilot_log import OpenPilotLogger as ImportedLogger
    from autonomous_iteration.intelligent_autopilot import IntelligentAutopilot
    from memory.memory_store import MemoryStore
    from tools.tool_executor import ToolExecutor as ImportedToolExecutor

    assert IntelligentAutopilot is not None
    assert ImportedToolExecutor is ToolExecutor
    assert MemoryStore is not None
    assert ImportedLogger is OpenPilotLogger


def test_config_check_cli_returns_success() -> None:
    from ui.cli import main

    assert main(["config", "check"]) == 0


def test_tool_executor_rejects_missing_required_input() -> None:
    registry = _registered_registry()
    executor = ToolExecutor(registry)
    try:
        result = executor.execute_single(
            ToolSelection(
                step_id="read-file",
                tool_name="file_reader",
                reason="capability_match",
                input_params={},
            )
        )
    finally:
        executor.shutdown()

    assert not result.success
    assert result.error is not None
    assert result.error.error_type == "InvalidInput"
    assert "file_path" in result.error.error_message
    assert result.error.recoverable
    assert result.error.retry_recommended
    assert result.metadata["failure_mode"] == "invalid_input"
    assert "required parameters" in result.metadata["recovery_strategy"]


def test_tool_executor_reads_file_and_applies_defaults(tmp_path) -> None:
    target = tmp_path / "hello.txt"
    target.write_text("hello openpilot", encoding="utf-8")
    registry = _registered_registry()
    executor = ToolExecutor(registry)
    selection = ToolSelection(
        step_id="read-file",
        tool_name="file_reader",
        reason="capability_match",
        input_params={"file_path": str(target)},
    )
    try:
        result = executor.execute_single(selection)
    finally:
        executor.shutdown()

    assert result.success
    assert result.output["content"] == "hello openpilot"
    assert result.output["encoding"] == "utf-8"
    assert result.output["file_type"] == "data"
    assert result.output["truncated"] is False
    assert selection.input_params["encoding"] == "utf-8"
    assert selection.input_params["max_size_mb"] == 10


def test_file_reader_supports_sample_mode(tmp_path) -> None:
    target = tmp_path / "sample.log"
    target.write_text("one\ntwo\nthree\n", encoding="utf-8")
    registry = _registered_registry()
    executor = ToolExecutor(registry)
    try:
        result = executor.execute_single(
            ToolSelection(
                step_id="sample-file",
                tool_name="file_reader",
                reason="capability_match",
                input_params={
                    "file_path": str(target),
                    "read_mode": "sample",
                    "max_lines": 2,
                },
            )
        )
    finally:
        executor.shutdown()

    assert result.success
    assert result.output["content"] == "one\ntwo\n"
    assert result.output["lines_read"] == 2
    assert result.output["total_lines"] == 3
    assert result.output["truncated"] is True
    assert result.output["metadata"]["read_mode"] == "sample"


def test_file_reader_supports_tail_mode(tmp_path) -> None:
    target = tmp_path / "tail.log"
    target.write_text("one\ntwo\nthree\n", encoding="utf-8")
    registry = _registered_registry()
    executor = ToolExecutor(registry)
    try:
        result = executor.execute_single(
            ToolSelection(
                step_id="tail-file",
                tool_name="file_reader",
                reason="capability_match",
                input_params={
                    "file_path": str(target),
                    "read_mode": "tail",
                    "max_lines": 2,
                },
            )
        )
    finally:
        executor.shutdown()

    assert result.success
    assert result.output["content"] == "two\nthree\n"
    assert result.output["lines_read"] == 2
    assert result.output["total_lines"] == 3
    assert result.output["truncated"] is True
    assert result.output["metadata"]["read_mode"] == "tail"


def test_file_reader_adaptive_mode_samples_log_files(tmp_path) -> None:
    target = tmp_path / "events.log"
    target.write_text("first\nsecond\nthird\n", encoding="utf-8")
    registry = _registered_registry()
    executor = ToolExecutor(registry)
    try:
        result = executor.execute_single(
            ToolSelection(
                step_id="adaptive-file",
                tool_name="file_reader",
                reason="capability_match",
                input_params={
                    "file_path": str(target),
                    "read_mode": "adaptive",
                    "max_lines": 2,
                },
            )
        )
    finally:
        executor.shutdown()

    assert result.success
    assert result.output["file_type"] == "log"
    assert result.output["content"] == "first\nsecond\n"
    assert result.output["truncated"] is True
    assert result.output["metadata"]["read_mode"] == "adaptive"


def test_file_reader_returns_placeholder_for_binary_files(tmp_path) -> None:
    target = tmp_path / "image.png"
    target.write_bytes(b"\x89PNG\r\n\x1a\n")
    registry = _registered_registry()
    executor = ToolExecutor(registry)
    try:
        result = executor.execute_single(
            ToolSelection(
                step_id="binary-file",
                tool_name="file_reader",
                reason="capability_match",
                input_params={"file_path": str(target)},
            )
        )
    finally:
        executor.shutdown()

    assert result.success
    assert result.output["content"] == "[Binary file - content not displayed]"
    assert result.output["file_type"] == "binary"
    assert result.output["encoding"] == "binary"
    assert result.output["lines_read"] == 0


def test_multi_file_reader_scans_directory_with_glob(tmp_path) -> None:
    first = tmp_path / "alpha完成报告.md"
    second = tmp_path / "beta完成报告.md"
    ignored = tmp_path / "notes.txt"
    first.write_text("alpha", encoding="utf-8")
    second.write_text("beta", encoding="utf-8")
    ignored.write_text("ignored", encoding="utf-8")

    registry = _registered_registry()
    executor = ToolExecutor(registry)
    try:
        result = executor.execute_single(
            ToolSelection(
                step_id="read-matching-files",
                tool_name="multi_file_reader",
                reason="capability_match",
                input_params={
                    "directory_path": str(tmp_path),
                    "pattern": "*完成报告.md",
                },
            )
        )
    finally:
        executor.shutdown()

    assert result.success
    assert result.output["count"] == 2
    assert result.output["files"] == [str(first), str(second)]
    assert "alpha" in result.output["content"]
    assert "beta" in result.output["content"]
    assert "ignored" not in result.output["content"]


def test_code_reviewer_rejects_non_pygame_when_pygame_is_product_fit() -> None:
    result = code_reviewer_executor(
        {
            "code": "print('hi')\n",
            "language": "python",
            "prompt_context": {
                "product_judgment": {
                    "preferred_stack": "pygame",
                }
            },
        }
    )

    assert result["approved"] is False
    assert any("standalone pygame GUI" in item for item in result["warnings"])
    assert any("standalone pygame GUI" in item for item in result["suggestions"])


def test_code_reviewer_rejects_curses_when_pygame_is_product_fit() -> None:
    result = code_reviewer_executor(
        {
            "code": "import curses\n\ndef main(stdscr):\n    pass\n",
            "language": "python",
            "prompt_context": {
                "product_judgment": {
                    "preferred_stack": "pygame",
                }
            },
        }
    )

    assert result["approved"] is False
    assert any("terminal/curses to pygame" in item for item in result["warnings"])
    assert any("terminal/curses to pygame" in item for item in result["suggestions"])


def test_code_reviewer_allows_pygame_code_without_product_fit_warning() -> None:
    result = code_reviewer_executor(
        {
            "code": "import pygame\npygame.init()\n",
            "language": "python",
            "prompt_context": {
                "product_judgment": {
                    "preferred_stack": "pygame",
                }
            },
        }
    )

    assert not any("Product-fit rubric not satisfied" in item for item in result["warnings"])
    assert not any("Product-fit rubric not satisfied" in item for item in result["suggestions"])


def test_tool_executor_records_output_schema_warnings() -> None:
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="partial_output_tool",
            display_name="Partial Output Tool",
            description="Returns an incomplete object to exercise warnings",
            permission_level=PermissionLevel.LOW,
            input_schema=[],
            output_schema=ToolOutputSchema(
                type="object",
                description="Expected output",
                properties={
                    "present": {"type": "string"},
                    "missing": {"type": "integer"},
                },
            ),
            audit_required=False,
        ),
        lambda params: {"present": "yes"},
    )
    executor = ToolExecutor(registry)
    try:
        result = executor.execute_single(
            ToolSelection(
                step_id="partial-output",
                tool_name="partial_output_tool",
                reason="capability_match",
                input_params={},
            )
        )
    finally:
        executor.shutdown()

    assert result.success
    assert result.metadata["validation_warnings"] == [
        "Output for partial_output_tool is missing declared property: missing"
    ]


def test_command_executor_defaults_to_dry_run(tmp_path) -> None:
    target = tmp_path / "should_not_exist.txt"
    registry = _registered_registry()
    executor = ToolExecutor(registry)
    try:
        result = executor.execute_single(
            ToolSelection(
                step_id="dry-run-command",
                tool_name="command_executor",
                reason="capability_match",
                input_params={"command": f"touch {target}"},
            )
        )
    finally:
        executor.shutdown()

    assert result.success
    assert result.output["stdout"].startswith("[DRY RUN]")
    assert result.output["exit_code"] == 0
    assert result.output["risk_assessment"]["risk_level"] == "medium"
    assert not target.exists()


def test_command_executor_automatic_runs_low_risk_command() -> None:
    registry = _registered_registry()
    executor = ToolExecutor(registry)
    try:
        result = executor.execute_single(
            ToolSelection(
                step_id="automatic-command",
                tool_name="command_executor",
                reason="capability_match",
                input_params={
                    "command": f"{sys.executable} -c \"print('ok')\"",
                    "mode": "automatic",
                    "timeout": 10,
                },
            )
        )
    finally:
        executor.shutdown()

    assert result.success
    assert result.output["success"]
    assert result.output["stdout"].strip() == "ok"
    assert result.output["stderr"] == ""
    assert result.output["exit_code"] == 0


def test_web_searcher_requires_query() -> None:
    registry = _registered_registry()
    executor = ToolExecutor(registry)
    try:
        result = executor.execute_single(
            ToolSelection(
                step_id="search-missing-query",
                tool_name="web_searcher",
                reason="capability_match",
                input_params={},
            )
        )
    finally:
        executor.shutdown()

    assert not result.success
    assert result.error is not None
    assert result.error.error_type == "InvalidInput"
    assert "query" in result.error.error_message


def test_web_searcher_parses_duckduckgo_html_without_network() -> None:
    html = """
    <html>
      <body>
        <a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Falpha&amp;rut=abc">Alpha Result</a>
        <a class="result__snippet">Alpha snippet with details.</a>
        <a class="result__a" href="https://docs.example.org/beta">Beta Result</a>
        <div class="result__snippet">Beta snippet.</div>
      </body>
    </html>
    """

    def fake_http_get(url: str, timeout: int) -> str:
        assert "q=openpilot+research" in url
        assert timeout == 7
        return html

    registry = _registered_registry()
    executor = ToolExecutor(registry)
    try:
        result = executor.execute_single(
            ToolSelection(
                step_id="search-web",
                tool_name="web_searcher",
                reason="capability_match",
                input_params={
                    "query": "openpilot research",
                    "max_results": 1,
                    "max_pages": 0,
                    "timeout": 7,
                    "llm_cleanup": False,
                    "_http_get": fake_http_get,
                },
            )
        )
    finally:
        executor.shutdown()

    assert result.success
    assert result.output["provider"] == "duckduckgo_html"
    assert result.output["count"] == 1
    assert result.output["llm_cleanup"] is False
    assert result.output["results"][0] == {
        "rank": 1,
        "title": "Alpha Result",
        "url": "https://example.com/alpha",
        "snippet": "Alpha snippet with details.",
        "source_domain": "example.com",
    }
    assert result.output["warnings"] == []


def test_web_searcher_empty_results_return_warning_without_failure() -> None:
    registry = _registered_registry()
    executor = ToolExecutor(registry)
    try:
        result = executor.execute_single(
            ToolSelection(
                step_id="search-empty",
                tool_name="web_searcher",
                reason="capability_match",
                input_params={
                    "query": "nothing",
                    "llm_cleanup": False,
                    "_http_get": lambda url, timeout: "<html><body>No results</body></html>",
                },
            )
        )
    finally:
        executor.shutdown()

    assert result.success
    assert result.output["count"] == 0
    assert result.output["results"] == []
    assert result.output["warnings"]


def test_web_searcher_network_errors_are_reported() -> None:
    def failing_http_get(url: str, timeout: int) -> str:
        raise OSError("network down")

    registry = _registered_registry()
    executor = ToolExecutor(registry)
    try:
        result = executor.execute_single(
            ToolSelection(
                step_id="search-network-failure",
                tool_name="web_searcher",
                reason="capability_match",
                input_params={
                    "query": "openpilot",
                    "_http_get": failing_http_get,
                },
            )
        )
    finally:
        executor.shutdown()

    assert not result.success
    assert result.error is not None
    assert "Search request failed" in result.error.error_message


def test_web_searcher_fetches_pages_and_cleans_with_llm_without_network() -> None:
    search_html = """
    <a class="result__a" href="https://example.com/alpha">Alpha Result</a>
    <a class="result__snippet">Alpha snippet.</a>
    <a class="result__a" href="https://example.org/beta">Beta Result</a>
    <a class="result__snippet">Beta snippet.</a>
    """
    pages = {
        "https://example.com/alpha": """
        <html><head><title>Alpha Page</title><script>ignore()</script></head>
        <body><nav>menu</nav><main><h1>Alpha heading</h1>
        <p>Alpha useful paragraph with enough detail for extraction.</p>
        <p>Alpha useful paragraph with enough detail for extraction.</p></main></body></html>
        """,
        "https://example.org/beta": """
        <html><head><title>Beta Page</title></head>
        <body><article><p>Beta useful paragraph with distinct research details.</p></article></body></html>
        """,
    }

    def fake_http_get(url: str, timeout: int) -> str:
        if "duckduckgo.com" in url:
            return search_html
        return pages[url]

    fake_llm = FakeCleanupLLM()
    result = web_searcher_executor(
        {
            "query": "openpilot research",
            "max_results": 2,
            "max_pages": 2,
            "max_page_chars": 500,
            "_http_get": fake_http_get,
            "_llm_client": fake_llm,
        }
    )

    assert result["llm_cleanup"] is True
    assert len(fake_llm.requests) == 1
    assert len(result["pages"]) == 2
    assert result["pages"][0]["title"] == "Alpha Page"
    assert result["pages"][0]["fetch_success"] is True
    assert "menu" not in result["pages"][0]["content_excerpt"]
    assert "Alpha useful paragraph" in result["pages"][0]["content_excerpt"]
    assert result["research_summary"] == "Clean summary"
    assert result["key_points"] == ["Useful fact"]
    assert result["source_notes"] == [{"url": "https://example.com/alpha", "note": "Primary source"}]
    assert result["follow_up_queries"] == ["openpilot follow up"]


def test_web_searcher_max_pages_zero_skips_page_fetch_and_cleanup() -> None:
    html = '<a class="result__a" href="https://example.com/a">A</a><a class="result__snippet">A snippet</a>'

    def fake_http_get(url: str, timeout: int) -> str:
        assert "duckduckgo.com" in url
        return html

    fake_llm = FakeCleanupLLM()
    result = web_searcher_executor(
        {
            "query": "openpilot",
            "max_pages": 0,
            "_http_get": fake_http_get,
            "_llm_client": fake_llm,
        }
    )

    assert result["count"] == 1
    assert result["pages"] == []
    assert result["llm_cleanup"] is False
    assert fake_llm.requests == []


def test_web_searcher_llm_cleanup_false_skips_llm() -> None:
    html = '<a class="result__a" href="https://example.com/a">A</a><a class="result__snippet">A snippet</a>'

    def fake_http_get(url: str, timeout: int) -> str:
        if "duckduckgo.com" in url:
            return html
        return "<html><body><p>Readable page content with useful details.</p></body></html>"

    fake_llm = FakeCleanupLLM()
    result = web_searcher_executor(
        {
            "query": "openpilot",
            "llm_cleanup": False,
            "_http_get": fake_http_get,
            "_llm_client": fake_llm,
        }
    )

    assert result["pages"][0]["fetch_success"] is True
    assert result["llm_cleanup"] is False
    assert result["research_summary"] == ""
    assert result["key_points"] == []
    assert fake_llm.requests == []


def test_web_searcher_page_fetch_failure_is_nonfatal() -> None:
    html = '<a class="result__a" href="https://example.com/a">A</a><a class="result__snippet">A snippet</a>'

    def fake_http_get(url: str, timeout: int) -> str:
        if "duckduckgo.com" in url:
            return html
        raise OSError("page down")

    result = web_searcher_executor(
        {
            "query": "openpilot",
            "llm_cleanup": False,
            "_http_get": fake_http_get,
        }
    )

    assert result["pages"][0]["fetch_success"] is False
    assert result["pages"][0]["error"] == "page down"
    assert any("Failed to fetch https://example.com/a" in warning for warning in result["warnings"])


def test_web_searcher_llm_cleanup_failure_is_reported() -> None:
    html = '<a class="result__a" href="https://example.com/a">A</a><a class="result__snippet">A snippet</a>'

    def fake_http_get(url: str, timeout: int) -> str:
        if "duckduckgo.com" in url:
            return html
        return "<html><body><p>Readable page content with useful details.</p></body></html>"

    try:
        web_searcher_executor(
            {
                "query": "openpilot",
                "_http_get": fake_http_get,
                "_llm_client": FakeCleanupLLM(fail=True),
            }
        )
    except RuntimeError as exc:
        assert "LLM cleanup failed" in str(exc)
    else:
        raise AssertionError("Expected LLM cleanup failure")


def test_embedder_uses_injected_service_without_network() -> None:
    class FakeEmbeddingService:
        provider = "fake"
        model = "fake-embedding"

        def embed_text(self, text: str, use_cache: bool = True) -> list[float]:
            assert text == "hello semantic world"
            assert use_cache is False
            return [0.1, 0.2, 0.3]

    registry = _registered_registry()
    executor = ToolExecutor(registry)
    try:
        result = executor.execute_single(
            ToolSelection(
                step_id="embed-query",
                tool_name="embedder",
                reason="capability_match",
                input_params={
                    "query": "hello semantic world",
                    "use_cache": False,
                    "_embedding_service": FakeEmbeddingService(),
                },
            )
        )
    finally:
        executor.shutdown()

    assert result.success
    assert result.output == {
        "embedding": [0.1, 0.2, 0.3],
        "dimension": 3,
        "model": "fake-embedding",
        "provider": "fake",
        "cached": False,
    }


def test_logger_writes_legacy_and_structured_jsonl(tmp_path) -> None:
    log_file = tmp_path / "openpilot.jsonl"
    logger = OpenPilotLogger(log_file)

    logger.log_event(
        "legacy_event",
        {"message": "ok"},
        session_id="session-1",
        turn_id=1,
    )
    logger.log_structured_event(
        source_type="tool",
        source_name="file_reader",
        phase="pre_execution",
        event_type="structured_event",
        session_id="session-1",
        turn_id=2,
        success=True,
        duration_ms=3,
        input_summary={"file_path": "demo.txt"},
        output_summary={"size_bytes": 4},
        metadata={"contract": "phase1"},
    )

    events = [
        json.loads(line)
        for line in log_file.read_text(encoding="utf-8").splitlines()
    ]

    assert [event["event_type"] for event in events] == [
        "legacy_event",
        "structured_event",
    ]
    assert events[0]["payload"] == {"message": "ok"}
    assert events[1]["payload"]["source_type"] == "tool"
    assert events[1]["payload"]["source_name"] == "file_reader"
    assert events[1]["payload"]["metadata"] == {"contract": "phase1"}
