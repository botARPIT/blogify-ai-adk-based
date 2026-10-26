# Blogify SLI, SLO, and Stress-Test Plan

## Scope and status

See the [system, workflow, and schema diagrams](../../architecture/README.md).

This is a proposed first service-level baseline for the current Blogify architecture: FastAPI accepts generation and review requests, PostgreSQL is the durable workflow store, Redis carries jobs and wake-up notifications, workers claim outbox/session leases and execute the ADK pipeline, and external LLM/research providers contribute variable latency.

The targets below are **initial objectives, not measured results**. No production-like benchmark has been run from this checkout. API and end-to-end generation measurements still require a representative staging run and the actual traffic mix.

## SLIs and initial SLOs

Use rolling 28-day windows for availability and latency. Report generation latency separately from human review waiting time and external-provider timeouts so user waiting is not hidden inside an ambiguous average.

| SLI | Definition | Initial SLO | Measurement status |
|---|---|---:|---|
| API availability | Non-health API requests with a server 5xx or timeout are bad events. Exclude caller 4xx, health probes, and `/metrics`. | ≥99.5% good requests per 28 days | Request counters/histogram are declared in `src/monitoring/metrics.py`; request middleware wiring and endpoint exclusion need verification. |
| Read API latency | Successful authenticated reads (list, detail, status, budget) completed within threshold. | p95 ≤400 ms; p99 ≤1 s | Needs stable route labels and histograms; do not label by user/session ID. |
| Generate acknowledgement | `POST /blogs/generate` accepted and durable session/outbox transaction committed before 202 response. | p95 ≤1 s; p99 ≤2 s | Must measure from request start through commit/response. |
| Queue delay | Time from accepted job creation to worker start, excluding time spent awaiting human review. | p95 ≤30 s; p99 ≤2 min under the agreed normal load | New timestamp/metric needed; do not infer from HTTP latency. |
| Workflow completion | Time from accepted request to first human-review checkpoint or terminal outcome; pause the clock while status is `AWAITING_*_REVIEW`. | p95 ≤5 min for supported, non-provider-degraded workload | New stage timestamps/events needed; set a workload-specific target after the first real benchmark. |
| Durable dispatch | Accepted jobs whose PostgreSQL outbox event is eventually processed or explicitly terminal-failed. | 100% accounted for; zero silently lost events | Validate with outbox reconciliation and failure injection. Redis is transport, not authority. |
| Duplicate effects | Duplicate accepted requests or redeliveries that create a second active generation/effect for the same idempotency key. | Zero duplicates in the test window | Test idempotency and at-least-once dispatch. Exactly-once delivery is not assumed. |
| Worker recovery | Eligible jobs recovered after worker loss/expired lease. | p95 recovery ≤5 min | Requires crash/reaper test and recovery metric. |
| Exhausted workflow failures | Operational workflow attempts ending in `FAILED`, excluding invalid input, user rejection/cancellation, and classified provider outages. | ≤1% per 28 days | Define error taxonomy before alerting; existing status metrics do not fully provide this numerator. |

The 99.5% API objective corresponds to roughly 3.6 hours of error budget in a 30-day month. A 99.9% objective is a later option once availability is measured and operational response is staffed.

## Required instrumentation

Existing metric declarations include `http_requests_total`, `http_request_duration_seconds`, `blog_generations_total`, and agent latency/cost metrics. The code should be checked for actual increments/observations before these are used as SLIs. Add or wire the following bounded-cardinality measurements before treating the queue/workflow SLOs as operational:

- `workflow_jobs_accepted_total{result}`
- `workflow_queue_wait_seconds` histogram by fixed phase
- `workflow_job_execution_seconds` histogram by fixed phase and outcome
- `workflow_outbox_oldest_pending_seconds` gauge
- `workflow_outbox_events{status}` gauge and `workflow_outbox_attempts_total{result}` counter
- `workflow_worker_active_jobs` gauge and `workflow_worker_lease_expirations_total` counter
- `workflow_recovery_seconds` histogram

Use only finite labels such as `phase`, `result`, and `status`. Never add `user_id`, `session_id`, raw error text, topic, or provider request IDs as metric labels. Capture generation and provider failures in structured logs/traces with correlation IDs instead.

## Test strategy

### Correctness gates

Run the existing unit suite plus focused tests for:

1. Outbox claim ownership, lease expiry, heartbeat, completion, retry delay, max-attempt terminal failure, and dispatch marking.
2. Idempotency under concurrent duplicate requests and the transaction invariant: session state and outbox intent commit together or neither persists.
3. Redis delivery duplication, delayed delivery, and broker outage followed by outbox republish.
4. Two workers racing for one outbox event/session lease; only one may execute the pipeline at a time.
5. Worker crash after claim, crash after side effect but before acknowledgement, lease recovery, and retry exhaustion.
6. Invalid and malformed outbox payloads, terminal sessions, stale reviews, and user/session ownership boundaries.
7. Budget reserve/commit/release consistency under concurrent generation attempts.

Unit mocks prove state-machine behavior, not PostgreSQL locking or transaction isolation. `tests/integration/test_workflow_outbox_postgres.py` adds isolated-schema transaction and `FOR UPDATE SKIP LOCKED` checks; run it only against a disposable database by setting `BLOGIFY_TEST_DATABASE_URL`. Crash/recovery and Redis-outage end-to-end cases still require a deployed integration topology.

### Load profiles

Use the same build, schema, worker count, CPU/memory limits, and dependency versions as the candidate deployment. Run a warm-up before recording percentiles.

| Profile | Workload | Duration | Purpose |
|---|---|---:|---|
| Smoke | 1–5 concurrent read clients; 1 synthetic queued job/s | 10 min | Confirm endpoints, metrics, and queue path. |
| Baseline | 10 concurrent reads; 1 generation job/s with deterministic stub provider | 30 min | Establish steady-state latency and saturation. |
| Ramp | Increase 5 → 10 → 25 → 50 concurrent clients in 10-minute steps; hold each step | 50 min | Find the first SLO/resource saturation point. |
| Burst | 5× measured baseline arrival rate for 2 min, then return to baseline | 15 min | Verify queue buffering and recovery. |
| Soak | Measured baseline rate and normal provider mix | 8–24 hr | Detect leaks, growing queue age, and retry storms. |
| Dependency failure | Inject Redis, PostgreSQL, and provider failures separately | 15 min each | Verify bounded retries, durable intent, and recovery. |

Use a deterministic stub provider for repeatable capacity tests. Run a separate small staging canary with real providers only after setting an explicit token/cost cap. Never use this stress suite to send uncontrolled paid LLM requests.

## Benchmark procedure and acceptance

1. Apply migrations to a disposable or staging database; record revision and schema size.
2. Record API/worker replica counts, worker concurrency, DB pool size, Redis version, CPU/memory limits, and provider mode.
3. Run correctness tests first; then run the API and Redis benchmark scripts linked below.
4. Capture request p50/p95/p99, error rate, accepted-job rate, queue-wait p95/p99, completion p95, retry count, oldest outbox age, DB pool wait, Redis latency, provider latency, CPU/memory, and cost per completed job.
5. A load point passes only when all SLOs hold, queue depth returns to its pre-burst level, no accepted event is unaccounted for, and no resource is continuously saturated.
6. Report the highest passing arrival rate and the first failing rate. Do not extrapolate a larger RPS claim from worker count or architecture alone.

## Running the harnesses

The API benchmark is a safe, read-only HTTP harness. Point it at `/api/v1/health` or an authenticated read route; it supports optional JSON headers through `BLOGIFY_BENCH_HEADERS`.

```bash
cd backend
python scripts/benchmark_api.py --base-url http://127.0.0.1:8000 --path /api/v1/health --requests 1000 --concurrency 20
```

The Redis queue stress test uses unique keys and only synthetic jobs. It is deliberately opt-in and does not call an LLM:

```bash
cd backend
BLOGIFY_RUN_REDIS_STRESS=1 BLOGIFY_STRESS_MESSAGES=5000 pytest -q -s tests/performance/load/test_queue_load.py
```

The stress test requires a dedicated reachable Redis instance. It deletes only the unique queue and processing keys it created. Do not point it at production.

## Current limits

- Generation measurements require the API, worker, PostgreSQL, Redis, and provider dependencies to be running together.
- The existing files under `tests/performance/load/` were empty when inspected. This plan adds only an opt-in Redis transport stress test; it does not claim end-to-end worker throughput.
- No staging topology, production request distribution, provider quota, or cost ceiling was supplied, so the targets and concurrency profile are provisional.
- The DB schema diagram is an ORM view. Confirm migrations and the live database schema before production changes, especially the version/session cycle and outbox aggregate relationship.

## Local development measurements (2026-10-13)

These are bounded local checks, not production or deployment SLO evidence:

- `GET http://127.0.0.1:8000/api/v1/health`: 1,000 measured requests at concurrency 20 after 50 warm-up requests; 0 failures; p50 30.17 ms, p95 104.08 ms, p99 140.57 ms. The listener's build identity was not established, and this health endpoint does not exercise database-backed reads or generation.
- Redis queue transport: 5,000 synthetic jobs against local standalone Redis 7.4.8; 32 producer/consumer workers; 5,000 unique jobs acknowledged with no loss or duplicate; enqueue p95 10.53 ms; dequeue-plus-ack p95 14.04 ms; end-to-end throughput 1,532.10 jobs/s. This isolates the Redis transport and excludes PostgreSQL, outbox relay, session leasing, worker pipeline, and external providers.

The API result and Redis result cannot be combined into a whole-system capacity claim. Repeat on a deployment-equivalent topology with DB/outbox/worker instrumentation before revising the initial SLOs.
