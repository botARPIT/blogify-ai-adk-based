# Blogify Backend: Deep-Dive Engineer Interview Version

## Problem

The system generates blogs asynchronously with a human review checkpoint after outline generation and another review state after final draft generation. The challenge is not just orchestration of AI agents, but making the workflow recoverable, inspectable, and revision-friendly under worker crashes and repeated user feedback.

## High-Level Architecture

- FastAPI handles request validation, authentication, session creation, and review actions.
- Redis acts as queue transport for background jobs.
- PostgreSQL is the canonical source of truth for:
  - session lifecycle state
  - active blog version
  - persisted feedback and review metadata
  - budget/accounting state
  - lease ownership and recovery signals
- Workers dequeue jobs, acquire DB-backed leases, hydrate active state, run the pipeline, and persist results.
- A reaper process handles stale leases, stale Redis processing entries, and queued-session reconciliation.

## Phase Model

There are four important persisted job phases:

- `fresh_generation`
- `resume_outline`
- `research_phase`
- `revision`

They do not all execute the same runner:

- `fresh_generation` -> `run_pipeline()` -> full app pipeline
- `resume_outline` -> `resume_pipeline()` -> resume paused full app pipeline
- `research_phase` -> `run_pipeline_from_phase("research_phase")`
- `revision` -> persisted as `revision`, but currently re-enters via `run_pipeline_from_phase("research_phase")`

This distinction matters because outline approval is a true resumable pause boundary, while revision is a rerun-from-phase path.

## State Model

The canonical state lives in Postgres:

- `blog_sessions` tracks lifecycle state
- `blog_versions` tracks versioned content state and feedback snapshots
- the active version pointer determines what state gets rehydrated

Redis should not be treated as the source of truth for execution state. It only transports jobs.

## Reliability and Recovery

### Queue / lease split

The worker first dequeues from Redis and then acquires a DB lease. That creates a classic non-atomic boundary between queue claim and DB ownership.

### Recovery mechanisms

To handle that, the system uses multiple overlapping mechanisms:

- stale DB lease recovery for workers that die mid-execution
- stale Redis processing-entry requeue for jobs lost before lease acquisition
- queued-session reconciliation for sessions that remain runnable in DB but have no Redis presence

This provides an at-least-once recovery model rather than exactly-once execution.

### Tradeoffs

The main tradeoff is complexity versus rigor:

- keeping Redis as transport and Postgres as canonical state simplifies reasoning about business state
- but the queue/database split requires recovery policy and reconciliation logic

A transactional outbox would help producer-side enqueue durability, but it would not fully solve consumer-side failure windows like dequeue-before-lease death.

## Human Feedback Propagation

User feedback is persisted on the active version and in the version state snapshot. That means:

- outline review feedback can be replayed into the paused outline confirmation boundary
- final review revision feedback survives retries and becomes part of the next active revision state

The key design choice is that user feedback is not transient UI-only data. It becomes durable pipeline input.

## What I Would Highlight In An Interview

- how I separated transport state from canonical workflow state
- why `resume_outline` and `revision` are not the same thing
- how lease-based recovery and reconciliation close different failure windows
- what remains imperfect:
  - still at-least-once, not exactly-once
  - PR/test environment still needs dependency cleanup
  - recovery behavior is reliable but not minimal in complexity

## Concise Positioning

This is not just an AI app. It is an AI workflow system with:

- asynchronous execution
- persisted review checkpoints
- versioned content state
- distributed recovery semantics
- operational documentation and postmortem discipline
