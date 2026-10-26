# Observability

Blogify emits structured JSON logs to stdout, Prometheus metrics from
`/metrics`, and OpenTelemetry traces from the API, worker, and reaper.

The production Compose stack runs Prometheus, Grafana, Tempo, and an
OpenTelemetry Collector on the private backend network. Application logs stay
on stdout and should be collected by the host or managed deployment platform.
No separate host log-shipping container is required by this project.

## Local Compose

From the repository root:

```bash
docker compose -f backend/docker-compose.yml up -d
```

The local stack includes Prometheus and Grafana. Open Prometheus at
`http://localhost:9090` and Grafana at `http://localhost:3001` (default local
credentials: `admin` / `admin`; set `GRAFANA_USER` and `GRAFANA_PASSWORD` to
override). Grafana provisions the **API Golden Signals** dashboard from
`grafana/provisioning/dashboards/golden-signals.json`.

The dashboard covers API request rate (traffic), p95 latency, 4xx/5xx request
rate (errors), in-flight requests, and process CPU/memory (saturation). These
are API process metrics; worker concurrency and job outcomes appear in the
Backend Runtime and Generation dashboard. Production Compose keeps Prometheus
and Grafana private to the backend network, as described in its SSH-tunnel
instructions.

## Backend and generation metrics

The API `/metrics` endpoint also publishes 15-second snapshots from PostgreSQL
and Redis: persisted blog-session counts by status, outbox counts and oldest
pending age, ready/processing queue depth, live worker heartbeats, PostgreSQL
connection/transaction/database-size statistics, and the API SQLAlchemy pool.
These status gauges are database-backed, so counts such as `FAILED`,
`COMPLETED`, `AWAITING_OUTLINE_REVIEW`, and `AWAITING_FINAL_REVIEW` survive
process restarts.

Workers expose their process-local metrics on port `9101` inside the Compose
network; the reaper exposes port `9102`. Prometheus discovers worker replicas
through Docker DNS. Worker metrics include job attempts, outcomes, duration,
and concurrency. ADK invocation, model-call, and tool spans are translated into
Prometheus counters and histograms; token and estimated cost histograms come
from the workflow usage records. These internal ports are not published to the
host. The **Backend Runtime and Generation** Grafana dashboard combines them.


## Verify the running stack

From the repository root, with Grafana credentials exported:

```bash
export GRAFANA_USER=admin
# Set GRAFANA_PASSWORD to the password configured for this stack.
python3 backend/scripts/check-observability.py --wait 60
```

This checks every API/worker/reaper scrape target, snapshot freshness, Grafana's
Prometheus and Tempo datasource paths, provisioned dashboards, and every PromQL
query. Use `--workers 3` after scaling workers to three replicas. Query validation
allows empty results for idle model/tool/job counters; generate a blog to populate
them. The API refreshes database and Redis snapshots every 15 seconds.

`blog_sessions_by_status{status="COMPLETED"}` is the current number of final,
human-approved sessions; `FAILED` is the current terminal failure count. Review
backlogs use `AWAITING_OUTLINE_REVIEW` and `AWAITING_FINAL_REVIEW`. These are gauges,
not event counters: deleting sessions changes the count, and they do not measure
historical completion throughput. `worker_jobs_total{outcome="succeeded"}` counts
persisted phase attempts, including phases that pause for human review. Those
worker counters reset when their process restarts.

Prometheus reads the API bearer token from a private runtime file created by
`monitoring/start-prometheus.sh`; the Prometheus image does not support
`--config.expand-env`. Scrapes without the correct token return 404 in production.
Worker metrics stay on private container ports. Each app process currently uses
one Python worker so its registry represents that process; configure Prometheus
multiprocess collection before introducing multiple Uvicorn processes per container.

Use Grafana Explore with the Tempo datasource for traces. The API request, persisted
outbox context, worker attempt, workflow segment and ADK spans carry trace context.
Model and tool spans also feed Prometheus; no OTLP endpoint is required for the
local span-to-metric processor, but exported traces require the Collector and Tempo.

For local access to production metrics through SSH, follow the
[Azure VM runbook](../runbooks/azure-vm.md#view-production-metrics-on-your-local-machine).


Request rate limiting uses the upstream Redis sliding-window limiter. Public
health, metrics and documentation endpoints bypass it. Rejections increment
`rate_limit_rejections_total{limit_type="per_user_request"}` or
`rate_limit_rejections_total{limit_type="service_global"}`. Per-user admission
limits default to 120 requests/minute, allowing the UI's status polling; global
admission defaults to 600 requests/minute. Configure these through
`RATE_LIMIT_REQUESTS_PER_MINUTE` and `SERVICE_RATE_LIMIT_REQUESTS_PER_MINUTE`.
These limits are protective thresholds and do not establish measured capacity.
Daily generation quotas continue to use the transactional PostgreSQL quota.
