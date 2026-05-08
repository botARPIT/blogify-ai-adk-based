"""Pydantic schemas for V1 API contract and agent I/O."""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, EmailStr, Field


# ---------------------------------------------------------------------------
# Agent I/O schemas (used by ADK agents - NOT part of API contract)
# ---------------------------------------------------------------------------


class IntentSchema(BaseModel):
    """Intent classification result."""

    status: str = Field(description="CLEAR | UNCLEAR_TOPIC | MULTI_TOPIC | MISSING_AUDIENCE")
    message: str = Field(description="Message explaining the classification")


class SectionSchema(BaseModel):
    """Blog section definition."""

    id: str = Field(description="Unique section identifier")
    heading: str = Field(description="Section heading")
    goal: str = Field(description="What this section should accomplish")
    target_words: int = Field(ge=80, le=300, description="Target word count")


class OutlineSchema(BaseModel):
    """Blog outline structure."""

    title: str = Field(max_length=120, description="Blog title")
    sections: list[SectionSchema] = Field(
        min_length=3, max_length=7, description="Blog sections"
    )
    estimated_total_words: int = Field(ge=300, le=2000, description="Total estimated words")


class ResearchSourceSchema(BaseModel):
    """Research source from Tavily."""

    title: str
    url: str
    content: str
    score: float = Field(ge=0.0, le=1.0)


class ResearchDataSchema(BaseModel):
    """Structured research data."""

    topic: str
    summary: str
    sources: list[ResearchSourceSchema]
    total_sources: int


class EditorReviewSchema(BaseModel):
    """Editor review result with approval decision."""

    approved: bool = Field(description="Whether blog is approved for publication")
    feedback: str = Field(description="Specific issues if not approved, empty if approved")
    final_blog: str = Field(description="Polished blog content if approved")
    sources_section: str = Field(description="Formatted sources/references section")


class FinalBlogSchema(BaseModel):
    """Final blog output."""

    title: str = Field(description="Final blog title")
    content: str = Field(description="Complete blog content with sources")
    word_count: int = Field(ge=300, description="Actual word count")
    sources_count: int = Field(ge=0, description="Number of sources cited")


# ---------------------------------------------------------------------------
# V1 API contract schemas
# ---------------------------------------------------------------------------


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    display_name: Optional[str] = None


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: int
    email: str


class UserResponse(BaseModel):
    id: int
    email: str
    display_name: Optional[str]
    is_active: bool
    created_at: datetime
    last_login_at: Optional[datetime]


class GenerateRequest(BaseModel):
    topic: str = Field(min_length=3, max_length=500)
    audience: str = Field(default="general readers", max_length=255)
    tone: str = Field(default="professional", max_length=100)
    idempotency_key: Optional[str] = Field(default=None, max_length=255)


class GenerateResponse(BaseModel):
    session_id: int
    status: str
    adk_session_id: str
    created_at: datetime


class OutlineReviewRequest(BaseModel):
    approved_outline: dict
    feedback_text: Optional[str] = None


class OutlineFrontendRequest(BaseModel):
    action: str
    edited_outline: Optional[dict] = None
    feedback_text: Optional[str] = None
    reviewer_user_id: Optional[int] = None


class OutlineFrontendDecision(BaseModel):
    session_id: int
    action: str
    new_status: str
    current_stage: Optional[str] = None


class OutlineSectionSchema(BaseModel):
    id: str
    heading: str
    goal: str
    target_words: int


class OutlineSchema(BaseModel):
    title: str
    sections: list[OutlineSectionSchema]
    estimated_total_words: int


class OutlineReviewView(BaseModel):
    session_id: int
    status: str
    current_stage: Optional[str] = None
    topic: str
    audience: Optional[str] = None
    feedback_text: Optional[str] = None
    outline: dict


class FinalReviewRequest(BaseModel):
    approved: bool
    feedback_text: Optional[str] = None


class AgentRunResponse(BaseModel):
    stage: str
    tokens: int
    cost_usd: float
    status: str


class AgentRunMetrics(BaseModel):
    run_id: int
    stage_name: str
    agent_name: str
    model_name: str
    status: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cost_usd: float
    latency_ms: Optional[int] = None
    started_at: datetime
    completed_at: Optional[datetime] = None
    error_message: Optional[str] = None


class SessionInfo(BaseModel):
    session_id: int
    status: str
    current_stage: Optional[str] = None
    topic: str
    audience: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    completed_at: Optional[datetime] = None
    # Computed/derived fields for the detail view
    budget_spent_usd: float = 0.0
    budget_spent_tokens: int = 0
    iteration_count: int = 0
    requires_human_review: bool = False
    remaining_revision_iterations: int = 0
    current_version_number: Optional[int] = None


class BlogVersionMetrics(BaseModel):
    version_id: int = 1
    version_number: int = 1
    title: Optional[str] = None
    content_markdown: Optional[str] = None
    word_count: int = 0
    sources_count: int = 0
    editor_status: str = "completed"
    created_by: str = "system"
    created_at: datetime


class BlogSessionMetrics(BaseModel):
    session: SessionInfo
    total_cost_usd: float
    total_tokens: int
    total_words: int
    outline: Optional[dict] = None
    latest_version: Optional[BlogVersionMetrics] = None
    agent_runs: list[AgentRunMetrics] = []
    review_events: list = []


class BlogSessionDetail(BaseModel):
    session_id: int
    topic: str
    audience: str
    tone: str
    status: str
    current_stage: Optional[str]
    outline_data: Optional[dict] = None
    final_content: Optional[str] = None
    budget_reserved_usd: float
    budget_spent_usd: float
    agent_runs: list[AgentRunResponse] = []
    created_at: datetime
    updated_at: datetime


class BlogSessionListItem(BaseModel):
    session_id: int
    topic: str
    audience: str
    tone: str
    status: str
    current_stage: Optional[str]
    created_at: datetime
    completed_at: Optional[datetime]


class BudgetResponse(BaseModel):
    balance_usd: float
    balance_tokens: int
    daily_blog_limit_left: int


class SessionStatusResponse(BaseModel):
    session_id: int
    status: str
    current_stage: Optional[str] = None
    current_agent: Optional[str] = None
    topic: Optional[str] = None
    created_at: datetime


class BlogContentView(BaseModel):
    session_id: int
    version_id: int = 1
    title: Optional[str] = None
    content_markdown: str
    word_count: int
    sources_count: int = 0
    topic: str
    audience: Optional[str] = None
    status: str


class BlogVersionView(BaseModel):
    version_id: int
    session_id: int
    version_number: int = 1
    source_type: str = "final"
    title: Optional[str] = None
    content_markdown: Optional[str] = None
    word_count: int = 0
    sources_count: int = 0
    editor_status: str = "completed"
    created_by: str = "system"
    created_at: datetime


class AuthMeResponse(BaseModel):
    authenticated: bool
    user: Optional["UserResponse"] = None