"""Distributed tracing with OpenTelemetry.

Provides request tracing across services and LLM calls.
"""

import os
from collections.abc import Callable
from contextlib import contextmanager
from typing import Any

from src.config.logging_config import get_logger

logger = get_logger(__name__)

# OpenTelemetry imports (optional dependency)
try:
    from opentelemetry import trace
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
    from opentelemetry.instrumentation.redis import RedisInstrumentor
    from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import ReadableSpan, SpanProcessor, TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    from opentelemetry.trace import Status, StatusCode

    OTEL_AVAILABLE = True
except ImportError:
    OTEL_AVAILABLE = False
    logger.warning(
        "opentelemetry_not_installed", message="Install opentelemetry packages for tracing"
    )

    class SpanProcessor:  # type: ignore[no-redef]
        """Import-safe fallback when OpenTelemetry is not installed."""


    ReadableSpan = Any  # type: ignore[misc, assignment]


# Global tracer
_tracer = None
_provider_initialized = False
_clients_instrumented = False


if OTEL_AVAILABLE:

    class PrometheusSpanProcessor(SpanProcessor):
        """Translate low-cardinality ADK spans into Prometheus metrics."""

        _stage_by_agent = {
            "intent_classifier": "intent",
            "outline_agent": "outline",
            "research_agent": "research",
            "writer_agent": "writer",
            "editor_agent": "editor",
        }

        def on_start(self, span, parent_context=None) -> None:
            pass

        def on_end(self, span: ReadableSpan) -> None:
            try:
                from src.monitoring.metrics import (
                    adk_tool_calls_total,
                    adk_tool_duration_seconds,
                    agent_invocations_total,
                    blog_generation_duration_seconds,
                    database_queries_total,
                    database_query_duration_seconds,
                    llm_call_duration_seconds,
                    llm_calls_total,
                    llm_tokens_total,
                    redis_command_duration_seconds,
                    redis_commands_total,
                )

                outcome = (
                    "failure"
                    if span.status.status_code == StatusCode.ERROR
                    else "success"
                )
                duration = max(0, span.end_time - span.start_time) / 1_000_000_000
                attributes = span.attributes or {}
                db_system = attributes.get("db.system") or attributes.get(
                    "db.system.name"
                )
                if db_system in {"postgresql", "postgres"}:
                    operation = _bounded_operation(
                        attributes.get("db.operation")
                        or attributes.get("db.operation.name")
                        or span.name
                    )
                    database_queries_total.labels(
                        operation=operation, outcome=outcome
                    ).inc()
                    database_query_duration_seconds.labels(
                        operation=operation
                    ).observe(duration)
                elif db_system == "redis":
                    command = _bounded_operation(
                        attributes.get("db.operation")
                        or attributes.get("db.operation.name")
                        or span.name
                    )
                    redis_commands_total.labels(
                        command=command, outcome=outcome
                    ).inc()
                    redis_command_duration_seconds.labels(command=command).observe(
                        duration
                    )

                if span.name.startswith("invoke_agent "):
                    agent_name = str(
                        span.attributes.get("gen_ai.agent.name")
                        or span.name.removeprefix("invoke_agent ")
                    )
                    agent_invocations_total.labels(
                        agent_name=agent_name,
                        success=str(outcome == "success").lower(),
                    ).inc()
                    stage = self._stage_by_agent.get(agent_name)
                    if stage:
                        blog_generation_duration_seconds.labels(stage=stage).observe(
                            duration
                        )
                elif span.name == "call_llm":
                    llm_calls_total.labels(outcome=outcome).inc()
                    llm_call_duration_seconds.observe(duration)
                    for attribute, kind in (
                        ("gen_ai.usage.input_tokens", "input"),
                        ("gen_ai.usage.output_tokens", "output"),
                    ):
                        value = attributes.get(attribute)
                        if isinstance(value, (int, float)) and value >= 0:
                            llm_tokens_total.labels(kind=kind).inc(value)
                elif span.name.startswith("execute_tool "):
                    tool_name = span.name.removeprefix("execute_tool ")
                    adk_tool_calls_total.labels(
                        tool_name=tool_name,
                        outcome=outcome,
                    ).inc()
                    adk_tool_duration_seconds.labels(tool_name=tool_name).observe(
                        duration
                    )
            except Exception:
                logger.debug("adk_prometheus_span_record_failed", exc_info=True)

        def shutdown(self) -> None:
            pass

        def force_flush(self, timeout_millis: int = 30000) -> bool:
            return True


def _bounded_operation(value: object) -> str:
    """Normalize driver operation names and never expose SQL/query text as labels."""
    operation = str(value).strip().split(maxsplit=1)[0].upper() if value else "OTHER"
    allowed = {
        "SELECT",
        "INSERT",
        "UPDATE",
        "DELETE",
        "CREATE",
        "ALTER",
        "DROP",
        "BEGIN",
        "COMMIT",
        "ROLLBACK",
        "SET",
        "GET",
        "MGET",
        "MSET",
        "DEL",
        "EXISTS",
        "EVAL",
        "EVALSHA",
        "SCRIPT",
        "SCAN",
        "EXPIRE",
        "ZRANGEBYSCORE",
        "CONNECT",
        "PUBLISH",
        "SUBSCRIBE",
        "ZADD",
        "ZREM",
        "ZRANGE",
        "ZCARD",
        "LPUSH",
        "RPOP",
        "LLEN",
        "OTHER",
    }
    return operation if operation in allowed else "OTHER"

def init_tracing(
    service_name: str | None = None,
    otlp_endpoint: str | None = None,
) -> None:
    """
    Initialize OpenTelemetry tracing.

    Args:
        service_name: Name of this service in traces
        otlp_endpoint: OTLP collector endpoint (default from env)
    """
    global _tracer, _provider_initialized

    if not OTEL_AVAILABLE:
        logger.warning("tracing_disabled", reason="opentelemetry not installed")
        return

    if _provider_initialized:
        return

    service_name = service_name or os.getenv("OTEL_SERVICE_NAME", "blogify-api")
    endpoint = otlp_endpoint or os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")

    # Create resource
    resource = Resource.create(
        {
            "service.name": service_name,
            "service.version": "1.0.0",
            "deployment.environment": os.getenv("ENVIRONMENT", "dev"),
        }
    )

    # Create tracer provider
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(PrometheusSpanProcessor())

    if endpoint:
        try:
            exporter = OTLPSpanExporter(endpoint=endpoint, insecure=True)
            provider.add_span_processor(BatchSpanProcessor(exporter))
            logger.info("otlp_exporter_configured", endpoint=endpoint)
        except Exception as e:
            logger.warning("otlp_exporter_failed", error=str(e))
    else:
        logger.info("otlp_exporter_disabled", reason="OTEL_EXPORTER_OTLP_ENDPOINT is not configured")

    # Set global provider
    trace.set_tracer_provider(provider)
    _provider_initialized = True

    # Get tracer
    _tracer = trace.get_tracer(__name__)

    logger.info("tracing_initialized", service_name=service_name)


def instrument_app(app) -> None:
    """
    Instrument FastAPI application with tracing.

    Args:
        app: FastAPI application instance
    """
    if not OTEL_AVAILABLE:
        return

    try:
        FastAPIInstrumentor.instrument_app(app, excluded_urls=r"/metrics,/api/health.*,/api/v1/health.*")
        logger.info("fastapi_instrumented")
    except Exception as e:
        logger.warning("fastapi_instrumentation_failed", error=str(e))

    instrument_clients()


def instrument_clients() -> None:
    """Instrument outbound HTTP and Redis clients once per process."""
    global _clients_instrumented
    if not OTEL_AVAILABLE or _clients_instrumented:
        return

    try:
        HTTPXClientInstrumentor().instrument()
        logger.info("httpx_instrumented")
    except Exception as e:
        logger.warning("httpx_instrumentation_failed", error=str(e))

    try:
        RedisInstrumentor().instrument()
        logger.info("redis_instrumented")
    except Exception as e:
        logger.warning("redis_instrumentation_failed", error=str(e))
    _clients_instrumented = True


def instrument_database(engine) -> None:
    """
    Instrument SQLAlchemy with tracing.

    Args:
        engine: SQLAlchemy engine
    """
    if not OTEL_AVAILABLE:
        return

    try:
        SQLAlchemyInstrumentor().instrument(engine=getattr(engine, "sync_engine", engine))
        logger.info("sqlalchemy_instrumented")
    except Exception as e:
        logger.warning("sqlalchemy_instrumentation_failed", error=str(e))


def get_tracer():
    """Get the global tracer instance."""
    global _tracer

    if _tracer is None:
        if OTEL_AVAILABLE:
            _tracer = trace.get_tracer(__name__)
        else:
            _tracer = NoOpTracer()

    return _tracer


def inject_trace_context() -> dict[str, str]:
    """Return W3C trace headers for persistence with asynchronous work."""
    if not OTEL_AVAILABLE:
        return {}
    carrier: dict[str, str] = {}
    from opentelemetry.propagate import inject

    inject(carrier)
    return carrier


def extract_trace_context(carrier: dict[str, str] | None):
    """Restore W3C trace context carried by an outbox event or queue job."""
    if not OTEL_AVAILABLE or not carrier:
        return None
    from opentelemetry.propagate import extract

    return extract(carrier)


def record_current_exception(exception: Exception) -> None:
    """Mark the active span failed when application code handles the exception."""
    if not OTEL_AVAILABLE:
        return
    span = trace.get_current_span()
    span.record_exception(exception)
    span.set_status(Status(StatusCode.ERROR, str(exception)))


class NoOpTracer:
    """No-op tracer when OpenTelemetry is not available."""

    @contextmanager
    def start_as_current_span(self, name: str, **kwargs):
        yield NoOpSpan()


class NoOpSpan:
    """No-op span."""

    def set_attribute(self, key: str, value: Any) -> None:
        pass

    def set_status(self, status: Any) -> None:
        pass

    def record_exception(self, exception: Exception) -> None:
        pass

    def add_event(self, name: str, attributes: dict | None = None) -> None:
        pass


@contextmanager
def trace_span(
    name: str,
    attributes: dict | None = None,
    *,
    context=None,
):
    """
    Create a traced span.

    Usage:
        with trace_span("llm_call", {"model": "gemini-1.5-pro"}) as span:
            response = call_llm()
            span.set_attribute("tokens", response.tokens)
    """
    tracer = get_tracer()

    with tracer.start_as_current_span(name, context=context) as span:
        if attributes:
            for key, value in attributes.items():
                span.set_attribute(key, value)

        try:
            yield span
        except Exception as e:
            span.record_exception(e)
            if OTEL_AVAILABLE:
                span.set_status(Status(StatusCode.ERROR, str(e)))
            raise


def trace_function(name: str | None = None, attributes: dict | None = None):
    """
    Decorator to trace a function.

    Usage:
        @trace_function("llm_intent_call")
        async def run_intent_stage(self, topic: str):
            ...
    """

    def decorator(func: Callable):
        span_name = name or func.__name__

        async def async_wrapper(*args, **kwargs):
            with trace_span(span_name, attributes):
                return await func(*args, **kwargs)

        def sync_wrapper(*args, **kwargs):
            with trace_span(span_name, attributes):
                return func(*args, **kwargs)

        import asyncio

        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper

    return decorator
