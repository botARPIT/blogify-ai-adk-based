"""Writer-Editor refinement loop using LoopAgent."""

from google.adk.agents import LoopAgent

from src.agents.editor_agent import editor_agent
from src.agents.writer_agent import writer_agent

# Create writer-editor refinement loop
# The loop will alternate between writer and editor up to max_iterations times
# The editor's approval decision is captured in the output
writer_editor_loop = LoopAgent(
    name="refinement_loop",
    sub_agents=[writer_agent, editor_agent],
    max_iterations=3,  # Maximum 3 refinement rounds
)
