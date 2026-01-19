"""Writer agent for blog content creation."""

from google.adk.agents import Agent
from google.adk.models.google_llm import Gemini

from src.config import WRITER_MODEL, create_retry_config

# Create writer agent (NO tools - uses research data only)
writer_agent = Agent(
    name="writer_agent",
    model=Gemini(
        model=WRITER_MODEL.name,
        retry_options=create_retry_config(attempts=WRITER_MODEL.retry_attempts),
        temperature=WRITER_MODEL.temperature,
        max_output_tokens=WRITER_MODEL.max_output_tokens,
    ),
    instruction="""
    Write an engaging blog post based on:
    - Outline: {blog_outline}
    - Research Data: {research_data}
    
    CRITICAL RULES:
    1. Use ONLY facts from research_data - do NOT make up information
    2. Cite all sources using [1], [2], etc. format
    3. Match target word counts per section from outline
    4. Write in an engaging, informative tone for the target audience
    5. Include specific data, statistics, and examples from research
    
    Structure:
    - Follow the section structure from the outline exactly
    - Each section should meet its target_words goal
    - Include citations throughout the text
    - End with a brief conclusion
    
    Do NOT include a "Sources:" section - the editor will add that.
    """.strip(),
    output_key="blog_draft",
)
