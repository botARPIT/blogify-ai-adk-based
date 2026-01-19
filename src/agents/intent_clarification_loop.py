"""Intent clarification loop with human approval."""

from typing import Any

from google.adk.agents import LoopAgent

from src.agents.intent_agent import intent_agent


def intent_loop_condition(state: dict[str, Any]) -> bool:
    """
    Continue intent loop while status is not CLEAR and under iteration limit.
    
    Args:
        state: Session state containing intent_result
    
    Returns:
        True if should continue asking for clarification
    """
    intent_result = state.get("intent_result", {})
    status = intent_result.get("status", "")
    
    # Check if human has provided clarification
    human_clarified = state.get("intent_human_clarified", False)
    
    # Continue if not CLEAR and human hasn't provided final input
    return status != "CLEAR" and not human_clarified


# Intent clarification loop (max 3 attempts per blog)
intent_clarification_loop = LoopAgent(
    name="intent_clarification_loop",
    sub_agents=[intent_agent],
    condition=intent_loop_condition,
    max_iterations=3,  # Max 3 clarification attempts
)
