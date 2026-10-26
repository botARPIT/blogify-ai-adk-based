# Blog generation profiling

Agent timings are collected inside the worker and persisted to
`agent_runs.latency_ms`. Each value covers the complete agent callback interval,
including model requests and tools called by that agent. The timing callbacks
are diagnostic only: Redis timing-marker failures do not fail a generation.

After a generation finishes, report its wall time, queue wait, worker lease
time, individual agent durations, and the slowest measured stage:

```bash
cd backend
.venv/bin/python scripts/profile_generation.py --session-ids 101
```

Pass several comparable session IDs to get mean, p50, p95, and maximum values
for the same measurements. Save the full report for later comparison with
`--json-out`, for example:

```bash
.venv/bin/python scripts/profile_generation.py \
  --session-ids 101 102 103 \
  --json-out docs/performance/results/generation-baseline.json
```

Wall time runs from session creation to completion and can include human review
pauses. Queue wait measures session creation to the first worker lease. Worker
lease time sums all worker leases. `outside_worker_time_ms` is elapsed time not
accounted for by those two measurements; it can include review pauses, retries
between leases, and dispatch delays. Agent durations help identify which
workflow component consumes worker time.

Compare runs with the same model/provider, topic complexity, audience, and
review path. Treat missing stage timings as unprofiled data: workers must load
the timing-enabled code before processing the job. Existing agent-run records
cannot be backfilled with per-agent durations after the fact.
