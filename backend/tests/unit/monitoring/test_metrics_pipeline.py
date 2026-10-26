"""Verify emitted OTel spans actually update the metrics Prometheus scrapes."""

from unittest.mock import AsyncMock

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.trace import Status, StatusCode

from src.monitoring import metrics
from src.monitoring.tracing import PrometheusSpanProcessor, _bounded_operation


def test_adk_model_span_records_outcome_tokens_and_duration():
    calls = metrics.llm_calls_total.labels(outcome="failure")
    tokens = metrics.llm_tokens_total.labels(kind="input")
    calls_before, tokens_before = calls._value.get(), tokens._value.get()
    provider = TracerProvider()
    provider.add_span_processor(PrometheusSpanProcessor())
    try:
        with provider.get_tracer(__name__).start_as_current_span("call_llm") as span:
            span.set_attribute("gen_ai.usage.input_tokens", 123)
            span.set_status(Status(StatusCode.ERROR))
        assert calls._value.get() == calls_before + 1
        assert tokens._value.get() == tokens_before + 123
    finally:
        provider.shutdown()


def test_agent_span_counts_completed_stage():
    counter = metrics.agent_invocations_total.labels(agent_name="writer_agent", success="true")
    before = counter._value.get()
    provider = TracerProvider()
    provider.add_span_processor(PrometheusSpanProcessor())
    try:
        with provider.get_tracer(__name__).start_as_current_span("invoke_agent writer_agent"):
            pass
        assert counter._value.get() == before + 1
    finally:
        provider.shutdown()


@pytest.mark.parametrize("operation,expected", [
    ("SELECT private_text FROM users", "SELECT"),
    ("EVALSHA", "EVALSHA"),
    ("unknown sensitive data", "OTHER"),
    ("", "OTHER"),
])
def test_client_metric_labels_do_not_include_query_text(operation, expected):
    assert _bounded_operation(operation) == expected


@pytest.mark.asyncio
async def test_database_outage_does_not_stop_queue_snapshot(monkeypatch):
    from src.monitoring import runtime_metrics

    monkeypatch.setattr(runtime_metrics, "update_database_pool_metrics", lambda _name: None)
    monkeypatch.setattr(runtime_metrics, "_refresh_postgres_state", AsyncMock(side_effect=OSError))
    refresh_redis = AsyncMock()
    monkeypatch.setattr(runtime_metrics, "_refresh_redis_state", refresh_redis)

    assert await runtime_metrics.refresh_runtime_metrics("api", include_shared_state=True) is False
    refresh_redis.assert_awaited_once()
