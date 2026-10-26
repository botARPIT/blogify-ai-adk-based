# Daily blog-generation limit

Each authenticated user may start **five blog generations per UTC calendar day**.
An accepted request consumes a slot even if its workflow later fails. A request
rejected before a session is created does not consume a slot. Repeating an
idempotency key for an existing session does not consume another slot.

PostgreSQL is authoritative. `user_blog_quotas` stores one counter row per user
with the UTC usage date. A PostgreSQL `INSERT ... ON CONFLICT DO UPDATE` atomically
resets the row for a new day or increments the current-day count. The row lock
serializes simultaneous generation requests for a user. The quota update, blog
session, and workflow outbox event commit in the same transaction. There is no
scheduled job or database trigger to reset counters.

`POST /api/v1/blogs/generate` returns HTTP 429 with
`DAILY_BLOG_LIMIT_REACHED` after the fifth accepted generation. `GET
/api/v1/blogs/budget` reports `daily_blog_limit_left` and the additive
`daily_blog_limit` field. The day boundary is 00:00 UTC because user timezone
preferences are not currently part of the account model.

Apply Alembic revision `c3d4e5f6a7b8` before deploying the API change.
