"""Research agent using Tavily with Google search fallback."""

from google.adk.agents import Agent
from google.adk.models.google_llm import Gemini
from google.adk.tools import google_search

from src.config import RESEARCH_MODEL, create_retry_config
from src.tools.tavily_research import research_topic


def create_research_agent() -> Agent:
    return Agent(
        name="research_agent",
        model=Gemini(
            model=RESEARCH_MODEL.name,
            retry_options=create_retry_config(attempts=RESEARCH_MODEL.retry_attempts),
            temperature=RESEARCH_MODEL.temperature,
            max_output_tokens=RESEARCH_MODEL.max_output_tokens,
        ),
        instruction="""Research the topic based on the blog outline: {blog_outline}

        STEP 1 — Conduct Research:
        Call the `research_topic` tool using the main topic and key themes extracted from the outline.

        STEP 2 — Compile and Store:
        Inspect the result returned by the tool. Produce a `research_data` object structured exactly as follows:
          - "summary": a concise paragraph of the most important findings based on the tool's output
          - "sources": a list of objects, each containing "title", "url", and "content" (the snippet/information)
          - "total_sources": the total count of valid sources collected
          - "research_method": "research_topic"

        Return a fully populated `research_data` object. If there is no research data then return "{}".""".strip(),
        tools=[research_topic],
        output_key="research_data",
    )


research_agent = create_research_agent()
