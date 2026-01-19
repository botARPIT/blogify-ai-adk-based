"""Writer-Editor refinement loop using LoopAgent."""

from typing import Any

from google.adk.agents import LoopAgent

from src.agents.editor_agent import editor_agent
from src.agents.writer_agent import writer_agent


def loop_condition(state: dict[str, Any]) -> bool:
    """
    Continue loop while editor has not approved the blog.
    
    Args:
        state: Session state containing editor_review
    
    Returns:
        True if should continue looping, False if approved
    """
    editor_review = state.get("editor_review", {})
    approved = editor_review.get("approved", False)
    return not approved


# Create writer-editor refinement loop
writer_editor_loop = LoopAgent(
    name="refinement_loop",
    sub_agents=[writer_agent, editor_agent],
    condition=loop_condition,
    max_iterations=3,  # Maximum 3 refinement rounds
)
