"""Cost tracking system with per-agent and per-blog aggregation."""

from dataclasses import dataclass, field
from typing import Any

from src.config import get_model_cost
from src.config.logging_config import get_logger

logger = get_logger(__name__)


@dataclass
class AgentCost:
    """Cost record for single agent invocation."""

    agent_name: str
    model_name: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cost_usd: float
    latency_ms: int | None = None


@dataclass
class BlogCostSummary:
    """Aggregated cost summary for entire blog."""

    session_id: str
    total_tokens: int = 0
    total_cost_usd: float = 0.0
    agent_costs: list[AgentCost] = field(default_factory=list)

    def add_agent_cost(self, cost: AgentCost) -> None:
        """Add agent cost to summary."""
        self.agent_costs.append(cost)
        self.total_tokens += cost.total_tokens
        self.total_cost_usd += cost.cost_usd


class CostTracker:
    """Track costs per agent invocation using callbacks."""

    def __init__(self) -> None:
        self.blog_costs: dict[str, BlogCostSummary] = {}

    def extract_usage(self, usage_metadata: Any) -> dict[str, int]:
        """
        Extract token usage from ADK usage_metadata.
        
        According to whitepapers, key field is 'token_count'.
        """
        if not usage_metadata:
            return {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

        # Extract based on whitepaper documentation
        prompt_tokens = getattr(usage_metadata, "prompt_token_count", 0) or 0
        completion_tokens = getattr(usage_metadata, "candidates_token_count", 0) or 0
        total_tokens = getattr(usage_metadata, "total_token_count", 0) or (
            prompt_tokens + completion_tokens
        )

        return {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
        }

    def track_agent_cost(
        self,
        session_id: str,
        agent_name: str,
        model_name: str,
        usage_metadata: Any,
        latency_ms: int | None = None,
    ) -> AgentCost:
        """
        Track cost for single agent invocation.
        
        Args:
            session_id: Blog session ID
            agent_name: Name of the agent
            model_name: Model used
            usage_metadata: Usage metadata from ADK response
            latency_ms: Optional latency in milliseconds
        
        Returns:
            AgentCost record
        """
        # Extract usage
        usage = self.extract_usage(usage_metadata)

        # Calculate cost
        cost_usd = get_model_cost(model_name, usage["total_tokens"])

        # Create cost record
        agent_cost = AgentCost(
            agent_name=agent_name,
            model_name=model_name,
            prompt_tokens=usage["prompt_tokens"],
            completion_tokens=usage["completion_tokens"],
            total_tokens=usage["total_tokens"],
            cost_usd=cost_usd,
            latency_ms=latency_ms,
        )

        # Add to blog summary
        if session_id not in self.blog_costs:
            self.blog_costs[session_id] = BlogCostSummary(session_id=session_id)

        self.blog_costs[session_id].add_agent_cost(agent_cost)

        logger.info(
            "agent_cost_tracked",
            session_id=session_id,
            agent=agent_name,
            tokens=usage["total_tokens"],
            cost_usd=cost_usd,
        )

        return agent_cost

    def get_blog_cost(self, session_id: str) -> BlogCostSummary | None:
        """Get cost summary for a blog session."""
        return self.blog_costs.get(session_id)


# Global instance
cost_tracker = CostTracker()
