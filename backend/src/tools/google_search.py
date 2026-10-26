"""Google Programmable Search fallback for research agents."""

from __future__ import annotations

import os
from typing import Any

import httpx

from src.config.logging_config import get_logger

logger = get_logger(__name__)
GOOGLE_CUSTOM_SEARCH_URL = "https://www.googleapis.com/customsearch/v1"


async def google_search_topic(topic: str, max_results: int = 5) -> dict[str, Any]:
    """Search Google when Tavily is unavailable and return citation-ready sources.

    Configure ``GOOGLE_SEARCH_API_KEY`` and ``GOOGLE_SEARCH_ENGINE_ID`` for an
    existing Google Custom Search JSON API account. This is separate from the
    ``GOOGLE_API_KEY`` used by Gemini models.
    """
    api_key = os.getenv("GOOGLE_SEARCH_API_KEY", "").strip()
    engine_id = os.getenv("GOOGLE_SEARCH_ENGINE_ID", "").strip()
    if not api_key or not engine_id:
        raise ValueError(
            "Google Search fallback requires GOOGLE_SEARCH_API_KEY and "
            "GOOGLE_SEARCH_ENGINE_ID"
        )

    params = {
        "key": api_key,
        "cx": engine_id,
        "q": topic,
        "num": min(max(int(max_results), 1), 10),
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(GOOGLE_CUSTOM_SEARCH_URL, params=params)
        response.raise_for_status()
        payload = response.json()

    items = payload.get("items") or []
    sources = [
        {
            "title": item.get("title", ""),
            "url": item.get("link", ""),
            "content": item.get("snippet", "")[:500],
            "score": 0.0,
            "provider": "google_custom_search",
        }
        for item in items
        if item.get("link")
    ]
    logger.info("google_search_completed", topic=topic[:50], sources_found=len(sources))
    return {
        "topic": topic,
        "summary": f"Google Search results for: {topic}",
        "total_sources": len(sources),
        "sources": sources,
        "provider": "google_custom_search",
    }
