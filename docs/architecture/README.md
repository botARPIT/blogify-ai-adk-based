# Architecture

Blogify's current architecture is documented with the following artifacts:

- [System context diagram](SystemArchitecture.png) — user, API, PostgreSQL, Redis, worker, and Google ADK workflow.
- [Generation workflow diagram](WorkflowDiagram.png) — durable dispatch, worker processing, human review pauses, and persisted results.
- [Editable workflow source](WorkflowDiagram.excalidraw) — source for the current workflow diagram.
- [Multi-agent pipeline diagram](<Blogify Content Generation Workflow.png>) — fresh generation, outline review, research, writing, editing, and final review.
- [Editable multi-agent pipeline source](<Blogify Content Generation Workflow.excalidraw>) — source for the current pipeline diagram.
- [Database schema diagram](blogify-database-schema.excalidraw) — ORM-level table and relationship view.
- [Backend architecture guide](backend.md) — current runtime, recovery, API, persistence, and security behavior.

The diagrams describe the outbox-based workflow used by the API, worker, and reaper. The schema diagram is not live-database evidence; validate it against Alembic migrations and the deployed database before applying changes.
