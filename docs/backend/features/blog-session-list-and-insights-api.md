# Blog session list and insights API

## `GET /api/v1/blogs/`

The list endpoint now accepts server-side pagination and filters:

```text
GET /api/v1/blogs/?page=1&page_size=9&status=FAILED&q=webhook
```

- `page`: one-based page number; defaults to `1`.
- `page_size`: 1–50 rows; defaults to `12`.
- `status`: repeatable enum filter (`QUEUED`, `PROCESSING`, `AWAITING_OUTLINE_REVIEW`, `AWAITING_FINAL_REVIEW`, `COMPLETED`, `FAILED`, `REJECTED`, `CANCELLED`).
- `q`: optional case-insensitive search over topic and audience, up to 100 characters.

The response is an envelope rather than the previous bare array:

```json
{
  "items": [{
    "session_id": 123,
    "topic": "A story topic",
    "audience": "Founders",
    "tone": "Practical",
    "status": "COMPLETED",
    "current_stage": "completed",
    "created_at": "2026-10-13T00:00:00Z",
    "completed_at": "2026-10-13T00:05:00Z",
    "cost_usd": 0.0123
  }],
  "page": 1,
  "page_size": 9,
  "total": 1,
  "total_pages": 1
}
```

`cost_usd` is the recorded `budget_spent_usd` for that session. Results and aggregate counts are always restricted to the authenticated user.

## `GET /api/v1/blogs/insights`

Accepts `days` from 7 to 365 (default 30). Daily generation counts, total generated, total spend, and the 12 recent per-session cost rows exclude `FAILED`, `REJECTED`, and `CANCELLED` sessions. `completed_count` reports completed sessions; `failed_count` remains a separate workflow-health count for those unsuccessful statuses. This supports the Insights page charts without loading every session into the browser.

## Compatibility

The list response shape changed from a bare array to a paginated envelope. Update clients to read `items` and pagination metadata. Existing query-free clients that deserialize the array need to migrate. No generation, authentication, ownership, or workflow behavior changed.
