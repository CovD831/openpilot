"""Web Searcher Tool - Search, fetch, and clean public web research results."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from html import unescape
from html.parser import HTMLParser
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, quote_plus, unquote, urlencode, urlparse
from urllib.request import Request, urlopen

from core.llm import LLMClient, LLMMessage, LLMRequest
from core.tool_contracts import (
    PermissionLevel,
    ToolCapability,
    ToolDefinition,
    ToolFailureMode,
    ToolInputSchema,
    ToolOutputSchema,
)


WEB_SEARCHER_DEFINITION = ToolDefinition(
    name="web_searcher",
    display_name="Web Searcher",
    description="Search the public web, fetch result pages, and clean research content with an LLM",
    version="1.1.0",
    capabilities=[ToolCapability.WEB_SEARCH, ToolCapability.NETWORK, ToolCapability.LLM_CALL],
    permission_level=PermissionLevel.MEDIUM,
    input_schema=[
        ToolInputSchema(
            name="query",
            type="string",
            description="Search query",
            required=True,
        ),
        ToolInputSchema(
            name="max_results",
            type="integer",
            description="Maximum number of results to return, clamped to 1-10",
            required=False,
            default=5,
        ),
        ToolInputSchema(
            name="region",
            type="string",
            description="DuckDuckGo region code",
            required=False,
            default="wt-wt",
        ),
        ToolInputSchema(
            name="time_range",
            type="string",
            description="Time range: all, day, week, month, or year",
            required=False,
            default="all",
        ),
        ToolInputSchema(
            name="safe_search",
            type="string",
            description="Safe search: off, moderate, or strict",
            required=False,
            default="moderate",
        ),
        ToolInputSchema(
            name="timeout",
            type="integer",
            description="HTTP timeout in seconds",
            required=False,
            default=10,
        ),
        ToolInputSchema(
            name="max_pages",
            type="integer",
            description="Maximum result pages to fetch and clean, clamped to 0-5",
            required=False,
            default=3,
        ),
        ToolInputSchema(
            name="max_page_chars",
            type="integer",
            description="Maximum extracted text characters per page, clamped to 500-12000",
            required=False,
            default=4000,
        ),
        ToolInputSchema(
            name="llm_cleanup",
            type="boolean",
            description="Use an LLM to remove noise and organize fetched content",
            required=False,
            default=True,
        ),
        ToolInputSchema(
            name="cleanup_instruction",
            type="string",
            description="Additional instructions for organizing the research result",
            required=False,
            default="Remove navigation, ads, duplicates, and unsupported claims. Organize facts by source and keep the answer concise.",
        ),
    ],
    output_schema=ToolOutputSchema(
        type="object",
        description="Structured web search results, fetched pages, and cleaned research summary",
        properties={
            "query": {"type": "string", "description": "Search query"},
            "provider": {"type": "string", "description": "Search provider used"},
            "results": {"type": "array", "description": "Search result records"},
            "count": {"type": "integer", "description": "Number of returned results"},
            "pages": {"type": "array", "description": "Fetched page excerpts and status"},
            "llm_cleanup": {"type": "boolean", "description": "Whether LLM cleanup was executed"},
            "research_summary": {"type": "string", "description": "Cleaned research summary"},
            "key_points": {"type": "array", "description": "Important facts extracted from sources"},
            "source_notes": {"type": "array", "description": "Source-specific notes"},
            "follow_up_queries": {"type": "array", "description": "Suggested follow-up searches"},
            "fetched_at": {"type": "string", "description": "UTC timestamp"},
            "warnings": {"type": "array", "description": "Non-fatal warnings"},
        },
    ),
    timeout_seconds=30,
    max_retries=1,
    failure_modes=[
        ToolFailureMode(
            error_type="invalid_input",
            description="Search parameters are invalid",
            recovery_strategy="Provide a non-empty query and supported search options",
        ),
        ToolFailureMode(
            error_type="network_error",
            description="Search provider request failed",
            recovery_strategy="Retry later or narrow the query",
        ),
        ToolFailureMode(
            error_type="parse_error",
            description="Search response could not be parsed",
            recovery_strategy="Retry later or use another provider",
        ),
        ToolFailureMode(
            error_type="llm_error",
            description="LLM cleanup failed",
            recovery_strategy="Disable llm_cleanup or check LLM provider configuration",
        ),
    ],
    tags=["web", "search", "research", "internet", "network", "llm"],
    audit_required=True,
)


TIME_RANGE_PARAMS = {
    "all": None,
    "day": "d",
    "week": "w",
    "month": "m",
    "year": "y",
}

SAFE_SEARCH_PARAMS = {
    "off": "-2",
    "moderate": "-1",
    "strict": "1",
}


class SearchResultHTMLParser(HTMLParser):
    """Extract result title/link/snippet triples from simple search-result HTML."""

    def __init__(self, provider: str) -> None:
        super().__init__(convert_charrefs=True)
        self.provider = provider
        self.results: list[dict[str, str]] = []
        self._current: dict[str, str] | None = None
        self._capture_title = False
        self._capture_snippet = False
        self._title_parts: list[str] = []
        self._snippet_parts: list[str] = []
        self._bing_result_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = {name: value or "" for name, value in attrs}
        classes = set(attrs_dict.get("class", "").split())
        if self.provider == "bing_html" and "b_algo" in classes:
            self._finish_current()
            self._bing_result_depth = 1
            return
        if self._bing_result_depth:
            self._bing_result_depth += 1

        if tag == "a" and self._is_result_link(classes, attrs_dict):
            self._finish_current()
            self._current = {
                "title": "",
                "url": _normalize_result_url(attrs_dict.get("href", "")),
                "snippet": "",
            }
            self._capture_title = True
            self._title_parts = []
            return

        if self._current is not None and self._is_snippet(tag, classes):
            self._capture_snippet = True
            self._snippet_parts = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._capture_title and self._current is not None:
            self._current["title"] = _clean_text(" ".join(self._title_parts))
            self._capture_title = False

        if self._capture_snippet and self._current is not None and tag in {"a", "div", "span"}:
            self._current["snippet"] = _clean_text(" ".join(self._snippet_parts))
            self._capture_snippet = False

        if self._capture_snippet and self.provider == "bing_html" and tag == "p" and self._current is not None:
            self._current["snippet"] = _clean_text(" ".join(self._snippet_parts))
            self._capture_snippet = False

        if self._bing_result_depth:
            self._bing_result_depth -= 1
            if self._bing_result_depth == 0:
                self._finish_current()

    def handle_data(self, data: str) -> None:
        if self._capture_title:
            self._title_parts.append(data)
        if self._capture_snippet:
            self._snippet_parts.append(data)

    def close(self) -> None:
        super().close()
        self._finish_current()

    def _finish_current(self) -> None:
        if not self._current:
            return
        if self._current.get("title") and self._current.get("url"):
            self.results.append(self._current)
        self._current = None

    def _is_result_link(self, classes: set[str], attrs: dict[str, str]) -> bool:
        if self.provider == "duckduckgo_html":
            return "result__a" in classes
        if self.provider == "bing_html":
            return self._bing_result_depth > 0 and bool(attrs.get("href", "").startswith(("http://", "https://")))
        return False

    def _is_snippet(self, tag: str, classes: set[str]) -> bool:
        if self.provider == "duckduckgo_html":
            return "result__snippet" in classes
        if self.provider == "bing_html":
            return self._bing_result_depth > 0 and tag == "p"
        return False


class ReadableHTMLTextParser(HTMLParser):
    """Extract visible-ish text from simple HTML pages."""

    BLOCK_TAGS = {"article", "main", "section", "p", "div", "li", "h1", "h2", "h3", "h4", "blockquote"}
    SKIP_TAGS = {"script", "style", "noscript", "svg", "canvas", "nav", "footer", "header", "form"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title = ""
        self._title_parts: list[str] = []
        self._capture_title = False
        self._skip_depth = 0
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self.SKIP_TAGS:
            self._skip_depth += 1
            return
        if tag == "title":
            self._capture_title = True
            self._title_parts = []
            return
        if tag in self.BLOCK_TAGS:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self.SKIP_TAGS and self._skip_depth:
            self._skip_depth -= 1
            return
        if tag == "title":
            self.title = _clean_text(" ".join(self._title_parts))
            self._capture_title = False
            return
        if tag in self.BLOCK_TAGS:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        if self._capture_title:
            self._title_parts.append(data)
            return
        text = _clean_text(data)
        if text:
            self._parts.append(text)

    def readable_text(self) -> str:
        lines = []
        for line in " ".join(self._parts).splitlines():
            cleaned = _clean_text(line)
            if len(cleaned) >= 20:
                lines.append(cleaned)
        return "\n".join(_dedupe_preserve_order(lines))


def web_searcher_executor(params: dict[str, Any]) -> dict[str, Any]:
    """Search the web, fetch result pages, and return cleaned research data."""
    query = str(params.get("query", "")).strip()
    if not query:
        raise ValueError("Search query cannot be empty")

    max_results = _clamp_int(params.get("max_results", 5), minimum=1, maximum=10)
    max_pages = _clamp_int(params.get("max_pages", 3), minimum=0, maximum=5)
    max_page_chars = _clamp_int(params.get("max_page_chars", 4000), minimum=500, maximum=12000)
    region = str(params.get("region", "wt-wt") or "wt-wt")
    time_range = str(params.get("time_range", "all") or "all").lower()
    safe_search = str(params.get("safe_search", "moderate") or "moderate").lower()
    timeout = _clamp_int(params.get("timeout", 10), minimum=1, maximum=30)
    llm_cleanup_requested = params.get("llm_cleanup", True)
    if not isinstance(llm_cleanup_requested, bool):
        raise ValueError("llm_cleanup must be a boolean")
    cleanup_instruction = str(
        params.get(
            "cleanup_instruction",
            "Remove navigation, ads, duplicates, and unsupported claims. Organize facts by source and keep the answer concise.",
        )
        or ""
    )

    if time_range not in TIME_RANGE_PARAMS:
        raise ValueError(f"Unsupported time_range: {time_range}")
    if safe_search not in SAFE_SEARCH_PARAMS:
        raise ValueError(f"Unsupported safe_search: {safe_search}")

    http_get = params.get("_http_get") or _default_http_get
    injected_http_get = "_http_get" in params

    attempts = [("duckduckgo_html", _build_duckduckgo_search_url(query, region, time_range, safe_search))]
    if not injected_http_get:
        attempts.append(("bing_html", _build_bing_search_url(query, safe_search)))

    provider = ""
    parsed_results: list[dict[str, str]] = []
    warnings = []
    errors = []
    for candidate_provider, search_url in attempts:
        try:
            html = http_get(search_url, timeout)
            parsed_results = _parse_search_results(html, candidate_provider)
            provider = candidate_provider
            break
        except TimeoutError as exc:
            errors.append(f"{candidate_provider}: timed out ({exc})")
            if injected_http_get:
                raise TimeoutError(f"Search request timed out: {exc}") from exc
        except (HTTPError, URLError, OSError) as exc:
            errors.append(f"{candidate_provider}: {exc}")
            if injected_http_get:
                raise ConnectionError(f"Search request failed: {exc}") from exc
        except Exception as exc:
            errors.append(f"{candidate_provider}: {exc}")
            if injected_http_get:
                raise ConnectionError(f"Search request failed: {exc}") from exc

    if not provider:
        raise ConnectionError(f"Search request failed: {'; '.join(errors)}")

    if errors:
        warnings.append(f"Fallback provider used after: {'; '.join(errors)}")

    if not parsed_results:
        warnings.append(f"No search results were parsed from {provider} response.")

    results = [
        {
            "rank": index + 1,
            "title": item["title"],
            "url": item["url"],
            "snippet": item.get("snippet", ""),
            "source_domain": _domain_from_url(item["url"]),
        }
        for index, item in enumerate(parsed_results[:max_results])
    ]

    pages = _fetch_result_pages(
        results=results[:max_pages],
        http_get=http_get,
        timeout=timeout,
        max_page_chars=max_page_chars,
        warnings=warnings,
    )
    cleanup_payload = _empty_cleanup_payload()
    llm_cleanup_executed = False
    if llm_cleanup_requested and pages:
        cleanup_payload = _clean_with_llm(
            query=query,
            results=results,
            pages=pages,
            cleanup_instruction=cleanup_instruction,
            llm_client=params.get("_llm_client"),
        )
        llm_cleanup_executed = True

    return {
        "query": query,
        "provider": provider,
        "results": results,
        "count": len(results),
        "pages": pages,
        "llm_cleanup": llm_cleanup_executed,
        **cleanup_payload,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "warnings": warnings,
    }


def _build_duckduckgo_search_url(query: str, region: str, time_range: str, safe_search: str) -> str:
    query_params = {
        "q": query,
        "kl": region,
        "kp": SAFE_SEARCH_PARAMS[safe_search],
    }
    time_param = TIME_RANGE_PARAMS[time_range]
    if time_param:
        query_params["df"] = time_param
    return f"https://html.duckduckgo.com/html/?{urlencode(query_params, quote_via=quote_plus)}"


def _build_bing_search_url(query: str, safe_search: str) -> str:
    query_params = {
        "q": query,
        "safeSearch": {
            "off": "Off",
            "moderate": "Moderate",
            "strict": "Strict",
        }[safe_search],
    }
    return f"https://www.bing.com/search?{urlencode(query_params, quote_via=quote_plus)}"


def _default_http_get(url: str, timeout: int) -> str:
    request = Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (compatible; OpenPilotWebSearcher/1.0; "
                "+https://example.invalid/openpilot)"
            )
        },
    )
    with urlopen(request, timeout=timeout) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, errors="replace")


def _parse_search_results(html: str, provider: str) -> list[dict[str, str]]:
    parser = SearchResultHTMLParser(provider)
    parser.feed(html)
    parser.close()
    return parser.results


def _fetch_result_pages(
    *,
    results: list[dict[str, Any]],
    http_get: Any,
    timeout: int,
    max_page_chars: int,
    warnings: list[str],
) -> list[dict[str, Any]]:
    pages = []
    for result in results:
        page = {
            "url": result["url"],
            "title": result.get("title", ""),
            "source_domain": result.get("source_domain", ""),
            "content_excerpt": "",
            "content_chars": 0,
            "fetch_success": False,
            "error": None,
        }
        try:
            html = http_get(result["url"], timeout)
            title, text = _extract_readable_page_text(html)
            excerpt = text[:max_page_chars]
            page.update(
                {
                    "title": title or page["title"],
                    "content_excerpt": excerpt,
                    "content_chars": len(excerpt),
                    "fetch_success": True,
                }
            )
        except Exception as exc:
            page["error"] = str(exc)
            warnings.append(f"Failed to fetch {result['url']}: {exc}")
        pages.append(page)
    return pages


def _extract_readable_page_text(html: str) -> tuple[str, str]:
    parser = ReadableHTMLTextParser()
    parser.feed(html)
    parser.close()
    return parser.title, parser.readable_text()


def _clean_with_llm(
    *,
    query: str,
    results: list[dict[str, Any]],
    pages: list[dict[str, Any]],
    cleanup_instruction: str,
    llm_client: Any | None,
) -> dict[str, Any]:
    if llm_client is None:
        from core.config import LLMSettings

        llm_client = LLMClient(LLMSettings())

    prompt = _build_cleanup_prompt(
        query=query,
        results=results,
        pages=pages,
        cleanup_instruction=cleanup_instruction,
    )
    try:
        response = llm_client.complete(
            LLMRequest(
                messages=[
                    LLMMessage(
                        role="system",
                        content=(
                            "You clean and organize web research. Use only the supplied "
                            "search results and fetched page excerpts. Do not invent facts."
                        ),
                    ),
                    LLMMessage(role="user", content=prompt),
                ],
                response_format="json_object",
                temperature=0.1,
                max_tokens=900,
                metadata={"tool": "web_searcher", "task": "cleanup"},
            )
        )
    except Exception as exc:
        raise RuntimeError(f"LLM cleanup failed: {exc}") from exc

    payload = response.parsed_json
    if payload is None:
        try:
            payload = json.loads(response.content)
        except Exception as exc:
            raise RuntimeError(f"LLM cleanup failed: invalid JSON response: {exc}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("LLM cleanup failed: response JSON root must be an object")

    return {
        "research_summary": str(payload.get("research_summary", "") or ""),
        "key_points": _string_list(payload.get("key_points")),
        "source_notes": _source_notes(payload.get("source_notes")),
        "follow_up_queries": _string_list(payload.get("follow_up_queries")),
    }


def _build_cleanup_prompt(
    *,
    query: str,
    results: list[dict[str, Any]],
    pages: list[dict[str, Any]],
    cleanup_instruction: str,
) -> str:
    payload = {
        "query": query,
        "cleanup_instruction": cleanup_instruction,
        "search_results": results,
        "fetched_pages": [
            {
                "url": page["url"],
                "title": page["title"],
                "source_domain": page["source_domain"],
                "content_excerpt": page["content_excerpt"],
                "fetch_success": page["fetch_success"],
                "error": page["error"],
            }
            for page in pages
        ],
    }
    return (
        "Clean noisy webpage text and organize the research. Return ONLY JSON with keys: "
        "research_summary (string), key_points (array of strings), source_notes "
        "(array of objects with url and note), follow_up_queries (array of strings).\n\n"
        f"{json.dumps(payload, ensure_ascii=False, indent=2)}"
    )


def _empty_cleanup_payload() -> dict[str, Any]:
    return {
        "research_summary": "",
        "key_points": [],
        "source_notes": [],
        "follow_up_queries": [],
    }


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if item is not None]


def _source_notes(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    notes = []
    for item in value:
        if isinstance(item, dict):
            notes.append(
                {
                    "url": str(item.get("url", "") or ""),
                    "note": str(item.get("note", "") or ""),
                }
            )
        elif item is not None:
            notes.append({"url": "", "note": str(item)})
    return notes


def _normalize_result_url(url: str) -> str:
    url = unescape(url or "").strip()
    if not url:
        return ""
    if url.startswith("//"):
        url = f"https:{url}"

    parsed = urlparse(url)
    if "duckduckgo.com" in parsed.netloc and parsed.path.startswith("/l/"):
        target = parse_qs(parsed.query).get("uddg", [""])[0]
        if target:
            return unquote(target)

    return url


def _domain_from_url(url: str) -> str:
    return urlparse(url).netloc.lower().removeprefix("www.")


def _clean_text(value: str) -> str:
    return " ".join(unescape(value).split())


def _dedupe_preserve_order(values: list[str]) -> list[str]:
    seen = set()
    result = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _clamp_int(value: Any, *, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Expected integer value, got {value!r}") from exc
    return max(minimum, min(maximum, parsed))
