"""Intent clarification loop with human approval."""

from google.adk.agents import LoopAgent

from src.agents.intent_agent import intent_agent

# Intent clarification loop (max 3 attempts per blog)
# The loop will run up to max_iterations times
# Human approval is handled in the pipeline orchestration layer
intent_clarification_loop = LoopAgent(
    name="intent_clarification_loop",
    sub_agents=[intent_agent],
    max_iterations=3,  # Max 3 clarification attempts
)
