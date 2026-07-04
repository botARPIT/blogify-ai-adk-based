"""Budget configuration — pricing and reservation constants."""

from typing import Final

# Model pricing per 1000 tokens (USD)
MODEL_PRICING: Final[dict[str, float]] = {
    "gemini-2.5-flash-lite": 0.00001,
    "gemini-2.5-flash": 0.00002,
    "gemini-2.5-pro": 0.00004,
}

# Pre-flight reservation: tokens estimated for a full blog generation.
# Used by check_and_reserve() to hold budget before the pipeline runs.
ESTIMATED_TOKENS_PER_BLOG = 50_000


def get_model_cost(model: str, tokens: int) -> float:
    """Calculate cost for given model and token count."""
    price_per_1k = MODEL_PRICING.get(model, MODEL_PRICING["gemini-2.5-flash"])
    return (tokens / 1000) * price_per_1k
