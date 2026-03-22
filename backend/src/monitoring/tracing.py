"""Distributed tracing with OpenTelemetry.

Provides request tracing across services and LLM calls.
"""

import os
from contextlib import contextmanager
from typing import Any, Callable

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
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    from opentelemetry.trace import Status, StatusCode
    
    OTEL_AVAILABLE = True
except ImportError:
    OTEL_AVAILABLE = False
    logger.warning("opentelemetry_not_installed", message="Install opentelemetry packages for tracing")


# Global tracer
_tracer = None


def init_tracing(
    service_name: str = "blogify-api",
    otlp_endpoint: str | None = None,
) -> None:
    """
    Initialize OpenTelemetry tracing.
    
    Args:
        service_name: Name of this service in traces
        otlp_endpoint: OTLP collector endpoint (default from env)
    """
    global _tracer
    
    if not OTEL_AVAILABLE:
        logger.warning("tracing_disabled", reason="opentelemetry not installed")
        return
    
    endpoint = otlp_endpoint or os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317")
    
    # Create resource
    resource = Resource.create({
        "service.name": service_name,
        "service.version": "1.0.0",
        "deployment.environment": os.getenv("ENVIRONMENT", "dev"),
    })
    
    # Create tracer provider
    provider = TracerProvider(resource=resource)
    
    # Add OTLP exporter
    try:
        exporter = OTLPSpanExporter(endpoint=endpoint, insecure=True)
        processor = BatchSpanProcessor(exporter)
        provider.add_span_processor(processor)
        logger.info("otlp_exporter_configured", endpoint=endpoint)
    except Exception as e:
        logger.warning("otlp_exporter_failed", error=str(e))
    
    # Set global provider
    trace.set_tracer_provider(provider)
    
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
        FastAPIInstrumentor.instrument_app(app)
        logger.info("fastapi_instrumented")
    except Exception as e:
        logger.warning("fastapi_instrumentation_failed", error=str(e))
    
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


def instrument_database(engine) -> None:
    """
    Instrument SQLAlchemy with tracing.
    
    Args:
        engine: SQLAlchemy engine
    """
    if not OTEL_AVAILABLE:
        return
    
    try:
        SQLAlchemyInstrumentor().instrument(engine=engine)
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
):
    """
    Create a traced span.
    
    Usage:
        with trace_span("llm_call", {"model": "gemini-1.5-pro"}) as span:
            response = call_llm()
            span.set_attribute("tokens", response.tokens)
    """
    tracer = get_tracer()
    
    with tracer.start_as_current_span(name) as span:
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
