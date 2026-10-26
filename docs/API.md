# Blogify AI API guide

The Blogify API is versioned under `/api/v1`. It accepts a blog-generation request quickly, processes it asynchronously, and exposes polling and human-review endpoints for the session lifecycle.

The OpenAPI document is the authoritative field-level contract:

- Interactive reference: `http://localhost:8000/docs`
- Raw schema: `http://localhost:8000/openapi.json`
- Postman collection: [`postman/Blogify-AI.postman_collection.json`](../postman/Blogify-AI.postman_collection.json)

## Authentication

Registering or logging in sets the local `auth_token` cookie. All `/blogs` routes require an authenticated user and enforce session ownership. The middleware also accepts `Authorization: Bearer <token>` for non-browser clients.

```bash
curl -c cookies.txt \
  -H 'Content-Type: application/json' \
  -d '{"email":"demo@example.com","password":"password123","display_name":"Demo User"}' \
  http://localhost:8000/api/v1/auth/register
```

To sign in to an existing account, send the same credentials to `POST /api/v1/auth/login`. Confirm the active session with `GET /api/v1/auth/me`; clear it with `POST /api/v1/auth/logout`.

## Generation lifecycle

```text
Generate → poll status → outline review → poll status → final review → completed content
```

### 1. Start a generation

`POST /api/v1/blogs/generate` returns `202 Accepted` with a `session_id`. The work continues in the background.

```bash
curl -b cookies.txt \
  -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: demo-healthcare-ai-001' \
  -d '{
    "topic": "The future of AI in healthcare",
    "audience": "healthcare leaders",
    "tone": "professional"
  }' \
  http://localhost:8000/api/v1/blogs/generate
```

Example response:

```json
{
  "session_id": 42,
  "status": "QUEUED",
  "adk_session_id": "...",
  "created_at": "2026-10-26T12:00:00Z"
}
```

Use one stable `Idempotency-Key` for retries of the same user intent. Reusing a key for a terminal session returns `409`; a new generation requires a new key. A daily limit returns `429` and insufficient budget returns `402`.

### 2. Poll session status

`GET /api/v1/blogs/{session_id}/status` returns the current status and stage.

```bash
curl -b cookies.txt \
  http://localhost:8000/api/v1/blogs/42/status
```

Poll until the session enters an outline-review or final-review state, fails, or completes. Use `GET /api/v1/blogs/{session_id}` for the fuller session record and `GET /api/v1/blogs/{session_id}/detail` for agent-run metrics.

### 3. Review the outline

`GET /api/v1/blogs/{session_id}/outline` returns the generated outline when it is ready for review.

Submit the outline decision with `POST /api/v1/blogs/{session_id}/outline/review`. The frontend route requires the complete `edited_outline` object, including when the action is `approve`.

```bash
curl -b cookies.txt \
  -H 'Content-Type: application/json' \
  -d '{
    "action": "approve",
    "edited_outline": {"title":"...","goal":"...","sections":[]}
  }' \
  http://localhost:8000/api/v1/blogs/42/outline/review
```

Use `"action":"revise"` and include `feedback_text` to continue with a changed outline or review feedback. The API queues the continuation asynchronously.

### 4. Review the final draft

`POST /api/v1/blogs/{session_id}/final-review` records the final decision:

```bash
curl -b cookies.txt \
  -H 'Content-Type: application/json' \
  -d '{"action":"approved"}' \
  http://localhost:8000/api/v1/blogs/42/final-review
```

Supported actions are `approved`, `revision_requested`, and `rejected`. `revision_requested` requires a non-empty `feedback_text`; feedback is not accepted for the other actions.

### 5. Read or export the completed blog

```bash
# Markdown content and sources
curl -b cookies.txt \
  http://localhost:8000/api/v1/blogs/42/content

# Export the latest completed version
curl -b cookies.txt -OJ \
  'http://localhost:8000/api/v1/blogs/42/export?format=pdf'
```

The content endpoint returns Markdown, title, word count, source metadata, and the session status. Export accepts `pdf` or `docx`; it returns `409` until the session is completed and `503` if document conversion is unavailable.

## Supporting endpoints

| Endpoint | Purpose |
| --- | --- |
| `GET /api/v1/health` | Basic health check. |
| `GET /api/v1/health/live` | Liveness probe. |
| `GET /api/v1/health/ready` | Dependency-readiness probe. |
| `GET /api/v1/blogs/` | Paginated session library with optional status and query filters. |
| `GET /api/v1/blogs/insights` | Blog-session insights for a selected day range. |
| `GET /api/v1/blogs/budget` | Current user's budget and daily quota view. |
| `GET /api/v1/blogs/{session_id}/versions/latest` | Latest saved blog version. |
| `GET /api/v1/tones` | Public catalog of available writing tones. |

## Error handling

The API uses normal HTTP status codes:

| Status | Meaning |
| --- | --- |
| `202` | Generation accepted for asynchronous work. |
| `400` | Invalid request content. |
| `401` | Missing or invalid authentication. |
| `402` | Budget is insufficient. |
| `404` | The session does not exist or is not owned by the caller. |
| `409` | The requested transition conflicts with the current session state. |
| `429` | The daily generation limit has been reached. |
| `503` | A requested export conversion is unavailable. |

For all remaining routes and exact request/response fields, use `/docs` or the checked-in Postman collection.
