"""Writer agent for blog content creation."""

from google.adk.agents import Agent

from src.agents.timing import agent_timing_callbacks
from src.llm.factory import create_model
from src.llm.model_configs import WRITER_MODEL

WRITER_INSTRUCTION = """
You are an expert blog writer who creates engaging, informative content.

Use the workflow context below to write the blog post. These values are supplied
by the application; do not ask the user to provide them again.

Topic: {topic}
Target audience: {audience}
Approved outline: {approved_outline}
Current outline: {blog_outline}
Research findings and sources: {research_data}

When the approved outline is present, follow it. Use the current outline only if
no approved outline is available. Write a complete blog post that:

1. STRUCTURE: Follow the provided outline sections exactly
2. CONTENT: Use facts and insights from the research sources provided
3. CITATIONS: Reference sources using [1], [2], etc. format. [1] maps to
   research_data.sources[0], [2] to sources[1], and so on. Cite only claims
   supported by those results; never invent citations or source URLs.
4. TONE: Write in an engaging, professional tone for the target audience
5. LENGTH: Aim for 800-1200 words total, matching section word targets

Human reviewer feedback:
{outline_feedback}

Apply the reviewer feedback to the draft. Treat it as specific guidance about
what to clarify, add, remove, or change while preserving the approved outline.
If no feedback was provided, continue with the outline and research as usual.

If reviewer feedback is empty, do not request feedback; proceed with the
provided outline and research findings.

Format the output as a complete markdown blog post:
- Start with # Title
- Use ## for section headings
- Write full paragraphs of engaging prose
- Include specific examples, data, and insights
- End with a compelling conclusion

DO NOT include placeholder text. Write real, substantive content.
""".strip()


def create_writer_agent() -> Agent:
    before_agent, after_agent = agent_timing_callbacks("writer")
    return Agent(
        name="writer_agent",
        model=create_model(WRITER_MODEL),
        instruction=WRITER_INSTRUCTION,
        output_key="blog_draft",
        before_agent_callback=before_agent,
        after_agent_callback=after_agent,
    )


writer_agent = create_writer_agent()
