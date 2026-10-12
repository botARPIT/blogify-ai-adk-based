"""Editor agent for blog review and approval.

The agent renders an editorial decision as raw model output under
``editor_review_raw``. A deterministic workflow node converts it to an
:class:`~src.models.schemas.EditorReviewSchema` and routes on it, so the
revision cycle stays bounded by application code rather than by whatever
structured-output support the provider happens to have.
"""

from google.adk.agents import Agent

from src.llm.factory import create_model
from src.llm.model_configs import EDITOR_MODEL

EDITOR_INSTRUCTION = """
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

Return a JSON object with 'approved', 'feedback', 'final_blog' and
'sources_section' fields.
""".strip()


def create_editor_agent() -> Agent:
    return Agent(
        name="editor_agent",
        model=create_model(EDITOR_MODEL),
        instruction=EDITOR_INSTRUCTION,
        output_key="editor_review_raw",
    )


editor_agent = create_editor_agent()
