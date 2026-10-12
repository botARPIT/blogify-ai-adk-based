"""Research agent using Tavily tool.

Research output is stored as the agent's raw text under ``research_data``.
There is no domain schema for a research write-up today, so no normalization
node is introduced here — one would be abstraction for its own sake.
"""

from google.adk.agents import Agent

from src.llm.factory import create_model
from src.llm.model_configs import RESEARCH_MODEL
from src.tools.tavily_research import research_topic

RESEARCH_INSTRUCTION = """
For the given topic and outline: {blog_outline}

Use the research_topic tool to gather comprehensive information:
- Key facts and statistics
- Recent developments and trends
- Expert opinions and insights
- Credible sources for citations

The research_topic tool will return structured data with sources.
Store this in the session state for the writer agent to use.
""".strip()


def create_research_agent() -> Agent:
    return Agent(
        name="research_agent",
        model=create_model(RESEARCH_MODEL),
        instruction=RESEARCH_INSTRUCTION,
        tools=[research_topic],
        output_key="research_data",
    )


research_agent = create_research_agent()
