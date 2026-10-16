# End-to-end tests

These two tests exercise the FastAPI-to-PostgreSQL/Redis path and worker execution. Model/provider calls are scripted; they do not use Google or Tavily credentials.

Set both variables to dedicated test services before running:

```sh
export BLOGIFY_TEST_DATABASE_URL='postgresql+asyncpg://user:password@localhost:5432/blogify_test'
export BLOGIFY_TEST_REDIS_URL='redis://localhost:6379/15'
cd backend
.venv/bin/pytest tests/e2e -q
```

The database user needs permission to create schemas. Each test creates and drops a uniquely named PostgreSQL schema. Redis keys use a unique test prefix and are not flushed. Do not point the database URL at a production database.
