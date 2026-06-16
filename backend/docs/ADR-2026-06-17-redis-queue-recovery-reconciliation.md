# ADR-2026-06-17: Redis Queue Recovery and Queued Session Reconciliation

## Status

Accepted and implemented on 2026-06-17.

## Purpose

This ADR documents the recovery changes added to close two queue-consistency gaps in the blog worker system:

- Redis processing entries expiring without being re-enqueued
- `QUEUED` sessions in Postgres becoming orphaned when no Redis job exists

This document focuses on:

- which failure windows were left open by the previous design
- why lease-based recovery alone was not enough
- why the chosen fix uses layered recovery instead of a full outbox redesign
- what invariants now define queue ownership and requeue behavior

## Context

Before this change, recovery was split unevenly across Redis and Postgres:

- Redis queue transport used a visibility-timeout model through `blogify:processing`
- Postgres tracked session lifecycle and worker leases
- stale DB leases were recovered by the reaper
- stale Redis processing entries were only cleaned up, not re-enqueued

That left two concrete gaps.

### Gap 1: dequeue succeeded, lease acquisition never happened

The worker dequeues a Redis job before it creates a DB lease.

If the worker dies in that window:

- the job has already left `blogify:tasks`
- there is no `session_leases` row for stale-lease recovery to find
- the session still looks `QUEUED` in Postgres
- the expired Redis processing entry was previously deleted rather than retried

This was a true job-loss path.

### Gap 2: Postgres says `QUEUED`, Redis has no job

The API and review flows mutate Postgres state and enqueue Redis work separately.

If Redis enqueue fails, is lost, or is manually cleaned up later, Postgres can still contain a valid runnable session while Redis contains no corresponding queued or processing payload.

That leaves:

- no active lease
- no worker execution
- no terminal failure
- no automatic recovery

## Decision

We chose a layered recovery model instead of introducing a transactional outbox in this change.

### 1. Redis processing expiry must requeue orphaned transport claims

Expired Redis processing entries should no longer be deleted unconditionally.

Instead:

- if the entry represents a session that is still `QUEUED`
- and there is no active DB lease
- and the session was not already requeued by stale-lease recovery

then the Redis payload is moved back to `blogify:tasks`.

This specifically recovers the "dequeued but never leased" window.

### 2. Lease-based recovery remains the source of truth for in-flight DB-owned work

If DB state shows that a worker lease existed or that reaper-driven recovery has already taken ownership, Redis transport cleanup must not independently create another retry.

That means stale Redis processing entries are only re-enqueued for sessions that still look queue-owned in Postgres.

For sessions already handled by lease recovery:

- the Redis processing entry is treated as stale transport residue
- the entry is removed but not requeued again

### 3. Add DB-to-Redis reconciliation for stranded `QUEUED` sessions

We added a periodic reconciliation pass that scans for sessions where:

- `blog_sessions.status = QUEUED`
- no active lease exists
- the session is older than a short grace period
- no corresponding Redis payload exists in either the ready queue or processing set

Those sessions are re-enqueued from persisted DB state.

This makes Postgres the recovery source of truth when Redis has lost a runnable job entirely.

### 4. Do not introduce a transactional outbox in this change

A transactional outbox would address producer-side enqueue durability, but it does not directly solve the consumer-side "dequeued before lease" failure window.

The chosen change was intentionally narrower:

- preserve the existing Redis + lease architecture
- close the concrete recovery gaps already observed
- avoid a larger producer/dispatcher redesign until it is justified by additional failure evidence

## Recovery Model After This Change

The system now has three overlapping recovery layers.

### Redis transport reclaim

Handles:

- jobs removed from the ready queue
- never successfully turned into DB-leased work

Mechanism:

- reaper inspects expired Redis processing entries
- eligible entries are pushed back into the Redis ready queue

### Lease-based stale-worker recovery

Handles:

- jobs that did acquire a DB lease
- workers that died mid-execution

Mechanism:

- reaper expires stale leases
- reaper moves session state from `PROCESSING` back to `QUEUED`
- reaper constructs a new job from persisted DB state

### DB reconciliation

Handles:

- sessions that remain `QUEUED`
- no active lease exists
- Redis no longer has any corresponding queued or in-flight payload

Mechanism:

- reaper rebuilds missing Redis jobs from persisted session + active-version state

## Implemented Changes

### Queue behavior

- Added queue helpers to inspect tracked Redis session IDs
- Added an explicit helper to move expired processing entries back to the ready queue

### Reaper behavior

- Reaper now distinguishes between:
  - stale transport residue to clean up
  - orphaned transport claims to requeue
- Reaper now runs a queued-session reconciliation pass after stale-lease and stale-processing handling

### Session repository behavior

- Added a query for aged `QUEUED` sessions with no active lease

## Why This Is Correct Enough For Now

This change does not claim cross-system atomicity between Redis and Postgres.

What it does provide is a more complete at-least-once recovery story:

- if Redis lost the claim before a lease existed, Redis reclaim restores it
- if a worker died after a lease existed, stale-lease recovery restores it
- if Postgres says work should exist but Redis forgot it entirely, reconciliation restores it

That is a materially stronger guarantee than the previous design, while keeping the existing architecture intact.

## Consequences

### Positive

- closes the known job-loss window before DB lease creation
- prevents silent stranding of `QUEUED` sessions with no Redis presence
- keeps recovery decisions anchored in persisted DB state
- avoids immediate adoption of a larger outbox/dispatcher design

### Tradeoffs

- recovery logic is now more layered and more stateful
- reaper owns more policy than before
- recovery remains at-least-once, not exactly-once
- producer-side enqueue durability is still not equivalent to a full outbox pattern

## Follow-up Considerations

If future incidents show producer-side enqueue loss remains common, the next design step should be a transactional outbox for:

- initial generation enqueue
- outline resume enqueue
- revision enqueue

That would complement, not replace, the consumer-side recovery introduced here.
