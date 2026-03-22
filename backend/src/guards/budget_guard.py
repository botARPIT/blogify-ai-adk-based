"""Budget enforcement guard with hard constraints."""

from typing import Any

from src.config.budget_config import budget_settings, get_model_cost
from src.config.logging_config import get_logger

logger = get_logger(__name__)


class BudgetGuard:
    """Budget enforcement with hard token limits (+10-20% buffer)."""

    def __init__(self) -> None:
        self.agent_limits = {
            "intent_classifier": budget_settings.intent_token_limit,
            "outline_agent": budget_settings.outline_token_limit,
            "research_agent": budget_settings.research_token_limit,
            "writer_agent": budget_settings.writer_token_limit,
            "editor_agent": budget_settings.editor_token_limit,
        }

    def check_agent_budget(self, agent_name: str, tokens: int) -> tuple[bool, str]:
        """
        Check if agent stayed within token limit.
        
        Args:
            agent_name: Name of the agent
            tokens: Tokens used
        
        Returns:
            (within_budget, error_message)
        """
        limit = self.agent_limits.get(agent_name, 10000)
        
        if tokens > limit:
            logger.error(
                "agent_budget_exceeded",
                agent=agent_name,
                tokens=tokens,
                limit=limit,
            )
            return False, f"{agent_name} exceeded token limit: {tokens}/{limit}"
        
        return True, ""

    def check_blog_budget(self, total_tokens: int, total_cost: float) -> tuple[bool, str]:
        """
        Check if entire blog stayed within budget.
        
        Args:
            total_tokens: Total tokens used
            total_cost: Total cost in USD
        
        Returns:
            (within_budget, error_message)
        """
        if total_tokens > budget_settings.per_blog_token_budget:
            logger.error(
                "blog_token_budget_exceeded",
                tokens=total_tokens,
                limit=budget_settings.per_blog_token_budget,
            )
            return False, f"Blog token budget exceeded: {total_tokens}/{budget_settings.per_blog_token_budget}"
        
        if total_cost > budget_settings.per_blog_cost_budget:
            logger.error(
                "blog_cost_budget_exceeded",
                cost=total_cost,
                limit=budget_settings.per_blog_cost_budget,
            )
            return False, f"Blog cost budget exceeded: ${total_cost:.4f}/${budget_settings.per_blog_cost_budget}"
        
        return True, ""


# Global instance
budget_guard = BudgetGuard()
