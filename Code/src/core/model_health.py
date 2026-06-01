"""Non-blocking startup connectivity probes for configured model endpoints."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from time import perf_counter
from typing import Any, Callable

from openai import OpenAI
from rich.console import Console

from core.config import EmbeddingSettings, LLMSettings, ModelHealthSettings


@dataclass(frozen=True)
class ModelConnectivityResult:
    """One startup model probe result suitable for terminal display."""

    model_kind: str
    provider: str
    model: str
    reachable: bool
    latency_ms: int
    detail: str = ""

    @property
    def label(self) -> str:
        return f"{self.model_kind} model {self.model} ({self.provider})"


def check_configured_models(
    *,
    llm_settings: LLMSettings | None = None,
    embedding_settings: EmbeddingSettings | None = None,
    health_settings: ModelHealthSettings | None = None,
    openai_factory: Callable[..., Any] = OpenAI,
) -> list[ModelConnectivityResult]:
    """Probe chat and embedding models concurrently with a small request."""

    llm_settings = llm_settings or LLMSettings()
    embedding_settings = embedding_settings or EmbeddingSettings()
    health_settings = health_settings or ModelHealthSettings()
    if not health_settings.enabled:
        return []

    probes = [
        lambda: _probe_chat_model(llm_settings, health_settings.timeout_seconds, openai_factory),
        lambda: _probe_embedding_model(embedding_settings, health_settings.timeout_seconds, openai_factory),
    ]
    with ThreadPoolExecutor(max_workers=len(probes), thread_name_prefix="openpilot-model-health") as executor:
        return list(executor.map(lambda probe: probe(), probes))


def run_startup_model_health_check(
    console: Console,
    *,
    llm_settings: LLMSettings | None = None,
    embedding_settings: EmbeddingSettings | None = None,
    health_settings: ModelHealthSettings | None = None,
) -> list[ModelConnectivityResult]:
    """Run startup probes and print diagnostics without blocking startup on failure."""

    health_settings = health_settings or ModelHealthSettings()
    if not health_settings.enabled:
        console.print("[dim]Model connectivity check skipped by configuration.[/dim]")
        return []

    try:
        results = check_configured_models(
            llm_settings=llm_settings,
            embedding_settings=embedding_settings,
            health_settings=health_settings,
        )
    except Exception as exc:
        console.print(f"[yellow]WARNING[/yellow] Model connectivity check failed: {_short_error(exc)}")
        return []

    console.print("[bold]Model Connectivity Check[/bold]")
    for result in results:
        if result.reachable:
            console.print(f"[green]OK[/green] {result.label}: reachable ({result.latency_ms} ms)")
            continue
        console.print(
            f"[yellow]WARNING[/yellow] {result.label}: unavailable "
            f"({result.latency_ms} ms) - {result.detail}"
        )
    console.print()
    return results


def _probe_chat_model(
    settings: LLMSettings,
    timeout_seconds: float,
    openai_factory: Callable[..., Any],
) -> ModelConnectivityResult:
    missing = settings.missing_fields()
    if missing:
        return _missing_configuration_result("chat", settings.provider, settings.model, missing)

    def request() -> None:
        client = openai_factory(
            api_key=settings.api_key,
            base_url=settings.base_url,
            timeout=timeout_seconds,
            max_retries=0,
        )
        client.chat.completions.create(
            model=settings.model,
            messages=[{"role": "user", "content": "Reply with OK."}],
            timeout=timeout_seconds,
        )

    return _timed_probe("chat", settings.provider, settings.model, request)


def _probe_embedding_model(
    settings: EmbeddingSettings,
    timeout_seconds: float,
    openai_factory: Callable[..., Any],
) -> ModelConnectivityResult:
    missing = settings.missing_fields()
    if missing:
        return _missing_configuration_result("embedding", settings.provider, settings.model, missing)
    if settings.provider not in {"openai", "openai-compatible"}:
        return ModelConnectivityResult(
            model_kind="embedding",
            provider=settings.provider,
            model=settings.model,
            reachable=False,
            latency_ms=0,
            detail=f"startup probe does not support provider {settings.provider!r}",
        )

    def request() -> None:
        client = openai_factory(
            api_key=settings.api_key,
            base_url=settings.base_url,
            timeout=timeout_seconds,
            max_retries=0,
        )
        client.embeddings.create(
            model=settings.model,
            input="OpenPilot connectivity probe",
            timeout=timeout_seconds,
        )

    return _timed_probe("embedding", settings.provider, settings.model, request)


def _timed_probe(
    model_kind: str,
    provider: str,
    model: str,
    request: Callable[[], None],
) -> ModelConnectivityResult:
    started = perf_counter()
    try:
        request()
    except Exception as exc:
        return ModelConnectivityResult(
            model_kind=model_kind,
            provider=provider,
            model=model,
            reachable=False,
            latency_ms=_elapsed_ms(started),
            detail=_short_error(exc),
        )
    return ModelConnectivityResult(
        model_kind=model_kind,
        provider=provider,
        model=model,
        reachable=True,
        latency_ms=_elapsed_ms(started),
    )


def _missing_configuration_result(
    model_kind: str,
    provider: str,
    model: str,
    missing: list[str],
) -> ModelConnectivityResult:
    return ModelConnectivityResult(
        model_kind=model_kind,
        provider=provider,
        model=model,
        reachable=False,
        latency_ms=0,
        detail=f"missing configuration: {', '.join(missing)}",
    )


def _elapsed_ms(started: float) -> int:
    return max(0, round((perf_counter() - started) * 1000))


def _short_error(exc: BaseException, limit: int = 240) -> str:
    text = " ".join(str(exc).split()) or type(exc).__name__
    return text if len(text) <= limit else f"{text[: limit - 3]}..."
