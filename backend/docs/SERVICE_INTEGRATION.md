# Blogify AI — Service Integration Guide

> How to use Blogify AI as a downstream service from your own backend.

## Table of Contents

- [Overview](#overview)
- [Prerequisites](#prerequisites)
- [Step 1: Generate an API Key](#step-1-generate-an-api-key)
- [Step 2: Set a Budget](#step-2-set-a-budget)
- [Step 3: Generate a Blog](#step-3-generate-a-blog)
- [Step 4: Poll for Status](#step-4-poll-for-status)
- [Step 5: Review the Outline (HITL)](#step-5-review-the-outline-hitl)
- [Step 6: Get the Final Content](#step-6-get-the-final-content)
- [Step 7: Review the Final Draft (Optional)](#step-7-review-the-final-draft-optional)
- [API Key Management](#api-key-management)
- [Budget Monitoring](#budget-monitoring)
- [Webhook Callbacks](#webhook-callbacks)
- [Error Handling](#error-handling)
- [Complete Flow Diagram](#complete-flow-diagram)
- [API Reference Summary](#api-reference-summary)

---

## Overview

Blogify AI exposes a **service-to-service internal API** that lets any backend trigger AI blog
generation on behalf of its users. The system provides:

- **Multi-tenant isolation** — each service client gets its own identity namespace
- **Budget enforcement** — daily spend limits at both the service-client and per-user level
- **Human-in-the-loop (HITL)** — outline review + final draft review before completion
- **Rate limiting** — per-client request throttling
- **Idempotency** — duplicate requests with the same `request_id` return cached results

### Architecture

```
Your Backend                    Blogify AI Service
    │                                  │
    │  POST /internal/ai/blogs         │
    │  X-Internal-Api-Key: <key>   ──► │  ← validates key, resolves identity
    │                                  │  ← checks budget, enqueues generation
    │  ◄── { session_id, status }      │
    │                                  │
    │  GET /internal/ai/blogs/{id}     │
    │  (poll for status)           ──► │  ← returns current stage
    │                                  │
    │  GET .../outline                 │
    │  (when status = outline_review)──►│  ← returns editable outline
    │                                  │
    │  POST .../outline/review         │
    │  { action: "approve" }       ──► │  ← resumes generation
    │                                  │
    │  GET .../content                 │
    │  (when status = completed)   ──► │  ← returns final blog content
```

---

## Prerequisites

| Requirement | Details |
|-------------|---------|
| Blogify AI service running | Local: `python -m src.workers.blog_worker` or deployed on EC2/Cloud |
| Base URL known | e.g., `http://localhost:8000` or `https://ai.yourdomain.com` |
| Admin API key set | `ADMIN_API_KEY` env var in the AI service's `.env` |
| Admin routes enabled | `ENABLE_ADMIN_ROUTES=true` in `.env` |
| PostgreSQL running | Required for session/budget/identity persistence |
| Redis running | Required for rate limiting and session state |

---

## Step 1: Generate an API Key

Use the **Admin API** to create a service client. This is a one-time setup.

```bash
curl -X POST http://localhost:8000/internal/admin/service-clients \
  -H "Content-Type: application/json" \
  -H "X-Admin-Api-Key: YOUR_ADMIN_API_KEY" \
  -d '{
    "client_key": "blogify-main-app",
    "name": "Blogify Main Application",
    "mode": "blogify_service"
  }'
```

### Response

```json
{
  "client_key": "blogify-main-app",
  "name": "Blogify Main Application",
  "mode": "blogify_service",
  "status": "active",
  "created_at": "2026-03-31T15:00:00Z",
  "rotated_at": null,
  "api_key": "XaBcD1234...randomTokenUrlSafe32bytes"
}
```

> **⚠️ IMPORTANT**: The `api_key` field is returned **only once** during creation. Store it
> securely (e.g., in your backend's environment variables as `BLOGIFY_AI_API_KEY`). The service
> stores only a SHA-256 hash — the raw key cannot be recovered.

### Parameters

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `client_key` | string | ✅ | Unique identifier (3-128 chars). Use something like `your-app-name` |
| `name` | string | ✅ | Human-readable name (3-255 chars) |
| `mode` | enum | ✅ | Must be `"blogify_service"` for service-to-service integration |

---

## Step 2: Set a Budget

Set a daily spending limit for your service client.

```bash
curl -X POST http://localhost:8000/internal/admin/service-clients/blogify-main-app/budget \
  -H "Content-Type: application/json" \
  -H "X-Admin-Api-Key: YOUR_ADMIN_API_KEY" \
  -d '{
    "daily_budget_limit_usd": 10.00
  }'
```

### Response

```json
{
  "daily_budget_limit_usd": 10.0,
  "budget_window": "daily",
  "currently_exhausted": false,
  "reset_at": "2026-04-01T00:00:00Z",
  "daily_spent_usd": 0.0
}
```

> The budget resets at midnight UTC daily. If the budget is exhausted, all generation
> requests return `402 Payment Required` until the next window.

---

## Step 3: Generate a Blog

From your backend, call the internal generation endpoint:

```bash
curl -X POST http://localhost:8000/internal/ai/blogs \
  -H "Content-Type: application/json" \
  -H "X-Internal-Api-Key: YOUR_SERVICE_API_KEY" \
  -d '{
    "topic": "How to Build Scalable Microservices with Python",
    "audience": "backend developers with 2-3 years experience",
    "tone": "technical but approachable",
    "tenant_id": "your-org-id",
    "end_user_id": "user-123",
    "request_id": "req-abc-unique-idempotency-key",
    "callback_url": "https://your-backend.com/webhooks/blogify-ai"
  }'
```

### Response (202 Accepted)

```json
{
  "session_id": "42",
  "status": "queued",
  "message": "Blog generation queued.",
  "budget_reserved_usd": 0.05
}
```

### Parameters

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `topic` | string | ✅ | Blog topic (10-500 chars) |
| `audience` | string | ❌ | Target audience description |
| `tone` | string | ❌ | Writing tone/style |
| `tenant_id` | string | ✅ | Your org/workspace ID (auto-creates on first call) |
| `end_user_id` | string | ✅ | Your user's ID (auto-creates on first call) |
| `request_id` | string | ✅ | Idempotency key — same key returns cached result |
| `external_blog_id` | string | ❌ | Your blog record ID (for reference linking) |
| `callback_url` | string | ❌ | URL for webhook callbacks on state transitions |

> **Identity auto-provisioning**: On the first request for a new `tenant_id` or `end_user_id`,
> the system automatically creates the tenant and user records. No separate registration needed.

---

## Step 4: Poll for Status

Poll the session endpoint to track generation progress:

```bash
curl http://localhost:8000/internal/ai/blogs/42 \
  -H "X-Internal-Api-Key: YOUR_SERVICE_API_KEY"
```

### Response

```json
{
  "session_id": "42",
  "status": "outline_review",
  "current_stage": "outline",
  "iteration_count": 0,
  "topic": "How to Build Scalable Microservices with Python",
  "requires_human_review": true,
  "budget_spent_usd": 0.002,
  "budget_spent_tokens": 1500,
  "current_version_number": null
}
```

### Status Lifecycle

```
queued → processing → outline_review → generating → completed
                                  ↗                    ↗
                        (if revised)          (if review approved)

At any point: → failed | budget_exhausted
```

| Status | Meaning | Your Action |
|--------|---------|-------------|
| `queued` | Waiting in generation queue | Poll again (3-5s interval) |
| `processing` | AI agents running (intent → research → outline) | Poll again |
| `outline_review` | Outline ready for human review | Fetch outline (Step 5) |
| `generating` | Outline approved, generating final content | Poll again |
| `human_review` | Final draft ready for review | Fetch content (Step 6) |
| `completed` | Final content available | Fetch content (Step 6) |
| `failed` | Generation failed | Check error, optionally retry |
| `budget_exhausted` | User/client budget exceeded | Wait for budget reset |

**Recommended polling**: 3s interval while `queued`/`processing`/`generating`, stop when
`outline_review`, `human_review`, `completed`, or `failed`.

---

## Step 5: Review the Outline (HITL)

When status becomes `outline_review`, fetch and review the generated outline:

### 5a. Fetch the Outline

```bash
curl http://localhost:8000/internal/ai/blogs/42/outline \
  -H "X-Internal-Api-Key: YOUR_SERVICE_API_KEY"
```

```json
{
  "session_id": 42,
  "status": "outline_review",
  "current_stage": "outline",
  "topic": "How to Build Scalable Microservices with Python",
  "audience": "backend developers with 2-3 years experience",
  "feedback_text": null,
  "outline": {
    "title": "Building Scalable Microservices with Python: A Practical Guide",
    "sections": [
      {
        "id": "s1",
        "heading": "Why Microservices?",
        "goal": "Explain the benefits of microservices architecture",
        "target_words": 200
      },
      {
        "id": "s2",
        "heading": "Choosing the Right Framework",
        "goal": "Compare FastAPI, Flask, and Django for microservices",
        "target_words": 250
      }
    ],
    "estimated_total_words": 1200
  }
}
```

### 5b. Approve or Revise

**Option A — Approve as-is:**

```bash
curl -X POST http://localhost:8000/internal/ai/blogs/42/outline/review \
  -H "Content-Type: application/json" \
  -H "X-Internal-Api-Key: YOUR_SERVICE_API_KEY" \
  -d '{
    "action": "approve"
  }'
```

**Option B — Approve with modifications:**

```bash
curl -X POST http://localhost:8000/internal/ai/blogs/42/outline/review \
  -H "Content-Type: application/json" \
  -H "X-Internal-Api-Key: YOUR_SERVICE_API_KEY" \
  -d '{
    "action": "revise",
    "feedback_text": "Add a section about testing strategies",
    "edited_outline": {
      "title": "Building Scalable Microservices with Python",
      "sections": [
        { "id": "s1", "heading": "Why Microservices?", "goal": "...", "target_words": 200 },
        { "id": "s2", "heading": "Choosing the Right Framework", "goal": "...", "target_words": 250 },
        { "id": "s3", "heading": "Testing Strategies", "goal": "Cover unit, integration, and contract testing", "target_words": 200 }
      ],
      "estimated_total_words": 1400
    }
  }'
```

After approval, the session status moves to `generating` and AI writes the full blog.
Resume polling (Step 4).

---

## Step 6: Get the Final Content

When status becomes `completed` (or `human_review`), fetch the generated content:

```bash
curl http://localhost:8000/internal/ai/blogs/42/content \
  -H "X-Internal-Api-Key: YOUR_SERVICE_API_KEY"
```

```json
{
  "session_id": 42,
  "version_id": 1,
  "title": "Building Scalable Microservices with Python: A Practical Guide",
  "content_markdown": "# Building Scalable Microservices with Python\n\n...",
  "word_count": 1350,
  "sources_count": 5,
  "topic": "How to Build Scalable Microservices with Python",
  "audience": "backend developers with 2-3 years experience",
  "status": "completed"
}
```

The `content_markdown` field contains the complete blog in Markdown format, ready to
render or convert to HTML in your application.

---

## Step 7: Review the Final Draft (Optional)

If your workflow requires human approval of the final draft before marking it complete:

```bash
curl -X POST "http://localhost:8000/internal/ai/blogs/42/review?version_id=1" \
  -H "Content-Type: application/json" \
  -H "X-Internal-Api-Key: YOUR_SERVICE_API_KEY" \
  -d '{
    "action": "approve",
    "reviewer_user_id": "user-123"
  }'
```

Available actions:

| Action | Effect |
|--------|--------|
| `approve` | Marks the blog as approved and complete |
| `request_revision` | Triggers a revision loop (requires `feedback_text`) |
| `reject` | Marks the blog as rejected |

---

## API Key Management

All management endpoints require `X-Admin-Api-Key`.

### List Service Clients

```bash
curl http://localhost:8000/internal/admin/service-clients \
  -H "X-Admin-Api-Key: YOUR_ADMIN_API_KEY"
```

### Rotate API Key

```bash
curl -X POST http://localhost:8000/internal/admin/service-clients/blogify-main-app/rotate \
  -H "X-Admin-Api-Key: YOUR_ADMIN_API_KEY"
```

Returns the new API key (old key is immediately invalidated).

### Suspend / Activate Client

```bash
# Suspend (all requests will return 401)
curl -X POST http://localhost:8000/internal/admin/service-clients/blogify-main-app/suspend \
  -H "X-Admin-Api-Key: YOUR_ADMIN_API_KEY"

# Re-activate
curl -X POST http://localhost:8000/internal/admin/service-clients/blogify-main-app/activate \
  -H "X-Admin-Api-Key: YOUR_ADMIN_API_KEY"
```

---

## Budget Monitoring

### Check Per-User Budget

```bash
curl "http://localhost:8000/internal/ai/budgets/user-123?tenant_id=your-org-id" \
  -H "X-Internal-Api-Key: YOUR_SERVICE_API_KEY"
```

```json
{
  "end_user_id": 5,
  "tenant_id": 2,
  "daily_spent_usd": 0.08,
  "daily_spent_tokens": 6200,
  "daily_limit_usd": 1.0,
  "daily_limit_tokens": 50000,
  "active_sessions": 1,
  "max_concurrent_sessions": 3,
  "remaining_revision_iterations": 2,
  "soft_stop_enabled": false
}
```

### Check Service-Client Budget

```bash
curl http://localhost:8000/internal/admin/service-clients/blogify-main-app/budget \
  -H "X-Admin-Api-Key: YOUR_ADMIN_API_KEY"
```

---

## Webhook Callbacks

If you provide a `callback_url` when starting generation, the service will POST webhook
events on every state transition:

```json
{
  "event_type": "blog.session.completed",
  "session_id": 42,
  "tenant_id": 2,
  "end_user_id": 5,
  "status": "completed",
  "current_stage": "editor_review",
  "current_version_number": 1,
  "budget_spent_usd": 0.04,
  "budget_spent_tokens": 4200,
  "remaining_revision_iterations": 2,
  "requires_human_review": false,
  "payload": null,
  "occurred_at": "2026-03-31T15:05:23Z"
}
```

### Event Types

| Event | When |
|-------|------|
| `blog.session.queued` | Generation request accepted |
| `blog.session.processing` | AI agents started |
| `blog.review.required` | Outline or draft ready for review |
| `blog.version.created` | New blog version generated |
| `blog.session.completed` | Final content available |
| `blog.session.failed` | Generation failed |
| `blog.session.budget_exhausted` | Budget limit hit |

---

## Error Handling

| HTTP Status | Meaning | Actionable Fix |
|------------|---------|----------------|
| `401` | Invalid or missing API key | Check `X-Internal-Api-Key` header |
| `402` | Budget exhausted | Wait for daily reset or increase budget |
| `404` | Session not found | Verify `session_id` is correct |
| `409` | Duplicate `client_key` | Use a different key or existing one |
| `422` | Validation error (bad input) | Check request body matches schema |
| `429` | Rate limited | Back off and retry after `Retry-After` |
| `500` | Internal server error | Check service logs |

---

## Complete Flow Diagram

```
┌─────────────────────────────────────────────────────────┐
│                    ONE-TIME SETUP                        │
│                                                         │
│  1. POST /internal/admin/service-clients                │
│     → Get API key                                       │
│  2. POST /internal/admin/service-clients/{key}/budget   │
│     → Set daily spending limit                          │
└──────────────────────────┬──────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────┐
│                  PER-BLOG GENERATION                     │
│                                                         │
│  3. POST /internal/ai/blogs                             │
│     → { session_id: 42 }                                │
│                                                         │
│  4. GET /internal/ai/blogs/42  (poll 3s)                │
│     → status: queued → processing → outline_review      │
│                                                         │
│  5. GET /internal/ai/blogs/42/outline                   │
│     → Show outline to user for review                   │
│                                                         │
│  6. POST /internal/ai/blogs/42/outline/review           │
│     → { action: "approve" }                             │
│                                                         │
│  7. GET /internal/ai/blogs/42  (resume polling)         │
│     → status: generating → completed                    │
│                                                         │
│  8. GET /internal/ai/blogs/42/content                   │
│     → Get final blog in Markdown                        │
└─────────────────────────────────────────────────────────┘
```

---

## API Reference Summary

### Admin Endpoints (`X-Admin-Api-Key` required)

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/internal/admin/service-clients` | Create a service client |
| `GET` | `/internal/admin/service-clients` | List all service clients |
| `GET` | `/internal/admin/service-clients/{key}` | Get client details |
| `POST` | `/internal/admin/service-clients/{key}/rotate` | Rotate API key |
| `POST` | `/internal/admin/service-clients/{key}/suspend` | Suspend client |
| `POST` | `/internal/admin/service-clients/{key}/activate` | Re-activate client |
| `GET` | `/internal/admin/service-clients/{key}/budget` | Check client budget |
| `POST` | `/internal/admin/service-clients/{key}/budget` | Set budget limit |

### Service Endpoints (`X-Internal-Api-Key` required)

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/internal/ai/blogs` | Start blog generation |
| `GET` | `/internal/ai/blogs/{session_id}` | Get session status |
| `GET` | `/internal/ai/blogs/{session_id}/outline` | Get outline for review |
| `POST` | `/internal/ai/blogs/{session_id}/outline/review` | Submit outline decision |
| `GET` | `/internal/ai/blogs/{session_id}/content` | Get final blog content |
| `GET` | `/internal/ai/blogs/{session_id}/detail` | Get full session detail |
| `GET` | `/internal/ai/blogs/{session_id}/versions/latest` | Get latest version |
| `POST` | `/internal/ai/blogs/{session_id}/review` | Submit final review |
| `GET` | `/internal/ai/budgets/{end_user_id}` | Get user budget snapshot |

### Interactive API Docs

When the service is running, view the full OpenAPI docs at:
- **Swagger UI**: `http://localhost:8000/docs`
- **ReDoc**: `http://localhost:8000/redoc`
- **Raw OpenAPI spec**: `http://localhost:8000/openapi.json`
