"""Research agent using Tav ily tool."""

from google.adk.agents import Agent
from google.adk.models.google_llm import Gemini

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
        For the given topic and outline: {blog_outline}
        
        Use the research_topic tool to gather comprehensive information:
        - Key facts and statistics
        - Recent developments and trends
        - Expert opinions and insights
        - Credible sources for citations
        
        The research_topic tool will return structured data with sources.
        Store this in the session state for the writer agent to use.
        """.strip(),
        tools=[research_topic],
        output_key="research_data",
    )


research_agent = create_research_agent()
