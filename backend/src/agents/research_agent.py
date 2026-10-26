"""Research agent with a validated evidence hand-off to downstream stages."""

from collections.abc import Callable
from typing import Any

from google.adk.agents import Agent
from google.adk.tools.base_tool import BaseTool
from google.adk.tools.base_toolset import BaseToolset
from google.adk.tools.google_search_tool import google_search

from src.agents.timing import agent_timing_callbacks
from src.llm.config import LLMProvider
from src.llm.factory import create_model
from src.llm.model_configs import RESEARCH_MODEL
from src.tools.tavily_research import research_topic

RESEARCH_INSTRUCTION = """
For the given topic and outline: {blog_outline}

Target audience: {audience}
Requested tone: {tone}

Use the research_topic tool to gather comprehensive information:
- Key facts and statistics
- Recent developments and trends
- Expert opinions and insights
- Credible sources for citations

Call research_topic first. It returns the evidence record that the application
persists for the writer, editor, and final Sources section.

If it reports an error or zero sources and the native google_search tool is
available, use it as a fallback. Never invent a source, URL, statistic, or
claim: include only evidence returned by a research tool.

Return a JSON object only, matching this shape:
{
  "topic": "...",
  "summary": "...",
  "total_sources": 0,
  "sources": [
    {"title": "...", "url": "https://...", "content": "...", "score": 0.0, "provider": "..."}
  ]
}

``total_sources`` must exactly equal the number of sources. Preserve the tool's
source order. The writer and editor may use only this validated evidence.
""".strip()


def create_research_agent() -> Agent:
    before_agent, after_agent = agent_timing_callbacks("research")
    tools: list[Callable[..., Any] | BaseTool | BaseToolset] = [research_topic]
    # ADK's built-in Google Search is a server-side Gemini capability. It does
    # not need a separate Programmable Search credential, but ADK rejects it
    # for OpenAI-compatible/Ollama models, so expose it only when supported.
    if RESEARCH_MODEL.provider is LLMProvider.GOOGLE:
        tools.append(google_search)
    return Agent(
        name="research_agent",
        model=create_model(RESEARCH_MODEL),
        instruction=RESEARCH_INSTRUCTION,
        tools=tools,
        output_key="research_data_raw",
        before_agent_callback=before_agent,
        after_agent_callback=after_agent,
    )


research_agent = create_research_agent()
