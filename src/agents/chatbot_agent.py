"""Chatbot agent using blog pipeline as AgentTool."""

from google.adk.agents import Agent
from google.adk.models.google_llm import Gemini
from google.adk.tools import AgentTool, FunctionTool

from src.config import CHATBOT_MODEL, create_retry_config
from src.agents.blog_generation_pipeline import blog_pipeline


@FunctionTool
async def generate_blog(topic: str, audience: str | None = None) -> dict:
    """
    Generate a blog post using the blog generation pipeline.
    
    Args:
        topic: Blog topic
        audience: Target audience (optional)
    
    Returns:
        Blog generation result or approval request
    """
    # This would be invoked by the chatbot when user explicitly requests blog generation
    # For now, return a placeholder
    return {
        "status": "initiated",
        "message": "Blog generation started. You will receive approval requests.",
        "topic": topic,
        "audience": audience,
    }


# Chatbot agent with blog generation tool
chatbot_agent = Agent(
    name="chatbot",
    model=Gemini(
        model=CHATBOT_MODEL.name,
        retry_options=create_retry_config(attempts=CHATBOT_MODEL.retry_attempts),
        temperature=CHATBOT_MODEL.temperature,
        max_output_tokens=CHATBOT_MODEL.max_output_tokens,
    ),
    instruction="""
    You are a helpful AI assistant that can answer questions and generate blog posts.
    
    For general queries:
    - Answer helpfully and conversationally
    - Provide accurate information
    - Be friendly and professional
    
    For blog generation requests (EXPLICIT only):
    - User must say "generate blog", "write a blog", "create a blog post", etc.
    - Extract topic and audience from user request
    - Use generate_blog tool to start the pipeline
    - Inform user they will receive approval requests
    
    CRITICAL: ONLY use generate_blog tool when user EXPLICITLY requests blog generation.
    For everything else, just chat normally.
    """.strip(),
    tools=[generate_blog],  # Blog generation as a tool
    output_key="chatbot_response",
)
