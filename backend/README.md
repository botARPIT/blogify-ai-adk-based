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
