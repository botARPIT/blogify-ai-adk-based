# Postmortem: Three Reapers Were Fighting Each Other

**Date:** 2026-05-08
**Severity:** P2 — Stale session leases being reaped multiple times, causing duplicate job queuing and inconsistent worker state
**Author:** Engineering
**Status:** Resolved

---

## What Happened

We ran three `blog_worker` replicas in production. When a stale lease needed to be reaped, all three reapers fired simultaneously. A lease expired once, got requeued three times, and three separate workers each picked up the "same" job.

The symptoms were subtle at first:
- Blog sessions showing intermediate state longer than expected
- Occasional double-generation artifacts appearing in the database
- Reaper logs from three distinct processes all claiming to have reaped the same `session_id`

This was a textbook race condition — not a crash, not a data corruption event, but a correctness violation that was quietly degrading reliability.

---

## Architecture at the Time

The `BlogWorker.run()` method looked something like this:

```python
class BlogWorker:
    def run(self):
        self.reaper = Reaper(...)
        asyncio.create_task(self.reaper.start())  # spawned inline
        # ... main job-consume loop
```

The reaper was a coroutine started inside the worker process. This meant every replica that came online spawned its own reaper. Three replicas = three reapers, all watching the same `session_leases` table, all scanning on the same interval.

The reaper's `reap()` method didn't have a distributed lock. It would:
1. `SELECT * FROM session_leases WHERE expires_at < NOW() AND status = 'active'`
2. Mark each lease as `expired`
3. Push the job back to the Redis queue

In a single-process world, this is fine. With three processes running the exact same logic on the same clock tick, step 1 returns the same rows to all three before any of them have committed step 2. Each process proceeds to reap and requeue the same expired leases. The result is triple-queuing.

---

## Timeline

- **Early production run** — System appeared to work. Only one worker replica active at the time.
- **After scaling to 3 replicas** — Intermittent double-generation reports. Two completed blogs appearing for one session.
- **Investigation begins** — Grep of reaper logs reveals three separate PIDs claiming the same `session_id`.
- **Root cause confirmed** — Reaper instantiation is inside `BlogWorker.run()`. Three workers = three reapers.
- **Fix implemented** — Reaper extracted into standalone process. Worker replicas no longer spawn reapers.
- **Verified** — Only one reaper process running. Reaper logs show single-process ownership.

---

## Why This Was Hard to Notice Initially

In a single-worker dev environment, nothing is wrong. The reaper fires, reaps, and the single worker picks up the requeued job. It looks correct.

The issue only surfaces when you scale horizontally, which happened in production. At that point, the embedded reaper pattern turns into a distributed fan-out problem nobody designed for.

We didn't have an explicit invariant that "only one reaper should run at any time." It was an implicit assumption that broke when the deployment model changed.

---

## Options We Considered

### Option A: Distributed Lease on the Reaper Itself
Use Redis `SET NX EX` to elect a single reaper among replicas. One worker wins the lock, others skip their reaper task. Rotate on lock expiry.

This keeps the reaper embedded in the worker but adds a coordination layer. The problem: the lock itself has failure modes — if the lock-holder crashes mid-reap, nobody knows for how long to wait before another worker takes over.

### Option B: Database-Side Idempotency on Reap Operations
Use `UPDATE ... WHERE status = 'active' AND expires_at < NOW() RETURNING id` to atomically claim stale leases before reaping them. Only the process that successfully updates a row gets to requeue it.

This works but requires each worker to handle the reap logic, which still means multiple processes running reaper logic simultaneously. It's more correct but more complex to reason about.

### Option C: Standalone Reaper Process (What We Did)
Extract the reaper into its own module with a `__main__` entrypoint. Run it as a separate container/process managed by `docker-compose`. One reaper, full stop. Workers are workers. Reapers are reapers.

```yaml
# docker-compose.yml
reaper:
  build: ./backend
  command: python -m src.workers.reaper
  environment:
    - DATABASE_URL=${DATABASE_URL}
    - REDIS_URL=${REDIS_URL}
  depends_on:
    - postgres
    - redis
  restart: unless-stopped
```

Single Responsibility Principle at the infrastructure level.

---

## Why We Chose Option C

Options A and B fix the race condition but leave the conceptual problem intact: reaper logic living inside worker processes. If we later scale workers to 10 replicas, we'd be back to managing distributed reaper election across 10 processes.

Option C is the simplest thing that can't have this class of bug. One process, one responsibility. Adding more worker replicas has zero effect on reaper behavior. The reaper process itself can be scaled independently if needed (with Option B's atomic-claim approach added at that point).

The implementation was also straightforward — the reaper module was already a class. Adding `if __name__ == "__main__"` and removing the instantiation from `BlogWorker.run()` was the core of the change.

---

## Fix

**`src/workers/reaper.py`** — Added standalone entrypoint:

```python
if __name__ == "__main__":
    import asyncio
    reaper = Reaper(...)
    asyncio.run(reaper.start())
```

**`src/workers/blog_worker.py`** — Removed embedded reaper:

```python
# Deleted:
# self.reaper = Reaper(...)
# asyncio.create_task(self.reaper.start())
```

**`docker-compose.yml`** — Added `reaper` service.

The worker process is now a pure job consumer. The reaper is a separate, independently-managed daemon.

---

## Lessons

**Horizontal scaling changes the blast radius of embedded background tasks.** A design that's correct with N=1 can silently break at N=3. Before embedding any background task inside a service that will be replicated, ask: what happens if two copies of this run simultaneously?

**SRP at the process level, not just the class level.** We had a `Reaper` class. We thought that was separation of concerns. It wasn't — the class was still instantiated by the worker. The responsibility boundary should be the process boundary.

**Infrastructure-level enforcement is more reliable than application-level coordination.** Running one reaper via `docker-compose` is a stronger guarantee than any distributed election scheme. The deployment topology becomes the invariant.
