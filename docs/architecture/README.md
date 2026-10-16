# Architecture diagrams

These are editable native Excalidraw files. Open them at [excalidraw.com](https://excalidraw.com) or import the files there.

- [System overview](./blogify-system-design.excalidraw) — the easy component map: client, API, Redis, worker, PostgreSQL, and recovery process.
- [Generation and review workflow](./blogify-workflow-detail.excalidraw) — the detailed stage flow, outline/final review pauses, state checkpoints, outbox dispatch, and lease recovery.
- [Database schema](./blogify-database-schema.excalidraw) — tables and declared ORM relationships from `backend/src/models/orm_models.py`.

The system diagrams show the intended outbox-based workflow. The current working tree deletes `backend/src/services/blog_service.py`, so verify the API-to-outbox transaction and relay wiring after that implementation is restored. The schema diagram reflects ORM declarations, not a live database introspection; compare it with Alembic history and the deployed schema before applying migrations.
