"""Tavily research tool for blog agents with deep research capability."""

import asyncio
import json
import os
from typing import Any

from google.adk.tools.function_tool import FunctionTool
from google.adk.tools.tool_context import ToolContext
from tavily import TavilyClient  # type: ignore[import-untyped]

from src.config.logging_config import get_logger
from src.core.workflow_state_keys import RESEARCH_TOOL_DATA_KEY
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


async def research_topic(
    topic: str,
    max_results: int = 5,
    tool_context: ToolContext | None = None,
) -> dict[str, Any]:
    """
    Research a topic using Tavily API with deep research capability.

    Uses the new Tavily research() method for comprehensive results.

    Args:
        topic: The topic to research
        max_results: Maximum number of results to return

    Returns:
        Dictionary containing research results and sources
    """
    logger.info("researching_topic", topic=topic[:50], max_results=max_results)
    client: TavilyClient | None = None
    tavily_error: Exception | None = None

    try:
        client = _get_tavily_client()
        response = client.search(query=topic, max_results=max_results)
        results = response.get("results", [])
        sources = [
            {
                "title": result.get("title", ""),
                "url": result.get("url", ""),
                "content": result.get("content", "")[:500],
                "score": result.get("score", 0.0),
                "provider": "tavily",
            }
            for result in results
            if result.get("url")
        ]
        if sources:
            logger.info("research_completed", sources_found=len(sources), provider="tavily")
            return _capture_tool_result(tool_context, {
                "topic": topic,
                "summary": response.get("answer") or f"Research results for: {topic}",
                "total_sources": len(sources),
                "sources": sources,
                "provider": "tavily",
            })
        tavily_error = ValueError("Tavily returned no usable sources")
    except Exception as exc:
        tavily_error = exc
        logger.warning("tavily_search_failed", error=str(exc))

    if client is not None:
        try:
            return _capture_tool_result(tool_context, await _deep_research(client, topic))
        except Exception as deep_error:
            logger.warning("deep_research_not_available", error=str(deep_error))

    error = f"Tavily: {type(tavily_error).__name__}"
    logger.error("research_failed", error=error, topic=topic[:50])
    return _capture_tool_result(tool_context, {
        "topic": topic,
        "summary": f"Research failed for: {topic}",
        "total_sources": 0,
        "sources": [],
        "provider": "tavily",
        "error": error,
    })


def _capture_tool_result(
    tool_context: ToolContext | None,
    result: dict[str, Any],
) -> dict[str, Any]:
    """Expose the exact tool payload to the deterministic workflow node."""
    if tool_context is not None:
        tool_context.state[RESEARCH_TOOL_DATA_KEY] = result
    return result


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
