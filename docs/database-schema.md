# Blogify AI Database Schema

## Overview

The repository contains **20 database tables** across two categories:

| Category | Tables | Description |
|----------|--------|-------------|
| **Legacy** | 3 | Original Phase 0 tables (users, blogs, cost_records) |
| **Canonical** | 17 | Phase 1+ tables for multi-tenant blog generation |

---

## 1. Legacy Tables (Phase 0)

### 1.1 users

Legacy user model for budget tracking.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | INTEGER | PK, AUTOINCREMENT | Primary key |
| `user_id` | VARCHAR(255) | UNIQUE, NOT NULL, INDEXED | Unique user identifier |
| `email` | VARCHAR(255) | NULLABLE | User email |
| `daily_budget_usd` | FLOAT | DEFAULT 1.0 | Daily budget in USD |
| `daily_blogs_limit` | INTEGER | DEFAULT 10 | Daily blog generation limit |
| `total_cost_usd` | FLOAT | DEFAULT 0.0 | Accumulated cost |
| `total_blogs_generated` | INTEGER | DEFAULT 0 | Total blogs generated |
| `created_at` | TIMESTAMP WITH TZ | DEFAULT now() | Creation timestamp |

**Relationships**:
- `blogs` → 1:M with `Blog`
- `cost_records` → 1:M with `CostRecord`

---

### 1.2 blogs

Generated blog record (legacy).

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | INTEGER | PK, AUTOINCREMENT | Primary key |
| `user_id` | VARCHAR(255) | FK → users.user_id, NOT NULL | Reference to user |
| `session_id` | VARCHAR(255) | UNIQUE, NOT NULL, INDEXED | Unique session identifier |
| `topic` | VARCHAR(500) | NOT NULL | Blog topic |
| `audience` | VARCHAR(255) | NULLABLE | Target audience |
| `title` | VARCHAR(255) | NULLABLE | Blog title |
| `content` | TEXT | NULLABLE | Blog content |
| `word_count` | INTEGER | DEFAULT 0 | Word count |
| `sources_count` | INTEGER | DEFAULT 0 | Number of sources |
| `status` | VARCHAR(50) | DEFAULT 'in_progress' | Blog status |
| `current_stage` | VARCHAR(50) | NULLABLE | Current pipeline stage |
| `stage_data` | JSONB | NULLABLE | Stage-specific data |
| `total_cost_usd` | FLOAT | DEFAULT 0.0 | Total cost in USD |
| `total_tokens` | INTEGER | DEFAULT 0 | Total tokens used |
| `created_at` | TIMESTAMP WITH TZ | DEFAULT now() | Creation timestamp |
| `completed_at` | TIMESTAMP WITH TZ | NULLABLE | Completion timestamp |

**Relationships**:
- `user` → M:1 with `User`
- `cost_records` → 1:M with `CostRecord`

---

### 1.3 cost_records

Cost tracking per agent invocation (legacy).

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | INTEGER | PK, AUTOINCREMENT | Primary key |
| `user_id` | VARCHAR(255) | FK → users.user_id, NOT NULL | Reference to user |
| `blog_id` | INTEGER | FK → blogs.id, NULLABLE | Optional reference to blog |
| `session_id` | VARCHAR(255) | NOT NULL, INDEXED | Session identifier |
| `agent_name` | VARCHAR(100) | NOT NULL | Agent that generated cost |
| `model_name` | VARCHAR(100) | NOT NULL | Model used |
| `prompt_tokens` | INTEGER | DEFAULT 0 | Prompt token count |
| `completion_tokens` | INTEGER | DEFAULT 0 | Completion token count |
| `total_tokens` | INTEGER | DEFAULT 0 | Total tokens |
| `cost_usd` | FLOAT | DEFAULT 0.0 | Cost in USD |
| `latency_ms` | INTEGER | NULLABLE | Latency in milliseconds |
| `success` | BOOLEAN | DEFAULT True | Whether invocation succeeded |
| `error_message` | TEXT | NULLABLE | Error message if failed |
| `created_at` | TIMESTAMP WITH TZ | DEFAULT now() | Creation timestamp |

**Relationships**:
- `user` → M:1 with `User`
- `blog` → M:1 with `Blog` (optional)

---

## 2. Canonical Tables (Phase 1+)

### 2.1 service_clients

Represents calling systems / deploy modes.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | BIGINT | PK, AUTOINCREMENT | Primary key |
| `client_key` | VARCHAR(128) | UNIQUE, NOT NULL, INDEXED | Client identifier key |
| `mode` | ENUM | NOT NULL | `standalone` / `blogify_service` |
| `name` | VARCHAR(255) | NOT NULL | Client name |
| `hashed_api_key` | VARCHAR(255) | NOT NULL | Hashed API key |
| `status` | ENUM | NOT NULL, DEFAULT `active` | `active` / `suspended` / `rotated` |
| `created_at` | TIMESTAMP WITH TZ | DEFAULT now() | Creation timestamp |
| `rotated_at` | TIMESTAMP WITH TZ | NULLABLE | Last key rotation timestamp |

**Relationships**:
- `tenants` → 1:M with `Tenant`
- `budget_policy` → 1:1 with `ServiceClientBudgetPolicy`

---

### 2.2 tenants

Budget and account boundary.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | BIGINT | PK, AUTOINCREMENT | Primary key |
| `service_client_id` | BIGINT | FK → service_clients.id, NOT NULL | Reference to service client |
| `external_tenant_id` | VARCHAR(255) | NULLABLE, INDEXED | External tenant identifier |
| `name` | VARCHAR(255) | NOT NULL | Tenant name |
| `plan_tier` | ENUM | NOT NULL, DEFAULT `free` | `free` / `pro` / `enterprise` |
| `status` | ENUM | NOT NULL, DEFAULT `active` | `active` / `suspended` / `cancelled` |
| `created_at` | TIMESTAMP WITH TZ | DEFAULT now() | Creation timestamp |

**Relationships**:
- `service_client` → M:1 with `ServiceClient`
- `end_users` → 1:M with `EndUser`
- `budget_policies` → 1:M with `BudgetPolicy`
- `blog_sessions` → 1:M with `BlogSession`

---

### 2.3 end_users

The actual budget-consuming user.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | BIGINT | PK, AUTOINCREMENT | Primary key |
| `tenant_id` | BIGINT | FK → tenants.id, NOT NULL | Reference to tenant |
| `external_user_id` | VARCHAR(255) | NOT NULL, INDEXED | External user identifier |
| `email` | VARCHAR(255) | NULLABLE | User email |
| `display_name` | VARCHAR(255) | NULLABLE | Display name |
| `status` | ENUM | NOT NULL, DEFAULT `active` | `active` / `suspended` |
| `created_at` | TIMESTAMP WITH TZ | DEFAULT now() | Creation timestamp |

**Unique Constraint**: `(tenant_id, external_user_id)` → `uq_tenant_user`

**Relationships**:
- `tenant` → M:1 with `Tenant`
- `budget_policies` → 1:M with `BudgetPolicy`
- `budget_ledger_entries` → 1:M with `BudgetLedgerEntry`
- `blog_sessions` → 1:M with `BlogSession`

---

### 2.4 auth_users

Local browser-authenticated user.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | BIGINT | PK, AUTOINCREMENT | Primary key |
| `email` | VARCHAR(255) | UNIQUE, NOT NULL, INDEXED | User email |
| `password_hash` | VARCHAR(512) | NOT NULL | Hashed password |
| `display_name` | VARCHAR(255) | NULLABLE | Display name |
| `is_active` | BOOLEAN | DEFAULT True | Whether user is active |
| `last_login_at` | TIMESTAMP WITH TZ | NULLABLE | Last login timestamp |
| `created_at` | TIMESTAMP WITH TZ | DEFAULT now() | Creation timestamp |
| `updated_at` | TIMESTAMP WITH TZ | DEFAULT now(), AUTOUPDATE | Last update timestamp |

**Relationships**:
- `notifications` → 1:M with `UserNotification`

---

### 2.5 budget_policies

Configured budget limits per scope (default / tenant / user override).

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | BIGINT | PK, AUTOINCREMENT | Primary key |
| `tenant_id` | BIGINT | FK → tenants.id, NULLABLE | Reference to tenant |
| `end_user_id` | BIGINT | FK → end_users.id, NULLABLE | Reference to end user |
| `scope` | ENUM | NOT NULL, DEFAULT `default` | `default` / `tenant` / `user_override` |
| `daily_cost_limit_usd` | FLOAT | DEFAULT 1.0 | Daily cost limit in USD |
| `daily_token_limit` | INTEGER | DEFAULT 50,000 | Daily token limit |
| `daily_blog_limit` | INTEGER | DEFAULT 5 | Daily blog limit |
| `per_session_cost_limit_usd` | FLOAT | DEFAULT 0.10 | Per-session cost limit |
| `per_session_token_limit` | INTEGER | DEFAULT 15,000 | Per-session token limit |
| `max_revision_iterations_per_session` | INTEGER | DEFAULT 3 | Max revision iterations |
| `max_concurrent_sessions` | INTEGER | DEFAULT 2 | Max concurrent sessions |
| `soft_stop_enabled` | BOOLEAN | DEFAULT False | Enable soft stop |
| `created_at` | TIMESTAMP WITH TZ | DEFAULT now() | Creation timestamp |
| `updated_at` | TIMESTAMP WITH TZ | DEFAULT now(), AUTOUPDATE | Last update timestamp |

**Relationships**:
- `tenant` → M:1 with `Tenant` (optional)
- `end_user` → M:1 with `EndUser` (optional)

---

### 2.6 service_client_budget_policies

Configured daily budget limit for a service client.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | BIGINT | PK, AUTOINCREMENT | Primary key |
| `service_client_id` | BIGINT | FK → service_clients.id, NOT NULL | Reference to service client |
| `daily_budget_limit_usd` | FLOAT | NOT NULL, DEFAULT 0.0 | Daily budget limit in USD |
| `currency_code` | VARCHAR(8) | NOT NULL, DEFAULT 'USD' | Currency code |
| `is_active` | BOOLEAN | NOT NULL, DEFAULT True | Whether policy is active |
| `created_at` | TIMESTAMP WITH TZ | DEFAULT now() | Creation timestamp |
| `updated_at` | TIMESTAMP WITH TZ | DEFAULT now(), AUTOUPDATE | Last update timestamp |

**Unique Constraint**: `(service_client_id)` → `uq_service_client_budget_policy`

**Relationships**:
- `service_client` → M:1 with `ServiceClient`

---

### 2.7 budget_ledger_entries

Canonical usage journal — immutable append-only record.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | BIGINT | PK, AUTOINCREMENT | Primary key |
| `tenant_id` | BIGINT | FK → tenants.id, NOT NULL | Reference to tenant |
| `end_user_id` | BIGINT | FK → end_users.id, NOT NULL | Reference to end user |
| `blog_session_id` | BIGINT | FK → blog_sessions.id, NULLABLE | Reference to blog session |
| `blog_version_id` | BIGINT | FK → blog_versions.id, NULLABLE | Reference to blog version |
| `agent_run_id` | BIGINT | FK → agent_runs.id, NULLABLE | Reference to agent run |
| `entry_type` | ENUM | NOT NULL | `reserve` / `commit` / `release` / `adjustment` / `refund` / `reject` |
| `resource_type` | ENUM | NOT NULL | `tokens` / `usd` / `blog_count` / `revision_count` |
| `quantity` | FLOAT | NOT NULL | Quantity of resource |
| `unit_cost_usd` | FLOAT | NULLABLE | Cost per unit |
| `metadata` | JSONB | NULLABLE | Additional metadata |
| `created_at` | TIMESTAMP WITH TZ | DEFAULT now() | Creation timestamp |

**Relationships**:
- `end_user` → M:1 with `EndUser`

---

### 2.8 blog_sessions

Canonical parent record for a blog generation request and its full lifecycle.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | BIGINT | PK, AUTOINCREMENT | Primary key |
| `tenant_id` | BIGINT | FK → tenants.id, NOT NULL | Reference to tenant |
| `end_user_id` | BIGINT | FK → end_users.id, NOT NULL | Reference to end user |
| `service_client_id` | BIGINT | FK → service_clients.id, NOT NULL | Reference to service client |
| `external_request_id` | VARCHAR(255) | NULLABLE, INDEXED | External request ID |
| `external_blog_id` | VARCHAR(255) | NULLABLE | External blog ID |
| `topic` | VARCHAR(500) | NOT NULL | Blog topic |
| `audience` | VARCHAR(255) | NULLABLE | Target audience |
| `tone` | VARCHAR(100) | NULLABLE | Writing tone |
| `status` | ENUM | NOT NULL, DEFAULT `queued`, INDEXED | Session status |
| `current_stage` | VARCHAR(80) | NULLABLE | Current pipeline stage |
| `iteration_count` | INTEGER | DEFAULT 0 | Number of iterations |
| `outline_data` | JSONB | NULLABLE | Generated outline |
| `outline_feedback` | TEXT | NULLABLE | Outline review feedback |
| `approved_research` | JSONB | NULLABLE | Approved research data |
| `research_review_deadline` | TIMESTAMP WITH TZ | NULLABLE | Research review deadline (48h) |
| `budget_reserved_usd` | FLOAT | DEFAULT 0.0 | Reserved budget in USD |
| `budget_reserved_tokens` | INTEGER | DEFAULT 0 | Reserved tokens |
| `budget_spent_usd` | FLOAT | DEFAULT 0.0 | Spent budget in USD |
| `budget_spent_tokens` | INTEGER | DEFAULT 0 | Spent tokens |
| `lease_version` | INTEGER | DEFAULT 0, NOT NULL | Lease version for reaper |
| `reap_count` | INTEGER | DEFAULT 0, NOT NULL | Number of reaps |
| `owned_by` | VARCHAR(100) | NULLABLE | Worker that owns the session |
| `claimed_at` | TIMESTAMP WITH TZ | NULLABLE | When session was claimed |
| `last_heartbeat_at` | TIMESTAMP WITH TZ | NULLABLE | Last heartbeat timestamp |
| `per_user_blog_number` | INTEGER | NOT NULL | Blog number for this user |
| `callback_url` | VARCHAR(1000) | NULLABLE | Webhook callback URL |
| `callback_enabled` | BOOLEAN | NOT NULL, DEFAULT True | Enable callback |
| `error_message` | TEXT | NULLABLE | Error message if failed |
| `created_at` | TIMESTAMP WITH TZ | DEFAULT now() | Creation timestamp |
| `updated_at` | TIMESTAMP WITH TZ | DEFAULT now(), AUTOUPDATE | Last update timestamp |
| `completed_at` | TIMESTAMP WITH TZ | NULLABLE | Completion timestamp |

**Indexes**:
- `status` (for reaper queries)
- `external_request_id`

**Relationships**:
- `tenant` → M:1 with `Tenant`
- `end_user` → M:1 with `EndUser`
- `versions` → 1:M with `BlogVersion` (ordered by version_number)
- `agent_runs` → 1:M with `AgentRun`

---

### 2.9 blog_versions

Every material output revision of a blog — the "final blog" is the latest approved version.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | BIGINT | PK, AUTOINCREMENT | Primary key |
| `blog_session_id` | BIGINT | FK → blog_sessions.id, NOT NULL, INDEXED | Reference to session |
| `version_number` | INTEGER | NOT NULL, DEFAULT 1 | Version number |
| `source_type` | ENUM | NOT NULL | `initial_generation` / `human_revision` / `chat_edit` / `manual_import` |
| `title` | VARCHAR(500) | NULLABLE | Blog title |
| `content_markdown` | TEXT | NULLABLE | Markdown content |
| `word_count` | INTEGER | DEFAULT 0 | Word count |
| `sources_count` | INTEGER | DEFAULT 0 | Number of sources |
| `editor_status` | ENUM | NOT NULL, DEFAULT `draft` | `draft` / `editor_approved` / `human_approved` / `human_rejected` |
| `created_by` | ENUM | NOT NULL, DEFAULT `system` | `system` / `human` / `chatbot` |
| `created_at` | TIMESTAMP WITH TZ | DEFAULT now() | Creation timestamp |

**Relationships**:
- `session` → M:1 with `BlogSession`
- `agent_runs` → 1:M with `AgentRun`
- `human_review_events` → 1:M with `HumanReviewEvent`

---

### 2.10 agent_runs

Structured metadata for each stage/agent execution.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | BIGINT | PK, AUTOINCREMENT | Primary key |
| `blog_session_id` | BIGINT | FK → blog_sessions.id, NOT NULL, INDEXED | Reference to session |
| `blog_version_id` | BIGINT | FK → blog_versions.id, NULLABLE | Reference to version |
| `parent_agent_run_id` | BIGINT | FK → agent_runs.id, NULLABLE | Parent agent run |
| `stage_name` | VARCHAR(80) | NOT NULL | Stage name (intent, outline, research, etc.) |
| `agent_name` | VARCHAR(100) | NOT NULL | Agent name |
| `model_name` | VARCHAR(100) | NOT NULL | Model used |
| `status` | ENUM | NOT NULL, DEFAULT `started` | `started` / `completed` / `failed` / `timed_out` / `cancelled` |
| `prompt_artifact_uri` | VARCHAR(1000) | NULLABLE | URI for prompt artifacts |
| `response_artifact_uri` | VARCHAR(1000) | NULLABLE | URI for response artifacts |
| `input_summary` | JSONB | NULLABLE | Input summary |
| `output_summary` | JSONB | NULLABLE | Output summary |
| `prompt_tokens` | INTEGER | DEFAULT 0 | Prompt token count |
| `completion_tokens` | INTEGER | DEFAULT 0 | Completion token count |
| `total_tokens` | INTEGER | DEFAULT 0 | Total tokens |
| `cost_usd` | FLOAT | DEFAULT 0.0 | Cost in USD |
| `latency_ms` | INTEGER | NULLABLE | Latency in milliseconds |
| `started_at` | TIMESTAMP WITH TZ | DEFAULT now() | Start timestamp |
| `completed_at` | TIMESTAMP WITH TZ | NULLABLE | Completion timestamp |
| `error_message` | TEXT | NULLABLE | Error message if failed |

**Relationships**:
- `session` → M:1 with `BlogSession`
- `blog_version` → M:1 with `BlogVersion` (optional)
- `ledger_entries` → 1:M with `BudgetLedgerEntry` (via primaryjoin)

---

### 2.11 human_review_events

HITL interactions — one record per reviewer action.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | BIGINT | PK, AUTOINCREMENT | Primary key |
| `blog_session_id` | BIGINT | FK → blog_sessions.id, NOT NULL, INDEXED | Reference to session |
| `blog_version_id` | BIGINT | FK → blog_versions.id, NOT NULL | Reference to version |
| `reviewer_user_id` | VARCHAR(255) | NOT NULL | Reviewer user ID |
| `action` | ENUM | NOT NULL | `approve` / `request_revision` / `reject` / `reopen` |
| `feedback_text` | TEXT | NULLABLE | Review feedback |
| `review_context` | JSONB | NULLABLE | Additional context |
| `created_at` | TIMESTAMP WITH TZ | DEFAULT now() | Creation timestamp |

**Relationships**:
- `blog_version` → M:1 with `BlogVersion`

---

### 2.12 export_jobs

Standalone export jobs — standalone mode only.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | BIGINT | PK, AUTOINCREMENT | Primary key |
| `blog_version_id` | BIGINT | FK → blog_versions.id, NOT NULL | Reference to version |
| `format` | ENUM | NOT NULL | `pdf` / `docx` / `markdown` |
| `status` | ENUM | NOT NULL, DEFAULT `pending` | `pending` / `processing` / `completed` / `failed` |
| `artifact_uri` | VARCHAR(1000) | NULLABLE | URI for exported artifact |
| `created_at` | TIMESTAMP WITH TZ | DEFAULT now() | Creation timestamp |
| `completed_at` | TIMESTAMP WITH TZ | NULLABLE | Completion timestamp |

---

### 2.13 user_notifications

Persistent in-app notification records for authenticated users.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | BIGINT | PK, AUTOINCREMENT | Primary key |
| `user_id` | BIGINT | FK → auth_users.id, NOT NULL, INDEXED | Reference to user |
| `type` | VARCHAR(80) | NOT NULL, INDEXED | Notification type |
| `title` | VARCHAR(255) | NOT NULL | Notification title |
| `message` | TEXT | NOT NULL | Notification message |
| `session_id` | BIGINT | FK → blog_sessions.id, NULLABLE, INDEXED | Related session |
| `action_url` | VARCHAR(500) | NULLABLE | Action URL |
| `is_read` | BOOLEAN | DEFAULT False, INDEXED | Read status |
| `read_at` | TIMESTAMP WITH TZ | NULLABLE | Read timestamp |
| `payload_json` | JSONB | NULLABLE | Additional payload |
| `created_at` | TIMESTAMP WITH TZ | DEFAULT now() | Creation timestamp |

**Relationships**:
- `user` → M:1 with `AuthUser`

---

## 3. Key Relationships Summary

| Parent Table | Child Table | Relationship Type |
|--------------|-------------|-------------------|
| `ServiceClient` | `Tenant` | 1:M |
| `Tenant` | `EndUser` | 1:M |
| `Tenant` | `BlogSession` | 1:M |
| `Tenant` | `BudgetPolicy` | 1:M |
| `Tenant` | `BudgetLedgerEntry` | 1:M |
| `EndUser` | `BlogSession` | 1:M |
| `EndUser` | `BudgetPolicy` | 1:M |
| `EndUser` | `BudgetLedgerEntry` | 1:M |
| `BlogSession` | `BlogVersion` | 1:M |
| `BlogSession` | `AgentRun` | 1:M |
| `BlogVersion` | `AgentRun` | 1:M (optional) |
| `BlogVersion` | `HumanReviewEvent` | 1:M |
| `AuthUser` | `UserNotification` | 1:M |
| `ServiceClient` | `ServiceClientBudgetPolicy` | 1:1 |

---

## 4. Enumerations

| Enum Name | Values |
|-----------|--------|
| `ClientMode` | `standalone`, `blogify_service` |
| `ClientStatus` | `active`, `suspended`, `rotated` |
| `TenantPlan` | `free`, `pro`, `enterprise` |
| `TenantStatus` | `active`, `suspended`, `cancelled` |
| `EndUserStatus` | `active`, `suspended` |
| `BudgetPolicyScope` | `default`, `tenant`, `user_override` |
| `LedgerEntryType` | `reserve`, `commit`, `release`, `adjustment`, `refund`, `reject` |
| `LedgerResourceType` | `tokens`, `usd`, `blog_count`, `revision_count` |
| `BlogSessionStatus` | `queued`, `processing`, `awaiting_outline_review`, `awaiting_human_review`, `awaiting_research_review`, `revision_requested`, `completed`, `failed`, `cancelled`, `budget_exhausted` |
| `BlogVersionSource` | `initial_generation`, `human_revision`, `chat_edit`, `manual_import` |
| `BlogEditorStatus` | `draft`, `editor_approved`, `human_approved`, `human_rejected` |
| `BlogCreatedBy` | `system`, `human`, `chatbot` |
| `AgentRunStatus` | `started`, `completed`, `failed`, `timed_out`, `cancelled` |
| `HumanReviewAction` | `approve`, `request_revision`, `reject`, `reopen` |
| `ExportFormat` | `pdf`, `docx`, `markdown` |
| `ExportStatus` | `pending`, `processing`, `completed`, `failed` |

---

## 5. Indexes

| Table | Index Columns |
|-------|---------------|
| `users` | `user_id` (UNIQUE) |
| `blogs` | `user_id`, `session_id` (UNIQUE) |
| `cost_records` | `user_id`, `blog_id`, `session_id` |
| `service_clients` | `client_key` (UNIQUE) |
| `tenants` | `external_tenant_id` |
| `end_users` | `(tenant_id, external_user_id)` (UNIQUE) |
| `auth_users` | `email` (UNIQUE) |
| `blog_sessions` | `external_request_id`, `status` |
| `blog_versions` | `blog_session_id` |
| `agent_runs` | `blog_session_id` |
| `human_review_events` | `blog_session_id` |
| `user_notifications` | `user_id`, `type`, `session_id`, `is_read` |

---

*Document generated from orm_models.py - Last updated: 2026-04-29*