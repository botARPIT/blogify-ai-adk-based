"""Dependency-neutral keys shared by tools and workflow normalization."""

from typing import Final

# Captures the exact payload returned by research_topic during one invocation.
# The workflow normalizes it into durable research_data before persistence.
RESEARCH_TOOL_DATA_KEY: Final = "research_tool_data"

__all__ = ["RESEARCH_TOOL_DATA_KEY"]
