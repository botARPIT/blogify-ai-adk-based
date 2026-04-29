# Upstream Service Deployment Guide

This guide explains how to provision a service-client API key in Blogify AI and
wire another backend to call Blogify AI as an internal blog-generation service.

## What the upstream backend should call

Use the internal service routes only:

- `POST /internal/ai/blogs`
- `GET /internal/ai/blogs/{session_id}`
- `GET /internal/ai/blogs/{session_id}/versions/latest`
- `GET /internal/ai/blogs/{session_id}/content`
- `GET /internal/ai/blogs/{session_id}/detail`
- `POST /internal/ai/blogs/{session_id}/outline/review`
- `POST /internal/ai/blogs/{session_id}/review`

All requests must include:

- `X-Internal-Api-Key`
- `Idempotency-Key` for mutating requests

## 1. Enable the admin API

The Blogify AI deployment must set:

- `ENABLE_ADMIN_ROUTES=true`
- `ADMIN_API_KEY=<strong random secret>`

The admin API is used only by operators to create, rotate, suspend, activate,
and budget service clients.

## 2. Provision a service client

You can either call the admin API directly or use the helper script in this
repo.

### Helper script

```bash
cd backend
source venv/bin/activate
python scripts/provision_service_client.py create \
  --base-url https://blogify-ai.internal \
  --admin-api-key "$BLOGIFY_AI_ADMIN_KEY" \
  --client-key upstream-app-dev \
  --name "Upstream App Dev" \
  --daily-budget-limit-usd 5
```

This will:

1. create the service client with `mode=blogify_service`
2. set its daily service budget
3. print the generated raw API key once

### Direct admin API calls

Create:

```bash
curl -X POST "$BLOGIFY_AI_BASE_URL/internal/admin/service-clients" \
  -H "Content-Type: application/json" \
  -H "X-Admin-Api-Key: $BLOGIFY_AI_ADMIN_KEY" \
  -d '{
    "client_key": "upstream-app-dev",
    "name": "Upstream App Dev",
    "mode": "blogify_service"
  }'
```

Set budget:

```bash
curl -X POST "$BLOGIFY_AI_BASE_URL/internal/admin/service-clients/upstream-app-dev/budget" \
  -H "Content-Type: application/json" \
  -H "X-Admin-Api-Key: $BLOGIFY_AI_ADMIN_KEY" \
  -d '{
    "daily_budget_limit_usd": 5.0
  }'
```

## 3. Store the raw API key in the upstream backend

The upstream backend should store:

- `BLOGIFY_AI_BASE_URL`
- `BLOGIFY_AI_API_KEY`

Recommended storage:

- deployment secret store
- cloud secret manager
- environment variables injected by the runtime

Do not store the raw key in:

- frontend code
- browser storage
- application database rows
- repo-tracked `.env` files
- logs

## 4. Use a dedicated upstream client wrapper

This repo includes a reference wrapper:

- [backend/examples/upstream_ai_service_client.py](./backend/examples/upstream_ai_service_client.py)

The upstream backend should centralize all Blogify AI requests in one module so
that:

- `X-Internal-Api-Key` is attached consistently
- `Idempotency-Key` is attached consistently
- request timeouts are normalized
- error handling is normalized

Recommended methods:

- `generate_blog(...)`
- `get_blog_session(...)`
- `get_latest_version(...)`
- `get_blog_content(...)`
- `get_blog_detail(...)`
- `submit_outline_review(...)`
- `submit_human_review(...)`

## 5. Generation request contract

Call:

- `POST /internal/ai/blogs`

Headers:

- `Content-Type: application/json`
- `X-Internal-Api-Key: <raw service client api key>`
- `Idempotency-Key: <stable logical request key>`

Body:

```json
{
  "topic": "How to build CI/CD pipelines for regulated biotech software",
  "audience": "engineering leaders",
  "tone": "practical",
  "tenant_id": "workspace_123",
  "end_user_id": "user_456",
  "request_id": "bloggen_20260331_abc123"
}
```

Recommended default:

- use the same value for `request_id` and `Idempotency-Key`

Persist upstream mapping:

- `upstream_blog_id`
- `blogify_session_id`
- `blogify_request_id`
- `blogify_status`

## 6. Polling model

The upstream backend should poll:

- `GET /internal/ai/blogs/{session_id}`

until the session reaches one of:

- `awaiting_outline_review`
- `awaiting_human_review`
- `completed`
- `failed`
- `budget_exhausted`
- `awaiting_budget_resolution`

Polling is the recommended initial integration model. The current system is
designed around session-state polling and explicit follow-up actions.

Important:

- `GET /internal/ai/blogs/{session_id}` is a status endpoint only
- it does **not** return the generated blog body
- once `current_version_number` becomes non-null or the session reaches
  `awaiting_human_review` / `completed`, the upstream backend should fetch:
  - `GET /internal/ai/blogs/{session_id}/versions/latest` for version metadata
  - `GET /internal/ai/blogs/{session_id}/content` for the actual generated blog
  - `GET /internal/ai/blogs/{session_id}/detail` for the aggregate debugging view

## 7. Outline review contract

Call:

- `POST /internal/ai/blogs/{session_id}/outline/review`

Headers:

- `X-Internal-Api-Key`
- `Idempotency-Key`

Approve:

```json
{
  "action": "approve"
}
```

Revise:

```json
{
  "action": "revise",
  "feedback_text": "Shorten the introduction and make the regulatory examples more concrete.",
  "edited_outline": {
    "title": "Biotech CI/CD in Regulated Environments",
    "sections": [
      {
        "id": "intro",
        "heading": "Why Regulated CI/CD Is Different",
        "goal": "Set the compliance context",
        "target_words": 140
      },
      {
        "id": "controls",
        "heading": "Core Validation Controls",
        "goal": "Explain validation expectations",
        "target_words": 220
      },
      {
        "id": "implementation",
        "heading": "Implementation Patterns",
        "goal": "Give practical implementation advice",
        "target_words": 220
      }
    ],
    "estimated_total_words": 700
  }
}
```

## 8. Final review / revision contract

Call:

- `POST /internal/ai/blogs/{session_id}/review?version_id=<version_id>`

Headers:

- `X-Internal-Api-Key`
- `Idempotency-Key`

Approve:

```json
{
  "action": "approve"
}
```

Reject:

```json
{
  "action": "reject",
  "feedback_text": "The article does not meet quality standards."
}
```

Request revision:

```json
{
  "action": "request_revision",
  "feedback_text": "Shorten the intro and add a more concrete compliance checklist."
}
```

The upstream backend must persist the latest `version_id` for each reviewable
session.

Recommended review/read sequence:

1. poll `GET /internal/ai/blogs/{session_id}`
2. when `current_version_number` is non-null, call `GET /internal/ai/blogs/{session_id}/versions/latest`
3. use the returned `version_id` for review actions
4. call `GET /internal/ai/blogs/{session_id}/content` whenever the upstream app needs the readable blog body

## 9. Error handling contract

### `401`

Meaning:

- invalid API key
- suspended service client
- wrong client mode
- missing `X-Internal-Api-Key`

Upstream behavior:

- log an operational alert
- do not retry automatically
- treat as a credential/configuration incident

### `402`

Meaning:

- service-client budget exhausted
- user daily budget exhausted
- user session budget exhausted
- revision budget exhausted

Upstream behavior:

- surface as a business failure
- do not auto-retry immediately
- preserve response detail for diagnostics

### `409`

Meaning:

- duplicate in-flight request
- or same idempotency key with a different payload

Upstream behavior:

- if retry of the same logical action, poll the existing session state
- if payload mismatch, treat as caller bug

### `503`

Meaning:

- queue unavailable
- queue full

Upstream behavior:

- retry safely with the same `Idempotency-Key`

## 10. Rotation and suspension

Rotate:

```bash
python scripts/provision_service_client.py rotate \
  --base-url "$BLOGIFY_AI_BASE_URL" \
  --admin-api-key "$BLOGIFY_AI_ADMIN_KEY" \
  --client-key upstream-app-dev
```

Suspend:

```bash
python scripts/provision_service_client.py suspend \
  --base-url "$BLOGIFY_AI_BASE_URL" \
  --admin-api-key "$BLOGIFY_AI_ADMIN_KEY" \
  --client-key upstream-app-dev
```

Activate:

```bash
python scripts/provision_service_client.py activate \
  --base-url "$BLOGIFY_AI_BASE_URL" \
  --admin-api-key "$BLOGIFY_AI_ADMIN_KEY" \
  --client-key upstream-app-dev
```

Recommended rotation procedure:

1. rotate key in Blogify AI
2. update upstream backend secret store
3. redeploy or reload upstream backend
4. run one smoke generation request

## 11. Minimum upstream smoke tests

- create a service client successfully
- set service budget successfully
- generate one blog successfully
- poll queued and processing states
- approve one outline
- request one revision
- approve final output
- retry one generation request with the same idempotency key
- confirm a suspended key returns `401`

## 12. Final operational assumptions

- API keys are operator-managed, not self-served
- one service client should exist per environment
- service budgets must be configured explicitly per environment
- the integration target is the internal blog-generation service, not a chatbot
