"""Editor agent for blog review and approval."""

from google.adk.agents import Agent
from google.adk.models.google_llm import Gemini

from src.config import EDITOR_MODEL, create_retry_config
from src.models.schemas import EditorReviewSchema


def create_editor_agent() -> Agent:
    return Agent(
        name="editor_agent",
        model=Gemini(
            model=EDITOR_MODEL.name,
            retry_options=create_retry_config(attempts=EDITOR_MODEL.retry_attempts),
            temperature=EDITOR_MODEL.temperature,
            max_output_tokens=EDITOR_MODEL.max_output_tokens,
        ),
        instruction="""
        Review the blog draft: {blog_draft}
        Research data available: {research_data}

        ── CITATION RULE (check this first) ────────────────────────────────────
        Examine research_data. It has real sources if ALL of the following hold:
          • research_data is not empty / null
          • research_data["sources"] is a non-empty list
          • At least one source has a non-empty "url" field

        IF REAL SOURCES EXIST → Citations mode:
          - Keep or add inline [N] markers where facts from the sources appear.
          - Every [N] in the text must map to a real entry in research_data["sources"].
          - Remove any [N] markers that have no matching source.
          - When approving, build a "Sources:" section listing only real URLs.

        IF NO REAL SOURCES → Plain mode:
          - Strip ALL [N] citation markers from the draft entirely.
          - Do NOT invent sources, URLs, or a Sources section.
          - The final blog must read as well-written, self-contained prose.
        ────────────────────────────────────────────────────────────────────────

        Review criteria (apply in both modes):
        1. Grammar, spelling, punctuation
        2. Tone consistency and professionalism
        3. Word count adherence to outline targets
        4. Content quality and engagement

        Decision process:

        IF ANY ISSUES FOUND:
        - Set approved=false
        - Provide specific, actionable feedback in 'feedback' field
        - Leave 'final_blog' and 'sources_section' empty

        IF READY FOR PUBLICATION:
        - Set approved=true
        - Polish the content (fix minor grammar/style issues)
        - In Citations mode: append a "Sources:" section with real URLs only
        - In Plain mode: no Sources section, no citation markers
        - Put the complete polished blog in 'final_blog'
        - Set 'feedback' to empty string

        Return JSON matching EditorReviewSchema exactly.
        """.strip(),
        output_schema=EditorReviewSchema,
        output_key="editor_review",
    )


editor_agent = create_editor_agent()
