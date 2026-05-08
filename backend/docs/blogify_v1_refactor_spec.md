# Blogify AI — V1 Refactor Specification
## Agent Prompt: Complete Codebase Rebuild

---

## CONTEXT FOR THE AGENT

You are refactoring an AI-generated blog generation backend. The existing codebase is structurally broken: business logic lives inside route handlers, there are two competing pipeline files, three competing repository patterns, and dead code throughout. You are NOT incrementally patching it. You are rebuilding the non-agent layer from scratch using the specifications below as your single source of truth.

### What you MUST NOT touch
These files are correct and complete. Do not modify them under any circumstances:
- `src/agents/pipeline.py` — ADK-native pipeline with HITL gate (formerly pipeline_v2)
- `src/agents/intent_agent.py`
- `src/agents/outline_agent.py`
- `src/agents/research_agent.py`
- `src/agents/writer_agent.py`
- `src/agents/editor_agent.py`
- `src/core/session_store.py` — RedisSessionService (ADK state backend)
- `src/core/sanitization.py`
- `src/core/redis_pool.py`
- `src/config/` — all config files, read but do not modify
- `src/monitoring/` — metrics and tracing, read but do not modify

### What you MUST delete entirely
These files are dead code or superseded. Delete them before writing any new code:
- `src/agents/pipeline_v2.py` — renamed to pipeline.py already
- `src/guards/budget_guard.py`
- `src/controllers/blog_controller.py`
- `src/controllers/chat_controller.py`
- `src/models/repository.py` — old monolith DatabaseRepository
- `src/services/chat_service.py`
- `src/services/adapter_auth_service.py`
- `src/services/artifact_storage_service.py`
- `src/services/service_client_service.py`
- `src/services/service_client_budget_service.py`
- `src/core/saga_state_machine.py`
- `src/core/compensation.py`
- `src/core/backpressure.py`
- `src/core/webhook_emitter.py`
- `src/api/routes/admin_service_clients.py`
- `src/agents/chatbot_agent.py`
- `src/agents/intent_clarification_loop.py`
- `src/agents/llm_judge_agent.py`
- `src/agents/writer_editor_loop.py`

### What you ARE building
Every file listed in the TARGET FILE STRUCTURE section below. Write each file completely. No stubs, no TODOs, no placeholder implementations.

---

## ARCHITECTURAL RULES — NON-NEGOTIABLE

These rules apply to every file you write:

**Rule 1 — One repository pattern only.**
All database access uses individual repository classes injected via FastAPI `Depends()` or passed explicitly as constructor arguments. The pattern is:
```python
async def route_handler(session: AsyncSession = Depends(get_db_session)):
    repo = BlogSessionRepository(session)
    result = await repo.get_by_id(session_id)
```
Never instantiate a session inside a service method. Never use `db_repository` (the old monolith). Never use `async with engine.begin()` inside service classes.

**Rule 2 — Routes are thin.**
Route handlers do three things only: validate input (via Pydantic), call one service method, return the result. No business logic, no direct repo access, no DB imports in route files.

**Rule 3 — Services own business logic, not state.**
Service classes take repositories as constructor arguments. They contain business logic. They do not open DB connections. They do not import FastAPI.

**Rule 4 — Workers own their DB session lifecycle.**
`blog_worker.py` creates one `AsyncSession` per job, passes it to the executor, closes it when done. The session is never shared across jobs.

**Rule 5 — All constants in config.**
Model names, token estimates, USD prices per token, budget limits — all live in `src/config/budget_config.py`. Services import from config. Config does not import from services.

**Rule 6 — No `user_id = "anonymous"`.**
The `user_id` passed to `run_pipeline()` must always be the actual authenticated user's ID as a string. Derive it from the `AuthUser.id` field. If the user_id is unavailable, raise an exception — do not default to "anonymous".

---

## DATABASE SCHEMA

Write a single Alembic migration: `alembic/versions/100_v1_schema.py`

This migration replaces all previous migrations. It creates the following tables from scratch. Do not reference any previous migration as a dependency (set `down_revision = None`).

### Table: `auth_users`
```sql
CREATE TABLE auth_users (
    id          SERIAL PRIMARY KEY,
    email       VARCHAR(255) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    display_name VARCHAR(255),
    is_active   BOOLEAN NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_login_at TIMESTAMPTZ
);
CREATE INDEX ix_auth_users_email ON auth_users (email);
```

### Table: `blog_sessions`
```sql
CREATE TABLE blog_sessions (
    id                      SERIAL PRIMARY KEY,
    user_id                 INTEGER NOT NULL REFERENCES auth_users(id) ON DELETE CASCADE,
    topic                   VARCHAR(500) NOT NULL,
    audience                VARCHAR(255) NOT NULL DEFAULT 'general readers',
    tone                    VARCHAR(100) NOT NULL DEFAULT 'professional',
    status                  VARCHAR(50) NOT NULL DEFAULT 'QUEUED',
    current_stage           VARCHAR(50),

    -- ADK pipeline state (needed for HITL resume)
    adk_session_id          VARCHAR(255),
    invocation_id           VARCHAR(255),
    confirmation_request_id VARCHAR(255),

    -- Content produced at each HITL gate
    outline_data            JSONB,
    final_content           TEXT,

    -- Budget tracking (denormalized for fast reads, ledger is source of truth)
    budget_reserved_tokens  INTEGER NOT NULL DEFAULT 0,
    budget_spent_tokens     INTEGER NOT NULL DEFAULT 0,
    budget_reserved_usd     NUMERIC(12,8) NOT NULL DEFAULT 0,
    budget_spent_usd        NUMERIC(12,8) NOT NULL DEFAULT 0,

    -- Lease-based worker ownership
    lease_owner             VARCHAR(255),
    lease_expires_at        TIMESTAMPTZ,
    lease_version           INTEGER NOT NULL DEFAULT 0,
    reap_count              INTEGER NOT NULL DEFAULT 0,
    last_heartbeat_at       TIMESTAMPTZ,

    -- Idempotency
    idempotency_key         VARCHAR(255),

    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at            TIMESTAMPTZ,
    failed_at               TIMESTAMPTZ,
    failure_reason          TEXT,

    CONSTRAINT uq_blog_sessions_idempotency
        UNIQUE (user_id, idempotency_key),

    CONSTRAINT ck_blog_sessions_status CHECK (status IN (
        'QUEUED', 'PROCESSING', 'AWAITING_OUTLINE_REVIEW',
        'AWAITING_FINAL_REVIEW', 'COMPLETED', 'FAILED', 'CANCELLED'
    ))
);
CREATE INDEX ix_blog_sessions_user_id ON blog_sessions (user_id);
CREATE INDEX ix_blog_sessions_status ON blog_sessions (status);
CREATE INDEX ix_blog_sessions_lease_expires ON blog_sessions (lease_expires_at)
    WHERE status = 'PROCESSING';
```

### Table: `agent_runs`
```sql
CREATE TABLE agent_runs (
    id              SERIAL PRIMARY KEY,
    blog_session_id INTEGER NOT NULL REFERENCES blog_sessions(id) ON DELETE CASCADE,
    stage_name      VARCHAR(100) NOT NULL,
    agent_name      VARCHAR(100) NOT NULL,
    model_name      VARCHAR(100) NOT NULL,
    status          VARCHAR(50) NOT NULL DEFAULT 'STARTED',
    prompt_tokens   INTEGER NOT NULL DEFAULT 0,
    completion_tokens INTEGER NOT NULL DEFAULT 0,
    total_tokens    INTEGER NOT NULL DEFAULT 0,
    cost_usd        NUMERIC(12,8) NOT NULL DEFAULT 0,
    latency_ms      INTEGER,
    output_snapshot JSONB,
    error_message   TEXT,
    started_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at    TIMESTAMPTZ,

    CONSTRAINT uq_agent_runs_session_stage
        UNIQUE (blog_session_id, stage_name),

    CONSTRAINT ck_agent_runs_status CHECK (
        status IN ('STARTED', 'COMPLETED', 'FAILED')
    )
);
CREATE INDEX ix_agent_runs_session ON agent_runs (blog_session_id);
```

### Table: `budget_ledger`
```sql
CREATE TABLE budget_ledger (
    id              SERIAL PRIMARY KEY,
    user_id         INTEGER NOT NULL REFERENCES auth_users(id) ON DELETE CASCADE,
    blog_session_id INTEGER REFERENCES blog_sessions(id) ON DELETE SET NULL,
    agent_run_id    INTEGER REFERENCES agent_runs(id) ON DELETE SET NULL,
    entry_type      VARCHAR(50) NOT NULL,
    tokens          INTEGER NOT NULL DEFAULT 0,
    amount_usd      NUMERIC(12,8) NOT NULL DEFAULT 0,
    note            VARCHAR(255),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT ck_budget_ledger_entry_type CHECK (
        entry_type IN ('GRANT', 'RESERVE', 'COMMIT', 'RELEASE', 'ADJUSTMENT')
    )
);
CREATE INDEX ix_budget_ledger_user_id ON budget_ledger (user_id);
CREATE INDEX ix_budget_ledger_session ON budget_ledger (blog_session_id);
```

**Budget semantics:**
- `GRANT`: Initial budget given to a new user (positive amount_usd, positive tokens). Written at registration.
- `RESERVE`: Estimated budget held at generation start (negative amount_usd, negative tokens). Written before job is enqueued.
- `COMMIT`: Actual cost for one agent stage (negative amount_usd, negative tokens). Written by executor per `CostInfo` object.
- `RELEASE`: Excess reserved budget returned after pipeline completes (positive amount_usd, positive tokens). Written by executor after all commits. `release = |reserved| - sum(|commits|)`.
- `ADJUSTMENT`: Manual correction by operator.

**Balance formula:**
```sql
SELECT COALESCE(SUM(amount_usd), 0) as balance_usd,
       COALESCE(SUM(tokens), 0) as balance_tokens
FROM budget_ledger
WHERE user_id = $1;
```
A negative sum means the user has spent more than granted. Balance = GRANT - RESERVE - COMMIT + RELEASE.

---

## TARGET FILE STRUCTURE

Build exactly these files. No additional files.

```
src/
├── agents/           (DO NOT TOUCH — existing files)
├── config/           (DO NOT TOUCH — existing files)
├── core/
│   ├── database.py           (NEW)
│   ├── redis_pool.py         (KEEP AS-IS)
│   ├── sanitization.py       (KEEP AS-IS)
│   ├── session_store.py      (KEEP AS-IS)
│   ├── task_queue.py         (REWRITE)
│   └── errors.py             (KEEP AS-IS)
├── models/
│   ├── orm_models.py         (REWRITE — canonical tables only)
│   ├── schemas.py            (REWRITE — v1 schemas only)
│   └── repositories/
│       ├── auth_user_repository.py     (KEEP — already correct)
│       ├── blog_session_repository.py  (REWRITE)
│       ├── agent_run_repository.py     (KEEP — already correct)
│       └── budget_repository.py        (REWRITE)
├── services/
│   ├── auth_service.py       (NEW)
│   ├── blog_service.py       (NEW)
│   └── budget_service.py     (REWRITE)
├── api/
│   ├── main.py               (REWRITE — minimal)
│   ├── auth.py               (KEEP — JWT dependency)
│   ├── middleware.py         (KEEP AS-IS)
│   └── routes/
│       ├── auth_routes.py    (NEW)
│       ├── blog_routes.py    (NEW)
│       └── health.py         (KEEP AS-IS)
└── workers/
    ├── blog_worker.py        (REWRITE)
    ├── executor.py           (NEW — replaces stage_executor.py)
    └── reaper.py             (REWRITE)
```

---

## FILE SPECIFICATIONS

### `src/core/database.py`
```python
"""SQLAlchemy async engine and session factory."""
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from src.config.database_config import db_settings

engine = create_async_engine(
    db_settings.database_url,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
)

AsyncSessionFactory = async_sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)

async def get_db_session() -> AsyncSession:
    """FastAPI dependency. Yields one session per request, commits on success, rolls back on error."""
    async with AsyncSessionFactory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
```

---

### `src/core/task_queue.py` — FULL REWRITE

The queue uses two Redis structures:
- `blogify:tasks` (LIST) — pending job payloads as JSON strings
- `blogify:processing` (ZSET) — jobs currently being processed, scored by deadline timestamp

**Critical requirement:** The dequeue operation MUST be atomic. Use this Lua script:
```lua
-- Atomically pop from LIST and add to ZSET in one operation
local job = redis.call('RPOP', KEYS[1])
if not job then return nil end
redis.call('ZADD', KEYS[2], ARGV[1], job)
return job
```

Where `KEYS[1] = "blogify:tasks"`, `KEYS[2] = "blogify:processing"`, `ARGV[1] = deadline_timestamp`.

**Job payload schema** (JSON string in queue):
```python
@dataclass
class BlogJob:
    session_id: int          # blog_sessions.id
    user_id: int             # auth_users.id
    adk_session_id: str      # UUID for ADK pipeline
    topic: str
    audience: str
    tone: str
    phase: str               # "start" | "resume_outline" | "resume_final"
    invocation_id: str | None = None
    confirmation_request_id: str | None = None
    approved_outline: dict | None = None
    feedback_text: str | None = None
    enqueued_at: str = ""    # ISO datetime
```

**Public interface:**
```python
class TaskQueue:
    QUEUE_KEY = "blogify:tasks"
    PROCESSING_KEY = "blogify:processing"
    VISIBILITY_TIMEOUT_SECONDS = 300  # 5 minutes

    async def enqueue(self, job: BlogJob) -> None:
        """Push job JSON to the left of the list."""

    async def dequeue(self, timeout: int = 5) -> BlogJob | None:
        """Atomically pop from list and add to processing ZSET. Returns None on timeout."""

    async def acknowledge(self, job: BlogJob) -> None:
        """Remove job from processing ZSET after successful completion."""

    async def reclaim_stale(self) -> int:
        """
        Move jobs from ZSET back to LIST if their deadline has passed.
        Called by the reaper. Returns count of reclaimed jobs.
        Uses ZRANGEBYSCORE to find jobs with score < now().
        For each: ZREM from processing, LPUSH back to queue.
        Returns count reclaimed.
        """

    async def extend_visibility(self, job: BlogJob, additional_seconds: int = 60) -> None:
        """Update the ZSET score for a job to extend its processing deadline."""
```

---

### `src/models/orm_models.py` — FULL REWRITE

Keep only these ORM models matching the schema defined above. Delete all legacy models (`User`, `Blog`, `CostRecord`, `Tenant`, `ServiceClient`, etc).

```python
import enum
from sqlalchemy import ...
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

class Base(DeclarativeBase):
    pass

class BlogSessionStatus(str, enum.Enum):
    QUEUED = "QUEUED"
    PROCESSING = "PROCESSING"
    AWAITING_OUTLINE_REVIEW = "AWAITING_OUTLINE_REVIEW"
    AWAITING_FINAL_REVIEW = "AWAITING_FINAL_REVIEW"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"

class BudgetEntryType(str, enum.Enum):
    GRANT = "GRANT"
    RESERVE = "RESERVE"
    COMMIT = "COMMIT"
    RELEASE = "RELEASE"
    ADJUSTMENT = "ADJUSTMENT"

class AgentRunStatus(str, enum.Enum):
    STARTED = "STARTED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"

# AuthUser, BlogSession, AgentRun, BudgetLedger ORM classes
# matching the schema above exactly
```

---

### `src/models/repositories/blog_session_repository.py` — FULL REWRITE

```python
class BlogSessionRepository:
    def __init__(self, session: AsyncSession) -> None: ...

    async def create(self, *, user_id, topic, audience, tone,
                     adk_session_id, idempotency_key=None) -> BlogSession: ...

    async def get_by_id(self, session_id: int) -> BlogSession | None: ...

    async def get_by_idempotency_key(self, user_id: int,
                                      key: str) -> BlogSession | None: ...

    async def get_for_user(self, user_id: int,
                           limit: int = 20) -> list[BlogSession]: ...

    async def count_active_for_user(self, user_id: int) -> int:
        """Count sessions in QUEUED | PROCESSING | AWAITING_* states."""

    async def update_status(self, session_id: int, status: BlogSessionStatus,
                            current_stage: str | None = None) -> None: ...

    async def save_outline(self, session_id: int, outline_data: dict,
                           invocation_id: str,
                           confirmation_request_id: str) -> None:
        """Save outline and ADK resume IDs when pipeline pauses for HITL."""

    async def save_final_content(self, session_id: int,
                                  content: str) -> None: ...

    async def acquire_lease(self, session_id: int,
                             worker_id: str,
                             lease_seconds: int = 300) -> bool:
        """
        Attempt to acquire worker lease using optimistic lock on lease_version.
        Uses UPDATE ... WHERE lease_version = current_version AND
        (lease_expires_at IS NULL OR lease_expires_at < now()).
        Returns True if acquired, False if another worker holds it.
        """

    async def release_lease(self, session_id: int,
                             worker_id: str) -> None: ...

    async def heartbeat_lease(self, session_id: int,
                               worker_id: str,
                               extend_seconds: int = 60) -> None:
        """Extend lease_expires_at and update last_heartbeat_at."""

    async def get_stale_processing_sessions(self,
                                             stale_threshold_minutes: int = 10
                                             ) -> list[BlogSession]:
        """
        Return PROCESSING sessions where lease_expires_at < now().
        These are candidates for reaper recovery.
        """

    async def increment_reap_count(self, session_id: int) -> int:
        """Increment reap_count and return new value."""

    async def mark_failed(self, session_id: int,
                           reason: str) -> None: ...
```

---

### `src/models/repositories/budget_repository.py` — FULL REWRITE

```python
class BudgetRepository:
    def __init__(self, session: AsyncSession) -> None: ...

    async def get_balance(self, user_id: int) -> dict:
        """
        Return {"balance_usd": Decimal, "balance_tokens": int}.
        Computed as SUM(amount_usd) and SUM(tokens) across all ledger entries for user.
        """

    async def write_entry(self, *, user_id: int,
                           blog_session_id: int | None,
                           agent_run_id: int | None,
                           entry_type: BudgetEntryType,
                           tokens: int,
                           amount_usd: Decimal,
                           note: str | None = None) -> BudgetLedger:
        """Single method for all ledger writes. Never update, always insert."""

    async def get_ledger_for_session(self,
                                      blog_session_id: int) -> list[BudgetLedger]:
        """Return all ledger entries for a session, ordered by created_at."""

    async def get_reserved_for_session(self,
                                        blog_session_id: int) -> Decimal:
        """
        Return sum of RESERVE entries for this session (as a negative number).
        Used by executor to compute release amount.
        """

    async def get_committed_for_session(self,
                                         blog_session_id: int) -> Decimal:
        """Return sum of COMMIT entries for this session (as a negative number)."""
```

---

### `src/services/auth_service.py` — NEW

```python
class AuthService:
    """Handles user registration, login, and JWT issuance."""

    INITIAL_BUDGET_USD = Decimal("5.00")
    INITIAL_BUDGET_TOKENS = 500_000

    def __init__(self, user_repo: AuthUserRepository,
                 budget_repo: BudgetRepository) -> None: ...

    async def register(self, email: str,
                        password: str,
                        display_name: str | None = None) -> AuthUser:
        """
        1. Check email not already registered. Raise 409 if taken.
        2. Hash password with bcrypt.
        3. Create AuthUser row.
        4. Write GRANT ledger entry for INITIAL_BUDGET_USD / INITIAL_BUDGET_TOKENS.
        5. Return AuthUser.
        All in one transaction (session passed from caller).
        """

    async def login(self, email: str, password: str) -> str:
        """
        1. Fetch user by email. Raise 401 if not found.
        2. Verify password. Raise 401 if wrong.
        3. Update last_login_at.
        4. Return signed JWT with sub=str(user.id), exp=24h.
        """

    async def get_current_user(self, user_id: int) -> AuthUser:
        """Fetch by id. Raise 401 if not found or not active."""
```

---

### `src/services/budget_service.py` — REWRITE

```python
from src.config.budget_config import ESTIMATED_TOKENS_PER_BLOG, get_model_cost

class BudgetService:
    """
    Owns all budget operations. Never opens DB connections.
    Takes budget_repo and session_repo as constructor arguments.
    """

    def __init__(self, budget_repo: BudgetRepository,
                 session_repo: BlogSessionRepository) -> None: ...

    async def check_and_reserve(self, user_id: int,
                                  blog_session_id: int) -> None:
        """
        1. Get current balance from budget_repo.get_balance().
        2. Compute estimated_usd from config: ESTIMATED_TOKENS_PER_BLOG * price_per_token.
        3. If balance_usd < estimated_usd: raise InsufficientBudgetError.
        4. Write RESERVE entry: tokens = -ESTIMATED_TOKENS_PER_BLOG,
                                 amount_usd = -estimated_usd.
        5. Update blog_sessions.budget_reserved_usd and budget_reserved_tokens.
        NOTE: Caller must hold a Redis lock keyed on f"budget_lock:{user_id}"
        before calling this method to prevent race conditions.
        Document this requirement clearly in the docstring.
        """

    async def commit_stage(self, *, user_id: int,
                            blog_session_id: int,
                            agent_run_id: int,
                            actual_tokens: int,
                            actual_usd: Decimal) -> None:
        """
        1. Write COMMIT ledger entry with negative actual_tokens, negative actual_usd.
        2. Update blog_sessions.budget_spent_tokens += actual_tokens,
                              budget_spent_usd += actual_usd.
        Idempotency: check agent_run_id has no existing COMMIT before writing.
        """

    async def release_excess(self, *, user_id: int,
                               blog_session_id: int) -> None:
        """
        Called after all stage commits are done.
        1. reserved = abs(get_reserved_for_session())
        2. spent = abs(get_committed_for_session())
        3. excess = reserved - spent
        4. If excess > 0: write RELEASE entry: tokens = +excess_tokens,
                                                amount_usd = +excess_usd.
        """

    async def release_all(self, *, user_id: int,
                           blog_session_id: int) -> None:
        """
        Called on session failure. Release the entire reserved amount.
        1. reserved = abs(get_reserved_for_session())
        2. Write RELEASE entry returning full reserved amount.
        """

    async def get_balance_snapshot(self, user_id: int) -> dict:
        """Return {"balance_usd": float, "balance_tokens": int}."""
```

---

### `src/services/blog_service.py` — NEW

```python
class BlogService:
    """
    Owns the blog session lifecycle from the API side.
    Does not interact with the pipeline or worker directly.
    Enqueues jobs to Redis. Worker picks them up.
    """

    MAX_ACTIVE_SESSIONS_PER_USER = 1  # v1: one at a time

    def __init__(self,
                 session_repo: BlogSessionRepository,
                 budget_service: BudgetService,
                 task_queue: TaskQueue,
                 redis_client) -> None: ...

    async def create_generation(self, *,
                                  user_id: int,
                                  topic: str,
                                  audience: str,
                                  tone: str,
                                  idempotency_key: str | None = None
                                  ) -> BlogSession:
        """
        1. If idempotency_key provided: check blog_session_repository for existing.
           If found: return it (idempotent).
        2. count_active_for_user(user_id). If >= MAX_ACTIVE_SESSIONS: raise 409.
        3. Generate adk_session_id = str(uuid4()).
        4. Create BlogSession row (status=QUEUED).
        5. Acquire Redis lock: SET budget_lock:{user_id} 1 NX EX 10.
           If lock not acquired: raise 429.
        6. Call budget_service.check_and_reserve(user_id, session.id).
        7. Release Redis lock.
        8. Build BlogJob(phase="start", session_id=session.id, user_id=user_id,
                         adk_session_id=adk_session_id, topic=topic,
                         audience=audience, tone=tone).
        9. task_queue.enqueue(job).
        10. Return session.
        """

    async def get_user_sessions(self, user_id: int) -> list[BlogSession]:
        """Return all sessions for user, newest first."""

    async def get_session(self, user_id: int,
                           session_id: int) -> BlogSession:
        """Get session by id. Raise 404 if not found. Raise 403 if user_id mismatch."""

    async def submit_outline_review(self, *,
                                     user_id: int,
                                     session_id: int,
                                     approved_outline: dict,
                                     feedback_text: str | None = None
                                     ) -> BlogSession:
        """
        1. get_session(user_id, session_id). Verify status = AWAITING_OUTLINE_REVIEW.
        2. Update session.outline_data = approved_outline.
        3. Update status = QUEUED.
        4. Build BlogJob(phase="resume_outline",
                         invocation_id=session.invocation_id,
                         confirmation_request_id=session.confirmation_request_id,
                         approved_outline=approved_outline,
                         feedback_text=feedback_text).
        5. Enqueue job.
        6. Return updated session.
        """

    async def submit_final_review(self, *,
                                   user_id: int,
                                   session_id: int,
                                   approved: bool,
                                   feedback_text: str | None = None
                                   ) -> BlogSession:
        """
        1. get_session(user_id, session_id). Verify status = AWAITING_FINAL_REVIEW.
        2. If approved: update status = COMPLETED, completed_at = now().
        3. If not approved: update status = FAILED, failure_reason = feedback_text.
        4. Return updated session.
        Note: For v1, final review does not re-run the pipeline.
              It simply marks the already-generated content as approved or rejected.
        """

    async def get_budget(self, user_id: int) -> dict:
        """Return balance snapshot from budget_service."""
```

---

### `src/api/routes/auth_routes.py` — NEW

```python
router = APIRouter(prefix="/auth", tags=["auth"])

class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    display_name: str | None = None

class LoginRequest(BaseModel):
    email: EmailStr
    password: str

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: int
    email: str

@router.post("/register", response_model=TokenResponse, status_code=201)
async def register(body: RegisterRequest, session: AsyncSession = Depends(get_db_session)):
    """Register new user. Grants initial budget automatically."""

@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, session: AsyncSession = Depends(get_db_session)):
    """Login and receive JWT."""

@router.get("/me")
async def get_me(current_user: AuthUser = Depends(get_current_user)):
    """Return current authenticated user info."""
```

---

### `src/api/routes/blog_routes.py` — NEW

```python
router = APIRouter(prefix="/blogs", tags=["blogs"])

class GenerateRequest(BaseModel):
    topic: str = Field(min_length=3, max_length=500)
    audience: str = Field(default="general readers", max_length=255)
    tone: str = Field(default="professional", max_length=100)
    idempotency_key: str | None = Field(default=None, max_length=255)

class OutlineReviewRequest(BaseModel):
    approved_outline: dict
    feedback_text: str | None = None

class FinalReviewRequest(BaseModel):
    approved: bool
    feedback_text: str | None = None

@router.post("/generate", status_code=202)
async def generate_blog(body: GenerateRequest,
                         current_user = Depends(get_current_user),
                         session: AsyncSession = Depends(get_db_session)):
    """Accept blog generation request. Returns session_id immediately."""

@router.get("/")
async def list_blogs(current_user = Depends(get_current_user),
                      session: AsyncSession = Depends(get_db_session)):
    """List all sessions for authenticated user."""

@router.get("/{session_id}")
async def get_blog(session_id: int,
                    current_user = Depends(get_current_user),
                    session: AsyncSession = Depends(get_db_session)):
    """Get session detail including agent_runs and outline_data."""

@router.post("/{session_id}/outline-review")
async def submit_outline_review(session_id: int,
                                  body: OutlineReviewRequest,
                                  current_user = Depends(get_current_user),
                                  session: AsyncSession = Depends(get_db_session)):
    """Submit outline approval to resume pipeline."""

@router.post("/{session_id}/final-review")
async def submit_final_review(session_id: int,
                                body: FinalReviewRequest,
                                current_user = Depends(get_current_user),
                                session: AsyncSession = Depends(get_db_session)):
    """Submit final content approval."""

@router.get("/budget")
async def get_budget(current_user = Depends(get_current_user),
                      session: AsyncSession = Depends(get_db_session)):
    """Return user's current budget balance."""
```

---

### `src/workers/executor.py` — NEW (replaces stage_executor.py)

This is the bridge between the worker and the ADK pipeline. It has ONE public method and private helpers only.

```python
from src.agents.pipeline import run_pipeline, resume_pipeline, CostInfo, PipelineResult
from src.config.budget_config import get_model_cost

class PipelineExecutor:
    """
    Calls the ADK pipeline and persists all results to the database.
    Receives an open AsyncSession from the worker — does not open its own.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._session_repo = BlogSessionRepository(session)
        self._run_repo = AgentRunRepository(session)
        self._budget_repo = BudgetRepository(session)
        self._budget_service = BudgetService(self._budget_repo, self._session_repo)

    async def execute(self, job: BlogJob) -> None:
        """
        Main entry point. Routes to correct execution path based on job.phase.
        Handles all DB writes. Never raises — catches and persists failures.
        """
        try:
            if job.phase == "start":
                await self._execute_start(job)
            elif job.phase == "resume_outline":
                await self._execute_resume_outline(job)
            else:
                raise ValueError(f"Unknown job phase: {job.phase}")
        except Exception as e:
            await self._handle_failure(job, str(e))

    async def _execute_start(self, job: BlogJob) -> None:
        """
        1. update_status(PROCESSING, current_stage="intent")
        2. result = await run_pipeline(topic, audience, user_id=str(job.user_id),
                                        session_id=job.adk_session_id)
        3. If result.error: call _handle_failure()
        4. If result.paused_for_confirmation: call _handle_outline_pause()
        5. Else: call _handle_success()
        """

    async def _execute_resume_outline(self, job: BlogJob) -> None:
        """
        1. update_status(PROCESSING, current_stage="research")
        2. result = await resume_pipeline(
                topic=job.topic, audience=job.audience,
                user_id=str(job.user_id), session_id=job.adk_session_id,
                invocation_id=job.invocation_id,
                confirmation_request_id=job.confirmation_request_id,
                approved_outline=job.approved_outline,
                feedback_text=job.feedback_text)
        3. If result.error: call _handle_failure()
        4. Else: call _handle_success() with status=AWAITING_FINAL_REVIEW
        """

    async def _handle_outline_pause(self, job: BlogJob,
                                     result: PipelineResult) -> None:
        """
        Called when pipeline pauses at outline HITL gate.
        1. _commit_costs(job, result.costs) — commit intent+outline costs
        2. session_repo.save_outline(session_id, result.outline,
                                      result.invocation_id,
                                      result.confirmation_request_id)
        3. update_status(AWAITING_OUTLINE_REVIEW, "outline_review")
        Also saves the outline to blog_sessions.outline_data in Postgres so it
        survives Redis TTL expiry during long HITL waits.
        """

    async def _handle_success(self, job: BlogJob,
                               result: PipelineResult) -> None:
        """
        Called when pipeline runs to completion (after resume).
        1. _commit_costs(job, result.costs) — commit research+writer+editor costs
        2. session_repo.save_final_content(job.session_id, result.final_content)
        3. budget_service.release_excess(user_id, session_id)
        4. update_status(AWAITING_FINAL_REVIEW, "final_review")
           Note: AWAITING_FINAL_REVIEW because human must still approve before COMPLETED.
        """

    async def _handle_failure(self, job: BlogJob, error: str) -> None:
        """
        1. session_repo.mark_failed(job.session_id, reason=error)
        2. budget_service.release_all(user_id, session_id)
        3. Log the failure with session_id and error.
        """

    async def _commit_costs(self, job: BlogJob,
                             costs: list[CostInfo]) -> None:
        """
        For each CostInfo where total_tokens > 0:
        1. Check agent_run_repo.is_stage_completed(session_id, cost.stage).
           If already exists: SKIP (idempotency — prevents double-commit on retry).
        2. run = await run_repo.start(session_id, cost.stage, cost.stage, cost.model)
        3. cost_usd = get_model_cost(cost.model, cost.total_tokens)
        4. await run_repo.complete(run.id, prompt_tokens, completion_tokens,
                                    cost_usd, latency_ms=0,
                                    output_snapshot=None)
        5. await budget_service.commit_stage(user_id, session_id,
                                              agent_run_id=run.id,
                                              actual_tokens=cost.total_tokens,
                                              actual_usd=cost_usd)
        """
```

---

### `src/workers/blog_worker.py` — REWRITE

```python
"""
Worker process. One long-running loop. Dequeues jobs, runs executor, releases lease.
Run as: python -m src.workers.blog_worker
"""

WORKER_ID = f"worker-{socket.gethostname()}-{os.getpid()}"
MAX_CONCURRENT_JOBS = 3  # Semaphore limit per worker process
HEARTBEAT_INTERVAL = 15  # seconds
LEASE_SECONDS = 300

class BlogWorker:
    def __init__(self) -> None:
        self._queue = TaskQueue()
        self._semaphore = asyncio.Semaphore(MAX_CONCURRENT_JOBS)
        self._running = True

    async def run(self) -> None:
        """Main loop. Dequeue jobs and process concurrently up to MAX_CONCURRENT_JOBS."""
        asyncio.create_task(self._heartbeat_loop())
        while self._running:
            job = await self._queue.dequeue(timeout=5)
            if job is None:
                continue
            asyncio.create_task(self._process_job(job))

    async def _process_job(self, job: BlogJob) -> None:
        async with self._semaphore:
            async with AsyncSessionFactory() as session:
                session_repo = BlogSessionRepository(session)
                acquired = await session_repo.acquire_lease(
                    job.session_id, WORKER_ID, LEASE_SECONDS
                )
                if not acquired:
                    # Another worker has this job. Acknowledge to remove from
                    # processing ZSET (the other worker will handle it).
                    await self._queue.acknowledge(job)
                    return

                # Start heartbeat task for this job
                heartbeat_task = asyncio.create_task(
                    self._job_heartbeat(job.session_id, session_repo)
                )
                try:
                    executor = PipelineExecutor(session)
                    await executor.execute(job)
                    await session.commit()
                    await self._queue.acknowledge(job)
                except Exception as e:
                    await session.rollback()
                    logger.error("job_failed", session_id=job.session_id, error=str(e))
                    # Do NOT acknowledge — reaper will reclaim and re-enqueue
                finally:
                    heartbeat_task.cancel()
                    await session_repo.release_lease(job.session_id, WORKER_ID)

    async def _job_heartbeat(self, session_id: int,
                              session_repo: BlogSessionRepository) -> None:
        """Extend lease every HEARTBEAT_INTERVAL seconds while job is running."""
        while True:
            await asyncio.sleep(HEARTBEAT_INTERVAL)
            try:
                await session_repo.heartbeat_lease(session_id, WORKER_ID, extend_seconds=60)
            except Exception:
                pass  # Heartbeat failure is non-fatal; reaper handles stale leases

    async def _heartbeat_loop(self) -> None:
        """Periodic worker liveness signal to Redis."""
        redis = get_redis_client()
        key = f"blogify:worker:{WORKER_ID}"
        while self._running:
            await redis.set(key, datetime.utcnow().isoformat(), ex=60)
            await asyncio.sleep(HEARTBEAT_INTERVAL)
```

---

### `src/workers/reaper.py` — REWRITE

The reaper is a separate asyncio task that runs inside the worker process (not a separate service for v1). It handles two recovery responsibilities.

```python
"""
Reaper: recovers stale jobs and re-enqueues them for retry.
Runs as an asyncio task inside blog_worker.py alongside the main loop.
"""

MAX_REAP_COUNT = 3           # Sessions reapable this many times before marked FAILED
REAP_INTERVAL_SECONDS = 60   # How often reaper runs
STALE_THRESHOLD_MINUTES = 10 # Sessions in PROCESSING with expired lease older than this

class Reaper:
    """
    Two responsibilities:
    1. DB Reaper: find PROCESSING sessions with expired leases in Postgres.
                  Re-enqueue them as new jobs or mark them FAILED if max reaps exceeded.
    2. Queue Reclaim: call task_queue.reclaim_stale() to move timed-out jobs
                      from the processing ZSET back to the task list.
                      This handles the case where a worker crashed after dequeue
                      but before acquiring the DB lease.
    """

    def __init__(self, task_queue: TaskQueue) -> None:
        self._queue = task_queue

    async def run_forever(self) -> None:
        """Loop forever. Run both reap passes every REAP_INTERVAL_SECONDS."""
        while True:
            try:
                await self._reap_db_sessions()
                await self._reap_queue()
            except Exception as e:
                logger.error("reaper_cycle_failed", error=str(e))
            await asyncio.sleep(REAP_INTERVAL_SECONDS)

    async def _reap_db_sessions(self) -> None:
        """
        1. Open a DB session.
        2. session_repo.get_stale_processing_sessions(STALE_THRESHOLD_MINUTES).
        3. For each stale session:
           a. new_reap_count = session_repo.increment_reap_count(session.id)
           b. If new_reap_count > MAX_REAP_COUNT:
              - session_repo.mark_failed(session.id, "max reap count exceeded")
              - budget_service.release_all(session.user_id, session.id)
              - Log permanent failure
           c. Else:
              - session_repo.update_status(session.id, QUEUED)
              - Reconstruct BlogJob from session fields
              - task_queue.enqueue(job)
              - Log requeue with reap_count
        """

    async def _reap_queue(self) -> None:
        """
        Call task_queue.reclaim_stale().
        Log count of reclaimed jobs.
        These jobs will be picked up by the worker's dequeue loop naturally.
        """
```

**Reaper semantics — invariants that MUST hold:**
1. A session is only ever marked FAILED by the reaper if `reap_count > MAX_REAP_COUNT`. Never on first failure.
2. When the reaper re-enqueues a session, it must reset `lease_owner = NULL` and `lease_expires_at = NULL` so a worker can acquire the lease.
3. The reaper NEVER commits budget operations. It delegates to `BudgetService.release_all()` for failed sessions.
4. The DB reaper and queue reclaim are independent. The queue reclaim does not know about session state. The DB reaper does not know about the Redis processing ZSET. They fix different failure modes.
5. A session in `AWAITING_OUTLINE_REVIEW` or `AWAITING_FINAL_REVIEW` is NOT stale — it is intentionally paused waiting for human input. The reaper must NOT touch these statuses.

---

## API CONTRACT

### Authentication
All `/blogs/*` endpoints require `Authorization: Bearer <jwt>`.
JWT payload: `{"sub": "42", "exp": 1234567890}` where sub is the `auth_users.id`.

### Status lifecycle
```
QUEUED
  → PROCESSING          (worker picks up job)
  → AWAITING_OUTLINE_REVIEW  (pipeline pauses at HITL gate 1)
  → QUEUED              (user submits outline review → re-enqueued)
  → PROCESSING          (worker picks up resume job)
  → AWAITING_FINAL_REVIEW    (pipeline completes, waiting for human approval)
  → COMPLETED           (user approves final content)
  → FAILED              (error at any stage, or user rejects final content)
```

### `POST /auth/register`
Request: `{email, password, display_name?}`
Response 201: `{access_token, token_type, user_id, email}`
Error 409: email already registered

### `POST /auth/login`
Request: `{email, password}`
Response 200: `{access_token, token_type, user_id, email}`
Error 401: invalid credentials

### `POST /blogs/generate`
Request: `{topic, audience?, tone?, idempotency_key?}`
Response 202:
```json
{
  "session_id": 42,
  "status": "QUEUED",
  "adk_session_id": "uuid",
  "created_at": "iso"
}
```
Error 409: user already has active generation
Error 402: insufficient budget

### `GET /blogs/`
Response 200: `[{session_id, topic, status, current_stage, created_at, completed_at}]`

### `GET /blogs/{session_id}`
Response 200:
```json
{
  "session_id": 42,
  "topic": "...",
  "audience": "...",
  "tone": "...",
  "status": "AWAITING_OUTLINE_REVIEW",
  "current_stage": "outline_review",
  "outline_data": {...},
  "final_content": null,
  "budget_reserved_usd": 0.08,
  "budget_spent_usd": 0.03,
  "agent_runs": [
    {"stage": "intent", "tokens": 1200, "cost_usd": 0.01, "status": "COMPLETED"},
    {"stage": "outline", "tokens": 2100, "cost_usd": 0.02, "status": "COMPLETED"}
  ],
  "created_at": "iso",
  "updated_at": "iso"
}
```

### `POST /blogs/{session_id}/outline-review`
Request: `{approved_outline: {...}, feedback_text?: "..."}`
Response 200: `{session_id, status: "QUEUED"}`
Error 409: session not in AWAITING_OUTLINE_REVIEW

### `POST /blogs/{session_id}/final-review`
Request: `{approved: true, feedback_text?: "..."}`
Response 200: `{session_id, status: "COMPLETED" | "FAILED"}`
Error 409: session not in AWAITING_FINAL_REVIEW

### `GET /blogs/budget`
Response 200: `{balance_usd: 4.91, balance_tokens: 491000}`

---

## BUDGET CONFIG (read from existing `src/config/budget_config.py`)

The existing `budget_config.py` already has `get_model_cost(model_name, tokens) -> float`.
Add these constants if not present:

```python
ESTIMATED_TOKENS_PER_BLOG = 50_000   # conservative estimate used for RESERVE
INITIAL_BUDGET_USD = Decimal("5.00")  # granted at registration
INITIAL_BUDGET_TOKENS = 500_000
```

Do not move pricing logic into services. Services import from config only.

---

## THINGS EXPLICITLY OUT OF SCOPE FOR V1

Do not implement these. Do not leave TODOs for them. Simply do not build them:
- Notifications system
- Multi-tenancy / service clients
- Rate limiting per user
- Blog revisions (2 revision limit)
- Pipeline state snapshot to Postgres on HITL pause (v2 hardening)
- Global concurrency coordination across multiple worker instances
- Webhook callbacks
- Admin routes

---

## VERIFICATION CHECKLIST

Before considering the implementation complete, verify:

- [ ] `src/agents/pipeline.py` is unchanged (diff should be empty)
- [ ] No file imports `from src.models.repository import db_repository`
- [ ] No file contains `user_id = "anonymous"`
- [ ] `task_queue.py` uses Lua script for atomic dequeue
- [ ] `budget_repository.py` only has INSERT operations in `write_entry()`, never UPDATE
- [ ] `executor.py` checks `is_stage_completed()` before writing any AgentRun (idempotency)
- [ ] `blog_session_repository.py` uses `UPDATE ... WHERE lease_version = ?` for lease acquisition
- [ ] `budget_service.check_and_reserve()` docstring documents Redis lock requirement
- [ ] `reaper.py` never touches sessions in AWAITING_* statuses
- [ ] New Alembic migration has `down_revision = None` (fresh schema)
- [ ] `auth_service.register()` writes a GRANT ledger entry in the same transaction as user creation

