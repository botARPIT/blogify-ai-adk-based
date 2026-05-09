# Postmortem: session_leases.id Had No Auto-Increment Sequence

**Date:** 2026-05-08
**Severity:** P1 — Blog generation completely broken for all users
**Author:** Engineering
**Status:** Resolved

---

## What Happened

The blog worker crashed on every job attempt with this stack trace:

```
sqlalchemy.dialects.postgresql.asyncpg.AsyncAdapt_asyncpg_dbapi.IntegrityError:
<class 'asyncpg.exceptions.NotNullViolationError'>: null value in column "id"
of relation "session_leases" violates not-null constraint
DETAIL: Failing row contains (null, 5, worker-bot-Aspire-A715-42G-2261959,
2026-05-08 16:45:42.83723+00, 1, 2026-05-08 16:40:42.83723+00, ..., null, null).
```

Workers tried to acquire a lease on each job. The `INSERT INTO session_leases` call failed because the `id` column had no default value — it came in as `null`, and PostgreSQL rejected it.

No jobs processed. The entire generation pipeline was down.

---

## Timeline

- **~16:40 UTC** — Blog worker restarts after previous session. First job arrives.
- **16:45 UTC** — Worker crashes mid-lease-acquire. IntegrityError surfaces in logs.
- **16:50 UTC** — Investigation begins. Error traced to `session_leases.id`.
- **16:51 UTC** — Confirmed: `id` column has `column_default = None` in the live DB.
- **16:54 UTC** — Migration 104 written and applied. Sequence attached.
- **16:54 UTC** — `id` column now shows `nextval('session_leases_id_seq'::regclass)`.
- **16:55 UTC** — Workers restarted. Jobs processing normally.

Total downtime: ~15 minutes.

---

## Root Cause

The `session_leases` table was created in migration 101 with this column definition:

```python
sa.Column('id', sa.Integer(), autoincrement=True, nullable=False)
```

`autoincrement=True` in SQLAlchemy tells the ORM layer to handle auto-increment at the Python level, but it does nothing to the database schema unless the column is explicitly declared as a primary key or uses `sa.Identity()`. Alembic rendered the DDL as:

```sql
CREATE TABLE session_leases (
    id INTEGER NOT NULL,
    ...
)
```

No `SERIAL`, no `SEQUENCE`, no `DEFAULT`. PostgreSQL created an integer column that required a caller-supplied value. The ORM never supplied one because it expected the DB to generate it.

This is a known SQLAlchemy/Alembic footgun. Using `autoincrement=True` on a non-primary-key column does not produce a database-side sequence. The correct form for PostgreSQL is either `sa.Identity()` or an explicit sequence with `server_default`.

---

## How We Found It

The error message was unusually precise. `null value in column "id" of relation "session_leases"` pointed directly to the schema gap, not to a code bug.

We confirmed the column had no default by querying the information schema:

```sql
SELECT column_name, column_default, is_nullable, data_type
FROM information_schema.columns
WHERE table_name = 'session_leases' AND column_name = 'id';
```

Output: `column_default = NULL`. That was the entire diagnosis.

---

## What We Tried

There was only one viable fix: attach a sequence to the existing column without dropping the table (it had live rows we needed to keep).

Option A was to use `ALTER TABLE ... ALTER COLUMN id SET DEFAULT nextval(...)`. The challenge was seeding the sequence above the current `MAX(id)` so it wouldn't collide with existing rows.

We went with this approach directly. No alternatives were seriously explored because the problem was clear.

---

## Fix

Migration `104_fix_session_leases_id_sequence.py`:

```sql
-- 1. Create the sequence
CREATE SEQUENCE IF NOT EXISTS session_leases_id_seq;

-- 2. Set DEFAULT on the column
ALTER TABLE session_leases
  ALTER COLUMN id SET DEFAULT nextval('session_leases_id_seq');

-- 3. Seed above the current max to avoid conflicts
SELECT setval('session_leases_id_seq', COALESCE(MAX(id), 0) + 1, false)
FROM session_leases;

-- 4. Mark the sequence as owned by the column (drops with table)
ALTER SEQUENCE session_leases_id_seq OWNED BY session_leases.id;
```

After running this, the column showed `nextval('session_leases_id_seq'::regclass)` as its default. Workers recovered immediately on restart.

---

## What We Changed Going Forward

- Migration 101 was left as-is (changing a deployed migration is worse than adding a fixup migration).
- Future table definitions use explicit `sa.Identity()` for auto-increment columns or define them as `sa.Column('id', sa.Integer(), primary_key=True)` which Alembic handles correctly.
- Added a note to the internal migration review checklist: verify that new `INTEGER NOT NULL` columns have a database-side default if they are expected to be auto-populated.

---

## Lessons

The gap between SQLAlchemy's `autoincrement=True` and an actual PostgreSQL sequence is well-documented but easy to miss. If you're defining a column that isn't the declared primary key but still needs auto-increment behavior, you need `sa.Identity()` or an explicit server default. The ORM's Python-level auto-increment doesn't translate to DDL.

Migration review is where this should have been caught. An `INTEGER NOT NULL` column with no `DEFAULT` on a table that gets `INSERT`ed by the ORM is a red flag.
