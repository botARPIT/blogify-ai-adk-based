# ADR-2026-05-30: Schema Rationale for Worker Recovery, Versioning, and Review Semantics

## Status

Accepted and aligned with the worker recovery ADR on 2026-05-30.

## Purpose

This ADR documents the field-level schema decisions introduced during the worker recovery and versioned-state redesign.

The companion ADR focuses on architecture and workflow semantics:

- [ADR-2026-05-30-worker-recovery-versioned-state.md](/home/bot/repos/development/blogify-ai-adk-prod/backend/docs/ADR-2026-05-30-worker-recovery-versioned-state.md)

This document focuses on:

- which fields were added or repurposed
- why they were needed operationally
- whether each field is canonical or mirrored
- which failure mode each field helps address

## Context

Before the redesign, the backend lacked a durable model for:

- version history
- worker resume checkpoints
- outline-review resume metadata
- explicit user review actions
- separating session lifecycle truth from version-specific state

That meant:

- retries depended too much on transient Redis/ADK session state
- revision history was not real persistence
- final review semantics were overloaded onto `approved: bool`
- stale recovery could not reliably reconstruct the right execution context

## Canonical vs Mirrored State

One of the main schema decisions was to distinguish between:

- canonical fields
- mirrored compatibility fields

### Canonical fields

These are the fields the system should rely on as the source of truth for a resumable version:

- `blog_versions.job_phase`
- `blog_versions.feedback_text`
- `blog_versions.user_action`
- `blog_versions.invocation_id`
- `blog_versions.confirmation_request_id`
- `blog_versions.state_snapshot`
- `blog_sessions.active_blog_version_id`

### Mirrored fields

These fields are kept on `blog_sessions` mainly for compatibility, summary views, and convenience:

- `blog_sessions.outline_data`
- `blog_sessions.final_content`
- `blog_sessions.invocation_id`
- `blog_sessions.confirmation_request_id`
- `blog_sessions.adk_session_id`

These mirrored fields are still useful, but the durable per-version recovery truth should live on the active `blog_versions` row.

## Schema Changes and Rationale

### `blog_sessions.job_phase`

#### Why it exists

This field persists the next worker/recovery phase at the session level.

It exists because session `status` alone is not enough to decide what the worker should execute next. A session can be `QUEUED`, but the backend still needs to know whether the queued work is:

- a fresh generation
- an outline resume
- a revision
- an internal post-outline recovery phase

#### Operational role

- lets the worker know which execution path to run
- gives the reaper a persisted retry phase
- helps avoid guessing from UI-visible status alone

#### Canonical or mirrored

Session-level operational selector. It is important, but version-level `blog_versions.job_phase` is the more precise per-version persisted phase.

#### Failure mode it helps fix

Without it, stale recovery and retries would need to infer execution intent from status alone, which is too coarse and leads to incorrect reruns.

### `blog_sessions.current_stage`

#### Why it exists

This field captures the last known execution checkpoint in human-readable terms.

It was needed because `status=PROCESSING` is too vague for debugging and recovery decisions.

#### Operational role

- improves observability
- helps session detail APIs and UI
- lets recovery logic distinguish whether the worker was still at confirmation or had already advanced into research
- helps explain failures in DB inspection

#### Canonical or mirrored

Session-level operational checkpoint. Not a substitute for `job_phase`, but a complementary signal.

#### Failure mode it helps fix

This field was critical to diagnosing and fixing the `resume_outline` recovery bug:

- `job_phase=resume_outline`
- `current_stage=research`

That combination proved that the session had already consumed outline approval and should not replay the outline confirmation step.

### `blog_sessions.active_blog_version_id`

#### Why it exists

This field establishes which `blog_versions` row is the currently active canonical version for the session.

Without it, the system would have to guess which version row to resume, display, or revise.

#### Operational role

- anchors version-specific recovery
- identifies which snapshot to rehydrate into ADK/Redis runtime state
- determines which version row should be updated during resume/review flows
- allows revision to create a new version while keeping a single active pointer

#### Canonical or mirrored

Canonical pointer. This is the authoritative link from session to current version state.

#### Failure mode it helps fix

Without an explicit active version pointer, revision and resume flows can drift into “latest row by assumption” behavior, which is fragile once history exists.

### `blog_versions.job_phase`

#### Why it exists

This field stores the phase associated with the specific persisted version snapshot.

It is needed because the active version may carry resume metadata different from what the top-level session last displayed.

#### Operational role

- stores version-local recovery intent
- supports reaper fallback when session-level phase is missing or stale
- helps interpret a specific version row independently of the current session summary

#### Canonical or mirrored

Canonical per-version recovery phase.

#### Failure mode it helps fix

Without it, version history would preserve content but not execution context, making durable recovery incomplete.

### `blog_versions.feedback_text`

#### Why it exists

This field stores user-provided revision guidance or other resume-relevant feedback at the version level.

It was needed because feedback belongs to a specific output/version context, not just to the session globally.

#### Operational role

- carries revision instructions into the next worker run
- preserves user guidance alongside the version snapshot it applies to
- avoids mixing runtime failures with user-requested changes

#### Canonical or mirrored

Canonical per-version feedback field.

#### Failure mode it helps fix

Originally, user feedback was being written into `failure_reason`, which conflated revision intent with operational failure. This field separates those concerns.

### `blog_versions.user_action`

#### Why it exists

This field stores explicit user decisions at review time.

The backend needed this because session `status` alone cannot distinguish:

- system failure
- user rejection
- user revision request
- user approval

all in a version-aware way.

#### Operational role

- records explicit review decisions
- keeps approval/revision/rejection attached to the relevant version
- supports reporting and auditability

Supported values:

- `APPROVED`
- `REVISION_REQUESTED`
- `REJECTED`
- `NULL` meaning no explicit user review action recorded yet

#### Canonical or mirrored

Canonical per-version review decision.

#### Failure mode it helps fix

Without it, version rows could not explain whether they were superseded because of user revision, ended because of rejection, or accepted for publication.

### `blog_versions.invocation_id`

#### Why it exists

This field stores the ADK invocation identifier associated with the outline pause/resume checkpoint.

It is required because outline review resume is not a generic rerun. It needs to resume a specific paused invocation.

#### Operational role

- required for `resume_outline`
- links persisted DB state back to the paused runtime execution boundary
- supports resuming the exact confirmation flow after outline review

#### Canonical or mirrored

Canonical version-level resume metadata. Session-level copies are mirrors for convenience.

#### Failure mode it helps fix

Without it, the backend could not reliably resume the outline confirmation checkpoint after a user approved or edited the outline.

### `blog_versions.confirmation_request_id`

#### Why it exists

This field stores the confirmation request identifier for the paused outline review interaction.

Like `invocation_id`, it is required to replay the human approval response into the correct paused tool call boundary.

#### Operational role

- required input to `resume_outline`
- identifies which confirmation request should receive the approval payload

#### Canonical or mirrored

Canonical version-level resume metadata. Session-level copies are mirrors.

#### Failure mode it helps fix

Without it, the system would not know which paused review request to satisfy when resuming after outline approval.

### `blog_versions.state_snapshot`

#### Why it exists

This is the most important new persistence field.

It stores the durable execution snapshot that the worker can use to rebuild runtime state before continuing execution.

#### Operational role

- DB source of truth for resume state
- used to rehydrate ADK/Redis session state before execution
- preserves outline, approved outline, research data, draft, editor review, and related context
- decouples recovery correctness from ephemeral Redis-only runtime state

Typical contents include:

- `topic`
- `audience`
- `intent_result`
- `blog_outline`
- `approved_outline`
- `outline_feedback`
- `outline_review_result`
- `research_data`
- `blog_draft`
- `editor_review`

#### Canonical or mirrored

Canonical recovery payload.

#### Failure mode it helps fix

Without a durable state snapshot, retries and revisions depend on live runtime session state, which can be stale, missing, or inconsistent after worker failure.

## Why We Did Not Add `blog_versions.is_active`

We explicitly chose not to add an `is_active` flag to `blog_versions`.

Reason:

- `blog_sessions.active_blog_version_id` already provides a single authoritative active pointer

Adding both:

- `active_blog_version_id`
- `blog_versions.is_active`

would create two sources of truth for the same concept and introduce consistency risk.

## Why We Replaced `approved: bool` With `action`

The old contract:

- `approved: true/false`

was too weak to express the actual review semantics the backend needed.

`false` was ambiguous. It could mean:

- request revision
- reject permanently

The new explicit contract:

- `approved`
- `revision_requested`
- `rejected`

supports:

- clearer branching logic
- cleaner API validation
- explicit review audit semantics
- better alignment with `REJECTED` and `user_action`

## Why `REJECTED` Needed To Be Separate From `FAILED`

`FAILED` means:

- system failure
- runtime failure
- pipeline failure

`REJECTED` means:

- the user explicitly declined the artifact

These are different in every important sense:

- operational handling
- reaper semantics
- reporting
- business meaning

That distinction is reflected both in session status and version-level user action tracking.

## Why Session and Version Both Hold Some Overlapping Fields

We intentionally kept a limited amount of denormalized overlap.

Reason:

- session APIs and UI often need fast access to active summary data
- existing code paths already expected some fields at the session level
- the transition to fully version-centric reads can be incremental

The rule is:

- version row is the durable canonical record
- session row is the active summary and routing surface

## Summary

These schema changes were not cosmetic. Each field exists because a specific operational ambiguity or failure mode was observed:

- retries needed explicit phase persistence
- stale recovery needed checkpoint visibility
- revisions needed real version history
- outline review needed durable confirmation metadata
- user decisions needed explicit modeling
- runtime resume needed a DB-backed snapshot instead of Redis-only assumptions

The result is a schema that better supports:

- correctness under worker failure
- versioned review workflows
- reliable resume semantics
- clearer auditability
- separation between workflow truth and execution checkpoint detail
