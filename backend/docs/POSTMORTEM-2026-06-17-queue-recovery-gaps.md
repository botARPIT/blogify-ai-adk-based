# Postmortem: Redis Processing Expiry and Orphaned `QUEUED` Sessions

## Summary

During review of the blog worker recovery flow, we identified that the system could permanently lose runnable work in two non-terminal cases:

- a worker dequeued a Redis job and died before DB lease acquisition
- Postgres held a `QUEUED` session while Redis no longer held any corresponding job

Neither case guaranteed a retry, and both could leave a session stuck indefinitely without being marked failed.

## Impact

The impact was operational rather than user-visible data corruption:

- a blog generation or revision could stop making progress
- the session could remain `QUEUED` forever
- no worker would pick it up
- no failure status would be written automatically

This meant the system could violate the expected invariant:

`QUEUED` must imply there is a path for some worker to eventually claim and execute the job.

## What Happened

### Failure mode 1: Redis dequeue without DB lease

The worker first moved a job from `blogify:tasks` into `blogify:processing`.

If the process crashed before `acquire_lease()` completed:

- Redis no longer had the job in the ready queue
- Postgres had no active lease to recover from
- the reaper later deleted the expired Redis processing entry instead of requeueing it

Result:

- the job disappeared from both the ready queue and lease recovery path

### Failure mode 2: `QUEUED` in DB, missing in Redis

Separate request paths could legitimately leave Postgres with runnable state while Redis had no queued or processing payload.

Examples include:

- enqueue failure after session state was already updated
- cleanup or loss of Redis payloads after queueing
- recovery bugs that removed transport state without re-creating runnable work

Result:

- Postgres still declared the session runnable
- Redis had no work for any worker to consume

## Root Cause

The root cause was an incomplete recovery model.

The system had:

- strong enough logic for stale DB leases
- weak logic for Redis visibility expiry
- no DB-to-Redis reconciliation for stranded `QUEUED` sessions

In effect, recovery assumed that any meaningful failure would eventually surface as a stale lease. That assumption was false for work that died before lease acquisition or lost its Redis payload after being marked runnable in Postgres.

## Contributing Factors

- Redis and Postgres do not share a transactional boundary
- worker ownership is established in two stages: queue claim first, DB lease second
- stale Redis processing cleanup was implemented as deletion, not retry
- no periodic check compared DB runnable state against Redis job presence

## Detection

This issue was found by codepath tracing and invariants review, not by an explicit automated alert.

The high-signal observation was:

- `QUEUED` in Postgres did not always imply any live or retryable Redis job existed

That led to review of:

- queue dequeue semantics
- Redis processing expiry handling
- stale lease recovery ordering
- session lifecycle transitions

## Resolution

We implemented two changes.

### 1. Smarter Redis processing expiry handling

Expired Redis processing entries are no longer deleted unconditionally.

They are now re-enqueued only when DB state shows the job is still queue-owned:

- session status is `QUEUED`
- no active lease exists
- the session was not already requeued by the stale-lease path

Otherwise the expired entry is treated as stale transport residue and cleaned up without creating a duplicate retry.

### 2. Periodic reconciliation for stranded `QUEUED` sessions

The reaper now periodically scans for aged `QUEUED` sessions that:

- have no active lease
- do not appear in the Redis ready queue
- do not appear in the Redis processing set

Those sessions are re-enqueued from persisted DB state.

## Why This Fix Was Chosen

A transactional outbox was considered, but it would primarily address producer-side enqueue durability.

The incident here also involved a consumer-side window:

- dequeue succeeded
- lease acquisition never happened

That required better Redis visibility recovery regardless of whether an outbox existed.

The implemented change was therefore the smallest design that closed the observed gaps while preserving the current worker/lease architecture.

## Preventive Actions

- Treat Redis transport expiry as recoverable work, not disposable residue, when DB state still indicates queue ownership
- Reconcile Postgres runnable state against Redis job presence on a schedule
- Continue using DB lease state as the authoritative signal for mid-flight worker recovery

## Remaining Risks

- Recovery semantics remain at-least-once rather than exactly-once
- Producer-side enqueue durability is still weaker than a full transactional outbox model
- Reaper correctness now depends on careful coordination between Redis transport state and DB lease state

## Follow-up

If future incidents show recurring producer-side enqueue loss or unacceptable operational complexity in reaper logic, the next step should be to evaluate:

- transactional outbox for enqueue requests
- dedicated dispatcher ownership for Redis publication
- tighter observability around stranded `QUEUED` sessions and reconcile counts
