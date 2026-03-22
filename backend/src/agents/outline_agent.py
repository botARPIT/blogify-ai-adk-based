"""Blog outline generation agent."""

from google.adk.agents import Agent
from google.adk.models.google_llm import Gemini

from src.config import OUTLINE_MODEL, create_retry_config
from src.models.schemas import OutlineSchema

# Create outline agent
outline_agent = Agent(
    name="outline_agent",
    model=Gemini(
        model=OUTLINE_MODEL.name,
        retry_options=create_retry_config(attempts=OUTLINE_MODEL.retry_attempts),
        temperature=OUTLINE_MODEL.temperature,
        max_output_tokens=OUTLINE_MODEL.max_output_tokens,
    ),
    instruction="""
    Generate a structured blog outline based on the topic and audience from intent result: {intent_result}
    
    Requirements:
    - Title: Compelling, max 120 characters, SEO-friendly
    - Sections: 3-7 sections minimum
    - Each section: id, heading, goal, target_words (80-300 each)
    - Total words: Sum of all section target_words
    
    Output must be a valid JSON matching OutlineSchema.
    """.strip(),
    output_schema=OutlineSchema,
    output_key="blog_outline",
)
