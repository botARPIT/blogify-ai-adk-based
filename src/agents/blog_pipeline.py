"""Blog generation pipeline using SequentialAgent pattern."""

from google.adk.agents import Agent

from src.agents.editor_agent import editor_agent
from src.agents.intent_agent import intent_agent
from src.agents.outline_agent import outline_agent
from src.agents.research_agent import research_agent
from src.agents.writer_agent import writer_agent
from src.agents.writer_editor_loop import writer_editor_loop

# Note: ADK doesn't have a built-in SequentialAgent class in the whitepapers
# Instead, we use a Coordinator pattern where a root agent delegates to sub-agents
# For now, we'll create a simple sequential flow using agent chaining

# Create blog generation pipeline
# This will be used as a tool by the chatbot agent
blog_pipeline_agents = [
    intent_agent,
    outline_agent,
    research_agent,
    writer_editor_loop,  # This contains writer + editor in a loop
]

# Export individual agents and the pipeline list
__all__ = [
    "intent_agent",
    "outline_agent",
    "research_agent",
    "writer_agent",
    "editor_agent",
    "writer_editor_loop",
    "blog_pipeline_agents",
]
