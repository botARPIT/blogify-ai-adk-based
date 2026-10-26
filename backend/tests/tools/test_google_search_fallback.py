from unittest.mock import AsyncMock

import pytest


@pytest.mark.asyncio
async def test_google_search_formats_citation_ready_sources(monkeypatch):
    from src.tools import google_search

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "items": [
                    {
                        "title": "Source title",
                        "link": "https://example.org/source",
                        "snippet": "Useful source snippet",
                    }
                ]
            }

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return False

        get = AsyncMock(return_value=FakeResponse())

    monkeypatch.setenv("GOOGLE_SEARCH_API_KEY", "test-key")
    monkeypatch.setenv("GOOGLE_SEARCH_ENGINE_ID", "test-engine")
    monkeypatch.setattr(google_search.httpx, "AsyncClient", lambda **_kwargs: FakeClient())

    result = await google_search.google_search_topic("test topic", max_results=20)

    assert result["provider"] == "google_custom_search"
    assert result["total_sources"] == 1
    assert result["sources"][0]["url"] == "https://example.org/source"
    assert result["sources"][0]["provider"] == "google_custom_search"
    FakeClient.get.assert_awaited_once()
    assert FakeClient.get.await_args.kwargs["params"]["num"] == 10


@pytest.mark.asyncio
async def test_google_search_requires_its_own_credentials(monkeypatch):
    from src.tools.google_search import google_search_topic

    monkeypatch.delenv("GOOGLE_SEARCH_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_SEARCH_ENGINE_ID", raising=False)

    with pytest.raises(ValueError, match="GOOGLE_SEARCH_API_KEY"):
        await google_search_topic("test topic")


@pytest.mark.asyncio
async def test_tavily_failure_returns_no_fabricated_sources(monkeypatch):
    from src.tools import tavily_research

    class BrokenTavilyClient:
        def search(self, **_kwargs):
            raise RuntimeError("Tavily unavailable")

        def research(self, *_args):
            raise RuntimeError("Deep research unavailable")

    monkeypatch.setattr(tavily_research, "_get_tavily_client", lambda: BrokenTavilyClient())
    result = await tavily_research.research_topic("test topic", max_results=3)
    assert result["total_sources"] == 0
    assert result["sources"] == []
    assert result["error"] == "Tavily: RuntimeError"


@pytest.mark.parametrize("provider,expected_tools", [("google", 2), ("ollama", 1)])
def test_research_agent_only_exposes_native_search_for_google(monkeypatch, provider, expected_tools):
    from dataclasses import replace
    from src.agents import research_agent
    from src.llm.config import LLMProvider

    monkeypatch.setattr(research_agent, "RESEARCH_MODEL", replace(
        research_agent.RESEARCH_MODEL, provider=LLMProvider(provider),
    ))
    monkeypatch.setattr(research_agent, "create_model", lambda _config: "gemini-2.5-flash")
    agent = research_agent.create_research_agent()
    assert len(agent.tools) == expected_tools
    assert "google_search" in research_agent.RESEARCH_INSTRUCTION
    assert "zero sources" in research_agent.RESEARCH_INSTRUCTION
