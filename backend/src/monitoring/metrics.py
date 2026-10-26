"""Prometheus metrics instrumentation."""

import hmac

from fastapi import HTTPException, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest

from src.config.env_config import config
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
http_requests_in_progress = Gauge(
    "http_requests_in_progress",
    "HTTP requests currently being handled",
    ["method"],
)

# Request rate-limit metrics
rate_limit_rejections_total = Counter(
    "rate_limit_rejections_total", "Rejected requests by rate-limit scope", ["limit_type"]
)

# Workflow metrics
blog_generation_duration_seconds = Histogram(
    "blog_generation_duration_seconds",
    "Blog generation duration",
    ["stage"],  # intent, outline, research, writer, editor
    buckets=(1, 2.5, 5, 10, 20, 30, 60, 120, 300, 600),
)

# Durable workflow state is refreshed from PostgreSQL by the API poller. These
# gauges are current counts, so they survive API and worker restarts.
blog_sessions_by_status = Gauge(
    "blog_sessions_by_status",
    "Persisted blog sessions by lifecycle status",
    ["status"],
)
workflow_outbox_events_by_status = Gauge(
    "workflow_outbox_events_by_status",
    "Persisted workflow outbox events by status",
    ["status"],
)
workflow_outbox_oldest_pending_seconds = Gauge(
    "workflow_outbox_oldest_pending_seconds",
    "Age of the oldest dispatchable pending outbox event",
)

# Redis queue and worker metrics.
redis_queue_items = Gauge(
    "redis_queue_items",
    "Number of jobs in a Redis queue structure",
    ["queue"],  # ready, processing
)
redis_queue_capacity = Gauge(
    "redis_queue_capacity", "Maximum number of ready jobs accepted by Redis queue"
)
queue_enqueue_failures_total = Counter(
    "queue_enqueue_failures_total",
    "Redis job enqueue failures",
    ["reason"],  # full, redis_error, notify_error
)
queue_wait_failures_total = Counter(
    "queue_wait_failures_total",
    "Redis worker dequeue or wait failures",
)
workers_active = Gauge("workers_active", "Workers with a live Redis heartbeat")
workers_active_jobs = Gauge("workers_active_jobs", "Active jobs reported by worker heartbeats")
workers_capacity = Gauge("workers_capacity", "Total job capacity reported by live workers")
worker_jobs_in_progress = Gauge(
    "worker_jobs_in_progress",
    "Workflow jobs currently executing in this worker process",
    ["phase"],
)
worker_capacity = Gauge(
    "worker_capacity",
    "Maximum concurrent workflow jobs for this worker process",
)
worker_jobs_total = Counter(
    "worker_jobs_total",
    "Workflow job attempts by phase and result",
    ["phase", "outcome"],  # succeeded, failed, retried, stale
)
worker_job_duration_seconds = Histogram(
    "worker_job_duration_seconds",
    "Time spent processing one workflow job attempt",
    ["phase"],
    buckets=(1, 5, 10, 30, 60, 120, 300, 600, 1200, 1800),
)

# Database server and SQLAlchemy pool snapshots.
database_connections = Gauge(
    "database_connections",
    "PostgreSQL connections by server-reported state",
    ["state"],
)
database_max_connections = Gauge(
    "database_max_connections", "PostgreSQL max_connections setting"
)
database_size_bytes = Gauge(
    "database_size_bytes", "Size of the Blogify PostgreSQL database in bytes"
)
database_transactions = Gauge(
    "database_transactions",
    "PostgreSQL transaction counters since statistics reset",
    ["outcome"],  # committed, rolled_back
)
database_deadlocks = Gauge(
    "database_deadlocks", "PostgreSQL deadlock count since statistics reset"
)
database_pool_connections = Gauge(
    "database_pool_connections",
    "SQLAlchemy async connection pool snapshot",
    ["process", "state"],  # size, checked_out, overflow
)
runtime_metrics_refresh_success_timestamp_seconds = Gauge(
    "runtime_metrics_refresh_success_timestamp_seconds",
    "Unix timestamp of the last successful runtime metrics refresh",
    ["process"],
)
runtime_metrics_refresh_errors_total = Counter(
    "runtime_metrics_refresh_errors_total",
    "Failed runtime metrics refresh attempts",
    ["process"],
)
database_queries_total = Counter(
    "database_queries_total",
    "PostgreSQL client spans by operation and result",
    ["operation", "outcome"],
)
database_query_duration_seconds = Histogram(
    "database_query_duration_seconds",
    "Duration of a PostgreSQL client span",
    ["operation"],
)
redis_commands_total = Counter(
    "redis_commands_total",
    "Redis command spans by command and result",
    ["command", "outcome"],
)
redis_command_duration_seconds = Histogram(
    "redis_command_duration_seconds",
    "Duration of a Redis command span",
    ["command"],
)

# ADK spans are translated to Prometheus counters and histograms by the OTel
# span processor. Usage and cost values are recorded from workflow results.
llm_calls_total = Counter(
    "llm_calls_total", "ADK model call spans by result", ["outcome"]
)
llm_tokens_total = Counter(
    "llm_tokens_total", "Tokens reported by ADK model spans", ["kind"]
)
llm_call_duration_seconds = Histogram(
    "llm_call_duration_seconds", "Duration of an ADK model call span",
    buckets=(0.1, 0.5, 1, 2.5, 5, 10, 30, 60, 120, 300),
)
adk_tool_calls_total = Counter(
    "adk_tool_calls_total",
    "ADK tool execution spans by tool and result",
    ["tool_name", "outcome"],
)
adk_tool_duration_seconds = Histogram(
    "adk_tool_duration_seconds", "Duration of an ADK tool execution span", ["tool_name"]
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
    buckets=(100, 500, 1000, 2500, 5000, 10000, 25000, 50000, 100000),
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

# Judge metrics
judge_decisions_total = Counter(
    "judge_decisions_total",
    "Total judge decisions",
    ["decision"],  # approved, rejected
)

async def metrics_endpoint(request: Request):
    """Prometheus metrics endpoint."""
    if not config.metrics_public:
        expected = config.metrics_bearer_token
        supplied = request.headers.get("Authorization", "")
        scheme, _, supplied_token = supplied.partition(" ")
        if (
            scheme.lower() != "bearer"
            or not expected
            or not hmac.compare_digest(supplied_token, expected)
        ):
            raise HTTPException(status_code=404, detail="Not found")
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
