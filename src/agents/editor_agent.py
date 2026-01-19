"""Editor agent for blog review and approval."""

from google.adk.agents import Agent
from google.adk.models.google_llm import Gemini

from src.config import EDITOR_MODEL, create_retry_config
from src.models.schemas import EditorReviewSchema

# Create editor agent
editor_agent = Agent(
    name="editor_agent",
    model=Gemini(
        model=EDITOR_MODEL.name,
        retry_options=create_retry_config(attempts=EDITOR_MODEL.retry_attempts),
        temperature=EDITOR_MODEL.temperature,
        max_output_tokens=EDITOR_MODEL.max_output_tokens,
    ),
    instruction="""
    Review the blog draft: {blog_draft}
    Research sources: {research_data}
    
    Review criteria:
    1. Grammar, spelling, punctuation
    2. Citation accuracy - all [N] references must exist in research_data
    3. Tone consistency and professionalism
    4. Word count adherence to outline targets
    5. Content quality and engagement
    
    Decision process:
    
    IF ANY ISSUES FOUND:
    - Set approved=false
    - Provide specific, actionable feedback in 'feedback' field
    - Leave 'final_blog' and 'sources_section' empty
    
    IF READY FOR PUBLICATION:
    - Set approved=true
    - Polish the content (fix minor grammar/style issues)
    - Create professional "Sources:" section with all citations
    - Put complete polished blog in 'final_blog' field
    - Set 'feedback' to empty string
    
    Return JSON matching EditorReviewSchema exactly.
    """.strip(),
    output_schema=EditorReviewSchema,
    output_key="editor_review",
)
