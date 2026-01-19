"""Writer agent for blog content creation."""

from google.adk.agents import Agent
from google.adk.models.google_llm import Gemini

from src.config import WRITER_MODEL, create_retry_config

# Create writer agent - generates full blog content based on prompts
writer_agent = Agent(
    name="writer_agent",
    model=Gemini(
        model=WRITER_MODEL.name,
        retry_options=create_retry_config(attempts=WRITER_MODEL.retry_attempts),
        temperature=WRITER_MODEL.temperature,
        max_output_tokens=WRITER_MODEL.max_output_tokens,
    ),
    instruction="""
    You are an expert blog writer who creates engaging, informative content.
    
    When given a topic, outline, and research data, write a complete blog post that:
    
    1. STRUCTURE: Follow the provided outline sections exactly
    2. CONTENT: Use facts and insights from the research sources provided
    3. CITATIONS: Reference sources using [1], [2], etc. format
    4. TONE: Write in an engaging, professional tone for the target audience
    5. LENGTH: Aim for 800-1200 words total, matching section word targets
    
    Format the output as a complete markdown blog post:
    - Start with # Title
    - Use ## for section headings
    - Write full paragraphs of engaging prose
    - Include specific examples, data, and insights
    - End with a compelling conclusion
    
    DO NOT include placeholder text. Write real, substantive content.
    """.strip(),
    output_key="blog_draft",
)
