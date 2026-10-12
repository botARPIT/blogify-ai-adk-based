"""Blog outline generation agent.

The agent writes the outline; a deterministic workflow node turns the raw text
into an :class:`~src.models.schemas.OutlineSchema`. Because the model may answer
in Markdown or JSON depending on provider and prompt, enforcement belongs
outside ADK — ``output_schema`` here would be silently dropped by
OpenAI-compatible endpoints rather than applied.
"""

from google.adk.agents import Agent

from src.llm.factory import create_model
from src.llm.model_configs import OUTLINE_MODEL

OUTLINE_INSTRUCTION = """
Generate a structured blog outline based on the topic and audience from intent result: {intent_result}

Requirements:
- Title: Compelling, max 120 characters, SEO-friendly
- Sections: 3-7 sections
- Each section: id, heading, goal, target_words (80-300 each)
- Total words: Sum of all section target_words

Respond with JSON matching this shape, or equivalent Markdown:
{
  "title": "...",
  "sections": [
    {"id": "section_1", "heading": "...", "goal": "...", "target_words": 150}
  ],
  "estimated_total_words": 450
}
""".strip()


def create_outline_agent() -> Agent:
    return Agent(
        name="outline_agent",
        model=create_model(OUTLINE_MODEL),
        instruction=OUTLINE_INSTRUCTION,
        output_key="outline_raw",
    )


outline_agent = create_outline_agent()
