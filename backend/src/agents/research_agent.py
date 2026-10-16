"""Research agent using Tavily tool.

Research output is stored as the agent's raw text under ``research_data``.
There is no domain schema for a research write-up today, so no normalization
node is introduced here — one would be abstraction for its own sake.
"""

from google.adk.agents import Agent

from src.agents.timing import agent_timing_callbacks
from src.llm.factory import create_model
from src.llm.model_configs import RESEARCH_MODEL
from src.tools.google_search import google_search_topic
from src.tools.tavily_research import research_topic

RESEARCH_INSTRUCTION = """
For the given topic and outline: {blog_outline}

Use the research_topic tool to gather comprehensive information:
- Key facts and statistics
- Recent developments and trends
- Expert opinions and insights
- Credible sources for citations

Call research_topic first. If it reports an error or returns zero sources, call
google_search_topic as a fallback. Use source titles, URLs, and snippets returned
by either tool; do not invent citations. Preserve the results and source order
in the research data for the writer and editor agents.
""".strip()


def create_research_agent() -> Agent:
    before_agent, after_agent = agent_timing_callbacks("research")
    return Agent(
        name="research_agent",
        model=create_model(RESEARCH_MODEL),
        instruction=RESEARCH_INSTRUCTION,
        tools=[research_topic, google_search_topic],
        output_key="research_data",
        before_agent_callback=before_agent,
        after_agent_callback=after_agent,
    )


research_agent = create_research_agent()
