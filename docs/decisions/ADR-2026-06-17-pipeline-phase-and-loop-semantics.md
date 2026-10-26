# ADR-2026-06-17: Pipeline Phase and Loop Semantics

## Status

Accepted and implemented on 2026-06-17.

## Purpose

This ADR records the naming and execution-semantics decisions for the blog agent pipeline.

It focuses on:

- why the previous loop naming was ambiguous
- which pipeline shape runs for each persisted blog job phase
- how pause/resume semantics differ from rerun-from-phase semantics

## Context

The codebase contains two writer/editor refinement loops that are structurally similar but are
not triggered the same way:

- one loop is embedded in the full app pipeline
- one loop is used only by the phase-resume runner

Previously both loops were named `refinement_loop`.

That created avoidable ambiguity in:

- code reading
- traces and logs
- documentation
- architecture review

The confusion was especially important because the system has multiple job phases:

- `fresh_generation`
- `resume_outline`
- `research_phase`
- `revision`

Those phases do not all run the same pipeline entrypoint.

## Decision

We explicitly distinguish the two loops by trigger context, not by internal structure.

### Full app pipeline loop

- helper: `_create_full_pipeline_draft_refinement_loop()`
- agent name: `full_pipeline_draft_refinement_loop`

Meaning:

- this is the writer/editor loop embedded in the full app pipeline after research

Triggered by:

- `fresh_generation`, once the full pipeline reaches research and drafting
- `resume_outline`, after outline approval is replayed into the paused full app pipeline

### Phase-resume loop

- helper: `_create_phase_resume_draft_refinement_loop()`
- agent name: `phase_resume_draft_refinement_loop`

Meaning:

- this is the writer/editor loop used by the phase runner created through
  `run_pipeline_from_phase("research_phase")`

Triggered by:

- `research_phase` stale-worker recovery
- `revision` jobs, which currently re-enter through the `research_phase` phase runner

## Phase-To-Runner Mapping

### `fresh_generation`

- executor path: `_execute_fresh_generation`
- pipeline function: `run_pipeline()`
- runner shape:
  - `intent_agent`
  - `outline_agent`
  - `outline_review_agent`
  - `research_agent`
  - `full_pipeline_draft_refinement_loop`

This is the full app pipeline.

### `resume_outline`

- executor path: `_execute_resume_outline`
- pipeline function: `resume_pipeline()`
- runner shape:
  - resumes the paused full app pipeline at the outline confirmation boundary
  - then continues with:
    - `research_agent`
    - `full_pipeline_draft_refinement_loop`

This is a true pause/resume path, not a fresh rerun from intent.

### `research_phase`

- executor path: `_execute_research_phase`
- pipeline function: `run_pipeline_from_phase("research_phase")`
- runner shape:
  - `research_agent`
  - `phase_resume_draft_refinement_loop`

This is a rerun-from-phase path used after outline approval has already been consumed.

### `revision`

- executor path: `_execute_revision`
- persisted job phase: `revision`
- pipeline function: `run_pipeline_from_phase("research_phase")`
- runner shape:
  - `research_agent`
  - `phase_resume_draft_refinement_loop`

The important distinction is:

- the persisted job phase remains `revision`
- the execution entrypoint is still the `research_phase` phase runner

## Review States Versus Pipeline States

### `AWAITING_OUTLINE_REVIEW`

This is a paused app-pipeline state, not an independent pipeline.

Operationally:

- the full pipeline has paused at `review_generated_outline`
- Postgres persists the approval metadata needed for resume
- no worker should continue execution until a user review endpoint submits approval/edit feedback

### `AWAITING_FINAL_REVIEW`

This is an application review state around persisted output, not an ADK pause boundary.

Operationally:

- research and drafting have already finished
- output has been persisted to the active version/session
- the user may:
  - approve
  - request revision
  - reject

## Consequences

### Positive

- code now exposes which refinement loop belongs to which execution path
- traces and runtime inspection become less ambiguous
- docs can describe job phases without collapsing multiple paths into one “writer/editor loop”

### Tradeoff

- there are still two loops with identical internal structure
- the distinction is semantic and trigger-based, not behavioral

That is intentional. The main issue was reader ambiguity, not a need to change execution behavior.
