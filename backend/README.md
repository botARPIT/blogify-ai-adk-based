# Backend Workspace

This folder is the explicit backend entrypoint layer for the repository.

It does not duplicate the application code under `src/`. Instead, it provides:

- a stable backend app import path: `backend.app:app`
- backend-specific startup scripts under `backend/scripts/`

Use these commands from the repo root:

```bash
bash backend/scripts/init_db.sh
bash backend/scripts/run_api.sh
```

Useful operational scripts:

- `bootstrap_dev.sh` — create the development environment, verify local Postgres/Redis, migrate, and run unit tests.
- `init_db.sh` — apply Alembic migrations only.
- `run_api.sh` / `run_worker.sh` — start the API and background worker locally.
- `test.sh` — run unit, integration, and coverage suites.
- `benchmark_api.py` / `profile_generation.py` — read-only performance diagnostics.
- `backup-db.sh` — create and rotate PostgreSQL backups when `BACKUP_DIR` is mounted by the host.

Deploy on an Azure Linux VM with Docker Compose using the
[Azure runbook](../docs/runbooks/azure-vm.md). The legacy AWS workflow is disabled.
`check-observability.py` checks live scrape targets, Grafana datasources and dashboard queries.
