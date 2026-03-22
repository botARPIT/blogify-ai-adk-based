"""Agents package — ADK agent definitions.

Agent *instances* (chatbot_agent, blog_pipeline, …) are intentionally NOT
imported here. They require google-adk to be installed and must be created
inside the API / worker lifespan, not at module-import time.

To get an agent instance use the per-module singletons directly, e.g.:

    from src.agents.pipeline import blog_pipeline
    from src.agents.intent_agent import intent_agent
"""

__all__: list[str] = []
