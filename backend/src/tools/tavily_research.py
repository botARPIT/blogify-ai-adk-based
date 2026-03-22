"""Tavily research tool for blog agents with deep research capability."""

import asyncio
import json
import os
import time
from typing import Any

from tavily import TavilyClient

from src.config.logging_config import get_logger
from src.monitoring.circuit_breaker import CircuitBreaker

logger = get_logger(__name__)

# Lazy initialization - client created on first use
_tavily_client: TavilyClient | None = None
circuit_breaker = CircuitBreaker(name="tavily", failure_threshold=5, recovery_timeout=60)


def _get_tavily_client() -> TavilyClient:
    """Get or create Tavily client singleton with API key from environment."""
    global _tavily_client
    if _tavily_client is None:
        api_key = os.getenv("TAVILY_API_KEY", "")
        if not api_key:
            raise ValueError("TAVILY_API_KEY environment variable not set")
        _tavily_client = TavilyClient(api_key=api_key)
        logger.info("tavily_client_initialized")
    return _tavily_client


async def research_topic(topic: str, max_results: int = 5) -> dict[str, Any]:
    """
    Research a topic using Tavily API with deep research capability.
    
    Uses the new Tavily research() method for comprehensive results.
    
    Args:
        topic: The topic to research
        max_results: Maximum number of results to return
    
    Returns:
        Dictionary containing research results and sources
    """
    try:
        logger.info("researching_topic", topic=topic[:50], max_results=max_results)
        
        client = _get_tavily_client()
        
        # Try simple search first (faster, works with basic plan)
        try:
            response = client.search(query=topic, max_results=max_results)
            
            results = response.get("results", [])
            
            formatted_results = {
                "topic": topic,
                "summary": response.get("answer", f"Research results for: {topic}"),
                "total_sources": len(results),
                "sources": [
                    {
                        "title": r.get("title", ""),
                        "url": r.get("url", ""),
                        "content": r.get("content", "")[:500],  # Truncate for storage
                        "score": r.get("score", 0.0),
                    }
                    for r in results
                ],
            }
            
            logger.info("research_completed", sources_found=len(results))
            return formatted_results
            
        except Exception as search_error:
            logger.warning("simple_search_failed", error=str(search_error))
            
            # Fallback: try deep research if available
            try:
                return await _deep_research(client, topic)
            except Exception as deep_error:
                logger.warning("deep_research_not_available", error=str(deep_error))
                
                # Return empty results if all methods fail
                return {
                    "topic": topic,
                    "summary": f"Unable to research: {topic}",
                    "total_sources": 0,
                    "sources": [],
                    "error": str(search_error)
                }
        
    except Exception as e:
        logger.error("research_failed", error=str(e), topic=topic[:50])
        return {
            "topic": topic,
            "summary": f"Research failed for: {topic}",
            "total_sources": 0,
            "sources": [],
            "error": str(e)
        }


async def _deep_research(client: TavilyClient, topic: str) -> dict[str, Any]:
    """
    Perform deep research using Tavily's research() method with polling.
    
    Note: This requires Tavily API plan that supports deep research.
    """
    logger.info("starting_deep_research", topic=topic[:50])
    
    # Start research task
    response = client.research(topic)
    request_id = response.get("request_id")
    
    if not request_id:
        raise ValueError("No request_id returned from research")
    
    # Poll for results with timeout
    max_wait = 120  # Maximum 2 minutes
    poll_interval = 3
    elapsed = 0
    
    while elapsed < max_wait:
        await asyncio.sleep(poll_interval)
        elapsed += poll_interval
        
        result = client.get_research_result(request_id)
        status = result.get("status")
        
        if status == "completed":
            content = result.get("content", "")
            sources = result.get("sources", [])
            
            logger.info("deep_research_completed", sources_count=len(sources))
            
            return {
                "topic": topic,
                "summary": content[:2000] if content else f"Research completed for: {topic}",
                "total_sources": len(sources),
                "sources": [
                    {
                        "title": s.get("title", ""),
                        "url": s.get("url", ""),
                        "content": s.get("content", "")[:500],
                        "score": s.get("score", 0.0),
                    }
                    for s in sources[:10]  # Limit to 10 sources
                ],
            }
            
        elif status == "failed":
            raise ValueError(f"Deep research failed: {result.get('error', 'Unknown error')}")
        
        logger.debug("research_polling", status=status, elapsed=elapsed)
    
    raise TimeoutError(f"Research timed out after {max_wait} seconds")


# ADK Function Tool wrapper for agent use
from google.adk.tools import FunctionTool

@FunctionTool
async def tavily_research_tool(topic: str, max_results: int = 5) -> str:
    """
    Research a topic using Tavily API (ADK tool wrapper).
    
    Args:
        topic: The topic to research
        max_results: Maximum number of results
        
    Returns:
        JSON string with research results
    """
    result = await research_topic(topic, max_results)
    return json.dumps(result)
