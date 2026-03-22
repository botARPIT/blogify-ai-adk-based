"""Budget configuration for agents and users."""

import os
from typing import Final

from pydantic_settings import BaseSettings, SettingsConfigDict


class BudgetSettings(BaseSettings):
    """Budget settings loaded from environment."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Global budget limits (USD per day)
    global_daily_budget: float = 100.00

    # Per-blog budget limits
    per_blog_token_budget: int = 10000  # Total tokens across all agents
    per_blog_cost_budget: float = 0.05  # USD

    # Per-user budget limits
    per_user_daily_budget: float = 1.00  # USD per day
    per_user_blogs_per_day: int = 4  # Max blogs per user per day

    # Per-agent token budgets (expected usage)
    intent_token_budget: int = 500
    outline_token_budget: int = 2000
    research_token_budget: int = 300
    writer_token_budget: int = 3000
    editor_token_budget: int = 2000

    # Hard limits (budget + 10-20% buffer for soft constraint enforcement)
    @property
    def intent_token_limit(self) -> int:
        return int(self.intent_token_budget * 1.2)

    @property
    def outline_token_limit(self) -> int:
        return int(self.outline_token_budget * 1.2)

    @property
    def research_token_limit(self) -> int:
        return int(self.research_token_budget * 1.2)

    @property
    def writer_token_limit(self) -> int:
        return int(self.writer_token_budget * 1.2)

    @property
    def editor_token_limit(self) -> int:
        return int(self.editor_token_budget * 1.2)


# Global instance
budget_settings = BudgetSettings()

# Model pricing per 1000 tokens (USD)
MODEL_PRICING: Final[dict[str, float]] = {
    "gemini-2.5-flash-lite": 0.00001,
    "gemini-2.5-flash": 0.00002,
    "gemini-2.5-pro": 0.00004,
}


def get_model_cost(model: str, tokens: int) -> float:
    """Calculate cost for given model and token count."""
    price_per_1k = MODEL_PRICING.get(model, MODEL_PRICING["gemini-2.5-flash"])
    return (tokens / 1000) * price_per_1k

