"""Intent classification agent.

The agent decides *what* to do. It emits raw model output under
``intent_raw``; turning that into an :class:`~src.models.schemas.IntentSchema`
is the job of a deterministic workflow node, not of ADK's provider-dependent
``output_schema`` enforcement.
"""

from google.adk.agents import Agent

from src.llm.factory import create_model
from src.llm.model_configs import INTENT_MODEL

INTENT_INSTRUCTION = """
Analyze the user's topic and audience to determine if it's suitable for blog generation.

Classification rules:
- CLEAR: Single, well-defined topic with clear audience
- UNCLEAR_TOPIC: Topic is too vague, ambiguous, or needs clarification
- MULTI_TOPIC: Multiple unrelated topics mixed together
- MISSING_AUDIENCE: Topic is clear but audience is not specified or unclear

Return a JSON object with 'status' and 'message' fields.
""".strip()


def create_intent_agent() -> Agent:
    return Agent(
        name="intent_classifier",
        model=create_model(INTENT_MODEL),
        instruction=INTENT_INSTRUCTION,
        output_key="intent_raw",
    )


intent_agent = create_intent_agent()
