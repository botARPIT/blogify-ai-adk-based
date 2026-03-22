"""LLM as Judge agent for final blog validation."""

from google.adk.agents import Agent
from google.adk.models.google_llm import Gemini
from google.genai import types
from pydantic import BaseModel, Field

from src.config.logging_config import get_logger

logger = get_logger(__name__)


class JudgeDecisionSchema(BaseModel):
    """LLM judge decision schema."""

    approved: bool = Field(description="Whether blog is approved for user delivery")
    confidence_score: float = Field(ge=0.0, le=1.0, description="Confidence in decision (0-1)")
    reasoning: str = Field(description="Detailed reasoning for the decision")
    issues_found: list[str] = Field(
        default_factory=list, description="List of specific issues if not approved"
    )
    quality_score: float = Field(
        ge=0.0, le=10.0, description="Overall quality rating (0-10)"
    )


# LLM as Judge agent
llm_judge_agent = Agent(
    name="llm_judge",
    model=Gemini(
        model="gemini-2.5-pro",  # Use stronger model for judging
        retry_options=types.HttpRetryOptions(attempts=2),
        temperature=0.1,  # Low temperature for consistent judging
        max_output_tokens=1000,
    ),
    instruction="""
    You are an expert blog quality judge. Your role is to evaluate if a blog is ready for delivery to the user.
    
    You will receive:
    - Original user intent and topic
    - Compressed context from the generation pipeline
    - Final blog content
    
    Evaluation Criteria (Rate each 0-10):
    
    1. FACTUAL ACCURACY
       - All claims are supported by the provided context
       - Citations match the research sources
       - No hallucinated facts or unsupported statements
    
    2. TOPIC ALIGNMENT  
       - Blog addresses the original user intent
       - Content matches the requested topic and audience
       - Sections align with the outline goals
    
    3. QUALITY & COHERENCE
       - Clear, engaging writing style
       - Logical flow and structure
       - No repetitive or contradictory content
       - Professional tone
    
    4. COMPLETENESS
       - All outline sections are covered
       - Adequate depth and detail
       - Sources/references are properly cited
    
    5. SAFETY
       - No harmful, offensive, or inappropriate content
       - No privacy violations or sensitive data leaks
       - Adheres to content safety guidelines
    
    Decision Process:
    - If ANY criterion scores below 6/10: REJECT with specific issues
    - If average score >= 7/10 AND no critical issues: APPROVE
    - Confidence score reflects certainty in your decision
    
    Return JSON with your decision, confidence, reasoning, issues, and quality score.
    """.strip(),
    output_schema=JudgeDecisionSchema,
    output_key="judge_decision",
)
