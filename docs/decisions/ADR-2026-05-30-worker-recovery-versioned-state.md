# ADR-2026-05-30: Worker Recovery, Versioned State, and Human Review Semantics

## Status

Accepted and partially implemented on 2026-05-30.

## Context

During debugging of the blog generation worker, several failures exposed a deeper architectural problem in how the system handled queue ownership, lease visibility, human review checkpoints, and retry recovery.

The system originally used:

- Redis as both transport and practical runtime state carrier for worker progress
- Postgres for session metadata and lease audit rows
- a single `job_phase` field to represent both user workflow phase and worker recovery checkpoint
- direct status writes in multiple places, with inconsistent transition enforcement

This produced several concrete failure modes:

1. Queue claim and DB lease acquisition were split across Redis and Postgres without a committed DB recovery boundary.
2. Lease acquisition was only flushed, not committed immediately, so stale-lease detection and recovery had weak observability.
3. Lease release was not reliably committed.
4. Final review rejection was conflated with system failure.
5. Revision and resume semantics depended too heavily on transient ADK/Redis session state.
6. Reaper recovery and Redis visibility reclaim could diverge and reintroduce jobs that DB still considered in-flight.
7. `resume_outline` was being reused as a long-lived recovery pointer even after the system had already advanced into research.
8. Phase-specific ADK runners reused agent instances already attached to the main pipeline, causing parent-ownership errors.
9. Research payloads were assumed to already be dict-shaped, but resumed runs could surface them as JSON strings.

## How The Issue Was Identified

The primary debugging direction came from production-like failures and targeted DB/log inspection.

The user identified the highest-signal symptoms:

- state transitions did not appear trustworthy
- worker claim and lease acquisition did not look transactional
- revision requests were being marked as failures
- user feedback was ending up in `failure_reason`
- `job_phase` and `current_stage` were diverging
- reaper logs showed `Invalid state transition: PROCESSING -> QUEUED`
- stale jobs were being re-enqueued with `resume_outline` even when `current_stage` had already advanced to `research`
- resumed jobs later failed with payload-shape errors such as `string indices must be integers, not 'str'`

The investigation relied on:

- session table snapshots
- version table snapshots
- lease audit rows
- reaper logs
- worker failure logs
- codepath tracing through service, worker, queue, reaper, executor, and pipeline layers

This was an important part of the outcome: the issues were not found by abstract redesign first. They were found by tracing real invariants that were being violated in persisted state and runtime logs.

## Assistant Contribution

The assistant helped in four ways:

1. Mapped the observed failures back to concrete codepaths in the worker, reaper, executor, pipeline, and repository layers.
2. Distinguished between user workflow states and worker recovery semantics when the system was overloading the same fields.
3. Proposed minimal but structurally correct fixes instead of local symptom patches.
4. Implemented the code and migration changes iteratively as each failure mode became visible.

The architecture direction itself was heavily shaped by the user's questions and decisions:

- Redis should be transport only, not the source of truth
- DB should hold resumable snapshot state
- revision should create a new version
- outline approval resume should update the current version
- user rejection should be distinct from system failure
- reaper should have its own explicit recovery path

## Decision

We decided to move the system toward DB-authoritative recovery with versioned state snapshots, while keeping Redis as a transport layer.

### 1. Best-effort worker acquisition boundary

We did not attempt impossible cross-system ACID atomicity between Redis and Postgres.

Instead, we adopted this model:

1. Redis claim happens first and acts as transport claim only.
2. Worker opens one DB transaction.
3. Session state is validated.
4. Lease is acquired.
5. Active version state is hydrated.
6. Session and version are marked `PROCESSING`.
7. The transaction is committed immediately.

This makes the DB state visible and authoritative before actual execution starts.

### 2. Redis is transport, DB is state

We decided that resumable execution state must persist in Postgres, not only in Redis/ADK runtime session state.

To support that:

- `blog_versions` was added as a durable per-version state table
- `blog_sessions.active_blog_version_id` was added
- DB snapshots are now used to rehydrate ADK session state before execution resumes

### 3. Introduce versioned persistence

We chose this versioning model:

- `fresh_generation` creates the initial version row
- `resume_outline` updates the active version row
- `revision` creates a new version row and advances `active_blog_version_id`

This preserves user-visible version history without creating a new row for every transient checkpoint.

### 4. Separate user rejection from system failure

We added `REJECTED` as a terminal state distinct from `FAILED`.

This keeps:

- user intent (`REJECTED`)
- runtime/system failure (`FAILED`)

separate for both operational semantics and reporting semantics.

We also changed final review from a boolean field to explicit actions:

- `approved`
- `revision_requested`
- `rejected`

### 5. Use explicit terminal-state helpers

We decided that terminal state checks should come from the enum helper rather than repeated hardcoded sets.

This reduces drift and prevents call sites from silently omitting newly added terminal states such as `REJECTED`.

### 6. Reaper gets a dedicated recovery path

We decided not to weaken the normal public state machine by allowing generic `PROCESSING -> QUEUED`.

Instead:

- normal workflow continues to use validated transitions
- stale-lease recovery uses a dedicated reaper-only repository path

Redis visibility reclaim was reduced to transport cleanup only. It no longer requeues work independently of DB state.

### 7. Separate user workflow phase from recovery checkpoint semantics

We discovered that `resume_outline` was being used too broadly.

That is valid only for:

- a session paused at outline confirmation

It is not valid for:

- a session that already consumed outline confirmation and advanced into research

As a targeted fix, we introduced `research_phase` as an internal recovery phase for stale reaper retries that had already crossed the outline approval boundary.

### 8. Rebuild phase runners with fresh agent instances

Phase-specific reruns must not reuse ADK agent instances already attached to the main pipeline graph.

We switched to agent factory functions and fresh pipeline/phase runner construction to avoid parent-ownership collisions.

### 9. Normalize resumed payloads at the execution boundary

We decided not to trust research payload shape on resumed runs.

`research_data` is now normalized before:

- cost commits
- version persistence
- snapshot persistence

This avoids failures when structured payloads arrive as serialized JSON strings.

## Implemented Changes

The following changes were implemented during this ADR:

### Data model and persistence

- Added `blog_versions`
- Added `blog_sessions.active_blog_version_id`
- Added `blog_versions.user_action`
- Added `REJECTED`
- Added explicit final review actions
- Added durable `state_snapshot`-based resume flow

### Worker and lease lifecycle

- Lease acquisition now validates and hydrates in DB
- Lease acquisition commits immediately before execution
- Lease release is committed explicitly
- Worker uses version snapshot state to rehydrate execution

### Reaper behavior

- Reaper uses a dedicated stale-processing recovery path
- Redis processing-set reclaim is now transport cleanup only
- Reaper selects recovery phase from persisted DB state, not Redis transport artifacts
- `research_phase` was introduced for post-outline stale recovery

### Review semantics

- Final review now uses action-based semantics
- `revision_requested` requeues work
- `rejected` is terminal and distinct from `failed`
- feedback text is only accepted for revision requests

### Pipeline construction

- Agent factories replaced unsafe reuse of globally parented agent objects
- Phase runners are built from fresh agent instances

### Execution boundary hardening

- `research_data` is normalized before persistence and cost indexing

## State Machine Design

The ADR now explicitly distinguishes three related but different concepts:

1. session lifecycle status
2. worker/recovery phase
3. human-readable execution checkpoint

Those map to:

- `blog_sessions.status`
- `blog_sessions.job_phase` and `blog_versions.job_phase`
- `blog_sessions.current_stage`

They are related, but they are not interchangeable.

### 1. Session lifecycle state machine

The primary lifecycle state machine is modeled through `BlogSessionStatus`.

Supported backend lifecycle states are:

- `QUEUED`
- `PROCESSING`
- `AWAITING_OUTLINE_REVIEW`
- `AWAITING_FINAL_REVIEW`
- `COMPLETED`
- `FAILED`
- `REJECTED`
- `CANCELLED`

Supported normal transitions are intentionally strict:

- `QUEUED -> PROCESSING`
- `PROCESSING -> AWAITING_OUTLINE_REVIEW`
- `PROCESSING -> AWAITING_FINAL_REVIEW`
- `PROCESSING -> FAILED`
- `AWAITING_OUTLINE_REVIEW -> QUEUED`
- `AWAITING_FINAL_REVIEW -> COMPLETED`
- `AWAITING_FINAL_REVIEW -> QUEUED`
- `AWAITING_FINAL_REVIEW -> REJECTED`

This state machine exists to represent workflow truth at the session level:

- whether work is runnable
- whether human input is required
- whether the session ended successfully
- whether the session failed operationally
- whether the user rejected the result

The key design choice is that this state machine is intentionally conservative. It is not meant to encode every operational recovery trick. It is meant to model externally meaningful workflow transitions.

### 2. Why we introduced a separate reaper recovery transition path

The reaper must sometimes move a stale in-flight session from:

- `PROCESSING -> QUEUED`

That transition is valid for recovery, but it is not a valid normal workflow transition.

If that transition were added to the public lifecycle state machine, then any caller using the generic status update path could push active work back to `QUEUED` without going through stale-lease semantics. That would weaken correctness and make the state machine less trustworthy.

For that reason, we implemented two transition paths:

#### Normal workflow transition path

Used by:

- service methods
- worker success/failure paths
- human review flows

Characteristics:

- validated by `BlogSessionStatus.validate_transition(...)`
- represents ordinary application workflow

#### Reaper recovery transition path

Used by:

- stale-lease recovery only

Characteristics:

- implemented as a dedicated repository recovery method
- bypasses the public transition validator intentionally
- only used when the system has already determined that the worker lost ownership

This separation is important because it preserves two guarantees:

1. The public lifecycle state machine stays strict and meaningful.
2. Operational recovery remains possible without weakening the user-visible workflow model.

### 3. Worker/recovery phases

The system also uses `job_phase` to decide what the worker should run next.

Supported phases now include:

- `fresh_generation`
- `resume_outline`
- `revision`
- `research_phase`

These are not the same thing as session statuses.

Their significance:

- `fresh_generation`
  - create a new blog generation from scratch
- `resume_outline`
  - replay the outline approval confirmation into a paused outline-review checkpoint
- `revision`
  - create a new version row and regenerate from an existing result using user feedback
- `research_phase`
  - internal recovery phase for sessions that already consumed outline approval and had advanced into post-approval execution before a worker died

The main lesson here was that one phase name cannot safely represent both:

- a user workflow milestone
- a worker recovery checkpoint

That is why `research_phase` was added as an internal recovery phase instead of continuing to overload `resume_outline`.

### 4. Backend workflow currently supported

The backend supports these major execution flows:

#### Fresh generation flow

1. User requests generation
2. Session created as `QUEUED`
3. Worker acquires lease and moves session to `PROCESSING`
4. Pipeline runs intent and outline generation
5. If outline approval is required, session moves to `AWAITING_OUTLINE_REVIEW`
6. After outline approval, session goes back to `QUEUED`
7. Worker resumes execution
8. Final result moves session to `AWAITING_FINAL_REVIEW`
9. Final review leads to:
   - `COMPLETED`
   - `QUEUED` with revision request
   - `REJECTED`

#### Outline resume flow

1. Session is paused at `AWAITING_OUTLINE_REVIEW`
2. User approves or edits outline
3. Session returns to `QUEUED`
4. Worker runs `resume_outline`
5. If recovery happens after the outline confirmation has already been consumed, reaper can convert recovery into `research_phase`

#### Revision flow

1. Session is in `AWAITING_FINAL_REVIEW`
2. User requests revision
3. Session returns to `QUEUED`
4. Active version is duplicated into a new version row
5. Worker resumes from post-outline execution with the revised context

#### Stale worker recovery flow

1. Session is `PROCESSING`
2. Lease heartbeat expires
3. Reaper expires the lease
4. Reaper moves the session back to `QUEUED` through a dedicated recovery path
5. Reaper enqueues the next phase based on persisted DB recovery state
6. Redis processing entries are cleaned as transport artifacts only

### 5. Significance of `current_stage`

`current_stage` in `blog_sessions` exists because `status` and `job_phase` are too coarse for operational diagnosis and targeted recovery.

Examples:

- `status=PROCESSING` only says “work is in-flight”
- it does not tell us whether the worker was in intent, outline, research, writer, editor, or revision work

`current_stage` fills that gap.

It is used to provide:

- operational observability
- better UI/session detail display
- more precise stale recovery decisions
- a debugging trail for where the worker was last known to be

Examples of stage values seen in this work:

- `intent`
- `research`
- `revision_research`
- `outline_review`
- `final_review`
- `revision_requested`
- `requeued_by_reaper`
- `rejected`

The `research_phase` recovery fix depends on this field. Specifically:

- if `job_phase=resume_outline`
- but `current_stage=research`

then the system knows that outline confirmation has already been consumed and that it must resume post-approval execution instead of replaying the outline review tool step.

### 6. Why `status`, `job_phase`, and `current_stage` all exist

All three are required because they answer different questions:

- `status`
  - what is the lifecycle state of the session?
- `job_phase`
  - what executable worker path should run next?
- `current_stage`
  - where inside processing did the worker last reach?

Trying to collapse them into one field caused ambiguity and recovery bugs.

This ADR intentionally moved the system away from that ambiguity.

### 7. State-machine-related schema decisions

The important schema additions and their role in state handling are:

- `blog_sessions.job_phase`
  - persisted worker/recovery phase selector
- `blog_sessions.current_stage`
  - last known execution checkpoint for observability and recovery interpretation
- `blog_sessions.active_blog_version_id`
  - authoritative pointer to the version row whose snapshot should be resumed
- `blog_versions.job_phase`
  - phase associated with the persisted version snapshot
- `blog_versions.feedback_text`
  - stores revision guidance or resume-related user instructions at the version level
- `blog_versions.user_action`
  - stores explicit user review decisions independently of operational failure
- `blog_versions.invocation_id`
  - required for outline confirmation resume
- `blog_versions.confirmation_request_id`
  - required for outline confirmation resume
- `blog_versions.state_snapshot`
  - canonical durable resume payload used to rebuild runtime execution state

### 8. Why this state-machine design improves reliability

This design makes the system more reliable because:

- normal workflow rules remain strict
- reaper recovery is explicit and auditable
- user rejection is not conflated with runtime failure
- worker retries use committed DB recovery state
- transport cleanup cannot silently redefine runnable work
- stale recovery can distinguish “still at confirmation boundary” from “already executing post-confirmation work”

## Consequences

### Positive

1. Recovery semantics are now anchored in Postgres instead of accidental Redis runtime state.
2. Lease visibility is improved because processing state is committed before execution begins.
3. Reaper no longer weakens the public state machine.
4. Redis can no longer independently make work runnable when DB disagrees.
5. Final review semantics are clearer for users and operators.
6. Versioned snapshots make revisions and retries auditable.
7. ADK phase reruns no longer fail from agent-parent reuse.
8. Resume flows are more resilient to payload shape drift.

### Tradeoffs

1. The system is still best-effort across Redis and Postgres, not globally ACID.
2. `job_phase` still carries both external and internal semantics in some places, even though this was improved with `research_phase`.
3. More persistence logic now exists in worker/executor/repository boundaries, which increases coordination complexity.

## Operational Notes

When debugging future incidents in this area, inspect these together:

- `blog_sessions.status`
- `blog_sessions.current_stage`
- `blog_sessions.job_phase`
- `blog_sessions.active_blog_version_id`
- `blog_versions.status`
- `blog_versions.job_phase`
- `blog_versions.state_snapshot`
- `session_leases`
- Redis queue and processing sets

The key invariant is:

- Redis may carry transport ownership
- Postgres must decide resumability and next runnable checkpoint

## Follow-up Work

The current system is significantly more robust, but further cleanup is still warranted.

Recommended next steps:

1. Separate user-facing workflow phase from internal recovery checkpoint more formally, rather than extending `job_phase` incrementally.
2. Add explicit tests for:
   - stale lease recovery
   - outline pause and outline resume
   - revision creation and active-version advancement
   - rejected vs failed semantics
   - post-outline stale recovery into `research_phase`
   - payload normalization on resumed runs
3. Remove temporary debug `print()` calls still present in queue/service codepaths.
4. Review whether additional internal recovery phases are needed for writer/editor-stage stale recovery.

## Summary

This ADR captures a shift from loosely coupled runtime behavior to explicit recovery-oriented design.

The system is now more reliable because:

- state authority moved to the database
- retries are driven by committed recovery information
- review semantics are explicit
- stale recovery is separate from user workflow transitions
- phase reruns rebuild safe agent graphs
- resumed payloads are normalized before use

The most important lesson from this work is that retries, human checkpoints, and transport visibility cannot be modeled reliably if user workflow state and worker recovery state are treated as the same concept.
