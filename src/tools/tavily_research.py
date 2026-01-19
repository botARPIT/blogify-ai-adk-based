"""Tavily research tool for comprehensive topic research."""

import os
from typing import Any

from google.adk.tools import FunctionTool
from tavily import TavilyClient

from src.config.logging_config import get_logger

logger = get_logger(__name__)

# Initialize Tavily client
tavily_client = TavilyClient(api_key=os.getenv("TAVILY_API_KEY", ""))


@FunctionTool
def research_topic(topic: str, audience: str | None = None, max_results: int = 10) -> dict[str, Any]:
    """
    Research a topic comprehensively using Tavily Search API.
    
    Args:
        topic: The main topic to research
        audience: Optional target audience to focus the research
        max_results: Maximum number of search results (default: 10)
    
    Returns:
        Structured research data with sources and summary
    """
    logger.info(f"researching_topic", topic=topic, audience=audience)
    
    # Build search query
    query = topic
    if audience:
        query += f" for {audience}"
    
    try:
        # Search with Tavily
        results = tavily_client.search(
            query=query,
            search_depth="advanced",  # Deep research mode
            max_results=max_results,
            include_answer=True,  # Get AI-generated summary
            include_raw_content=False,  # We want clean summaries
        )
        
        # Structure the research
        research_data = {
            "topic": topic,
            "summary": results.get("answer", ""),
            "sources": [
                {
                    "title": r["title"],
                    "url": r["url"],
                    "content": r["content"],
                    "score": r.get("score", 0.0),
                }
                for r in results.get("results", [])
            ],
            "total_sources": len(results.get("results", [])),
        }
        
        logger.info(f"research_completed", sources_found=research_data["total_sources"])
        return research_data
        
    except Exception as e:
        logger.error(f"research_failed", error=str(e))
        # Return empty research on failure
        return {
            "topic": topic,
            "summary": f"Research failed: {str(e)}",
            "sources": [],
            "total_sources": 0,
        }
