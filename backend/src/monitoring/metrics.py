"""Prometheus metrics instrumentation."""

from prometheus_client import Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST
from fastapi import Response

from src.config.logging_config import get_logger

logger = get_logger(__name__)

# Request metrics
http_requests_total = Counter(
    "http_requests_total",
    "Total HTTP requests",
    ["method", "endpoint", "status_code"],
)

http_request_duration_seconds = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency",
    ["method", "endpoint"],
)

# Blog generation metrics
blog_generations_total = Counter(
    "blog_generations_total",
    "Total blog generation attempts",
    ["status"],  # initiated, completed, failed
)

blog_generation_duration_seconds = Histogram(
    "blog_generation_duration_seconds",
    "Blog generation duration",
    ["stage"],  # intent, outline, research, writing, judge
)

# Agent metrics
agent_invocations_total = Counter(
    "agent_invocations_total",
    "Total agent invocations",
    ["agent_name", "success"],
)

agent_token_usage = Histogram(
    "agent_token_usage",
    "Tokens used by agent",
    ["agent_name"],
)

agent_cost_usd = Histogram(
    "agent_cost_usd",
    "Cost per agent invocation",
    ["agent_name"],
)

# Validation metrics
validation_failures_total = Counter(
    "validation_failures_total",
    "Total validation failures",
    ["agent_name", "validation_type"],  # semantic, business_rule, quality
)

# Rate limit metrics
rate_limit_rejections_total = Counter(
    "rate_limit_rejections_total",
    "Total rate limit rejections",
    ["limit_type"],  # global_request, user_request, global_blog, user_blog
)

# Circuit breaker metrics
circuit_breaker_state = Gauge(
    "circuit_breaker_state",
    "Circuit breaker state (0=closed, 1=open, 2=half_open)",
    ["circuit_name"],
)

circuit_breaker_failures_total = Counter(
    "circuit_breaker_failures_total",
    "Total circuit breaker failures",
    ["circuit_name"],
)

# Budget metrics
budget_exceeded_total = Counter(
    "budget_exceeded_total",
    "Total budget exceeded events",
    ["budget_type"],  # global, per_blog, per_user
)

daily_cost_usd = Gauge(
    "daily_cost_usd",
    "Total cost today",
    ["scope"],  # global, user
)

# Judge metrics
judge_decisions_total = Counter(
    "judge_decisions_total",
    "Total judge decisions",
    ["decision"],  # approved, rejected
)

judge_quality_score = Histogram(
    "judge_quality_score",
    "Quality scores from judge",
)


async def metrics_endpoint():
    """Prometheus metrics endpoint."""
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
