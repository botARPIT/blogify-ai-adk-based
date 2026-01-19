"""Pydantic schemas for agent inputs and outputs."""

from pydantic import BaseModel, Field


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
    sections: list[SectionSchema] = Field(min_length=3, max_length=7, description="Blog sections")
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
