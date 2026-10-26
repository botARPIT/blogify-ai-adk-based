# Blogify Backend: 2-Minute Interview Explanation

I built an asynchronous AI blog-generation backend where the API creates canonical session state in PostgreSQL, enqueues work in Redis, and a worker executes a multi-phase agent pipeline. The pipeline starts with intent classification and outline generation, then pauses for a human outline review before continuing into research, writing, and editing.

The most interesting part of the system is the reliability model. Redis is only the queue transport layer, while PostgreSQL is the source of truth for session status, active version state, review metadata, and recovery checkpoints. I added lease-based worker ownership, stale-worker recovery through a reaper, requeue logic for lost Redis processing entries, and reconciliation for `QUEUED` sessions that no longer have a Redis job.

Another key part is that there are different execution semantics for different phases. `fresh_generation` runs the full app pipeline, `resume_outline` resumes a paused pipeline after outline approval, and `research_phase` plus `revision` re-enter through a separate phase-runner path. I documented those distinctions in ADRs and architecture docs because they directly affect debugging and recovery correctness.

The project taught me a lot about distributed-systems tradeoffs in AI workflows: exactly where state should be canonical, how to persist human feedback so retries stay correct, and how to reason about at-least-once recovery without pretending queue and database operations are atomic when they are not.
