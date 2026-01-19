"""Tavily research tool for blog agents."""

import os
from typing import Any

from google.adk.tools import FunctionTool
from tavily import TavilyClient

from src.config.logging_config import get_logger
from src.monitoring.circuit_breaker import CircuitBreaker

logger = get_logger(__name__)

# Lazy initialization - client created on first use
_tavily_client: TavilyClient | None = None
circuit_breaker = CircuitBreaker(name="tavily", failure_threshold=5, recovery_timeout=60)


def _get_tavily_client() -> TavilyClient:
    """Get or create Tavily client singleton."""
    global _tavily_client
    if _tavily_client is None:
        api_key = os.getenv("TAVILY_API_KEY", "")
        if not api_key:
            raise ValueError("TAVILY_API_KEY environment variable not set")
        _tavily_client = TavilyClient(api_key=api_key)
        logger.info("tavily_client_initialized")
    return _tavily_client


async def _tavily_search(topic: str, max_results: int) -> dict[str, Any]:
    """Internal async wrapper for Tavily search."""
    client = _get_tavily_client()
    response = client.search(query=topic, max_results=max_results)
    return response


@FunctionTool
async def research_topic(topic: str, max_results: int = 5) -> str:
    """
    Research a topic using Tavily API with circuit breaker protection.
    
    Args:
        topic: The topic to research
        max_results: Maximum number of results to return
    
    Returns:
        JSON string containing research results
    """
    try:
        logger.info(f"researching_topic", topic=topic, max_results=max_results)
        
        # Use circuit breaker for Tavily API call
        result = await circuit_breaker.call(
            _tavily_search, topic=topic, max_results=max_results
        )
        
        # Extract and format results
        results = result.get("results", [])
        formatted_results = {
            "query": topic,
            "total_results": len(results),
            "sources": [
                {
                    "title": r.get("title", ""),
                    "url": r.get("url", ""),
                    "content": r.get("content", ""),
                    "score": r.get("score", 0.0),
                }
                for r in results
            ],
        }
        
        logger.info(f"research_completed", sources_found=len(results))
        
        import json
        return json.dumps(formatted_results)
        
    except Exception as e:
        logger.error(f"research_failed", error=str(e), topic=topic)
        return json.dumps({"error": str(e), "query": topic, "sources": []})
