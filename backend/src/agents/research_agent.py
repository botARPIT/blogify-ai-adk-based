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
        instruction="""
        Research the topic based on the blog outline: {blog_outline}

        STEP 1 — Try Tavily first:
        Call research_topic with the main topic extracted from the outline.
        Inspect the result:
          - If it contains a non-empty "sources" list → use it, proceed to STEP 3.
          - If "sources" is empty, or the result has an "error" key, or total_sources is 0
            → proceed to STEP 2.

        STEP 2 — Fallback to Google Search:
        Use google_search to search for the topic. Run 2–3 targeted queries covering:
          - Key facts and recent developments
          - Expert opinions or statistics
          - Real-world examples relevant to the outline sections
        Collect the returned snippets and URLs as your sources.

        STEP 3 — Compile and store:
        Produce a research_data object with:
          - "summary": a concise paragraph of the most important findings
          - "sources": list of objects, each with "title", "url", and "content" (snippet)
          - "total_sources": count of sources collected
          - "research_method": either "tavily" or "google_search" (whichever was used)

        Always return a populated research_data. Never return empty sources if
        google_search returned results. The writer agent depends on this data.
        """.strip(),
        tools=[research_topic, google_search],
        output_key="research_data",
    )


research_agent = create_research_agent()
