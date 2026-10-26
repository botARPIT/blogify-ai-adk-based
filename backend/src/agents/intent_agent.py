"""Safety and clarity gate for the first blog workflow segment.

The agent decides *what* to do. It emits raw model output under
``intent_raw``; turning that into an :class:`~src.models.schemas.IntentSchema`
is the job of a deterministic workflow node, not of ADK's provider-dependent
``output_schema`` enforcement.
"""

from google.adk.agents import Agent

from src.agents.timing import agent_timing_callbacks
from src.llm.factory import create_model
from src.llm.model_configs import INTENT_MODEL

INTENT_INSTRUCTION = """
Decide whether the request is safe and sufficiently specified for blog generation.

Topic: {topic}
Target audience: {audience}
Requested tone: {tone}

Set intent_clear to false when any of the following is true:
- The user requests instructions, planning, or content that would facilitate
  violence, self-harm, criminal wrongdoing, exploitation, hate, or other harm.
- The topic is missing, vague, ambiguous, or combines unrelated requests.
- The target audience is missing, contradictory, or too unclear to write for.
- The requested tone is missing, contradictory, or too unclear to apply.

Set intent_clear to true only when none of those conditions apply.

Return exactly one JSON object and no prose:
{"intent_clear": true, "confidence": between 0 - 1}

or

{"intent_clear": false, "confidence": between 0 - 1}
""".strip()


def create_intent_agent() -> Agent:
    before_agent, after_agent = agent_timing_callbacks("intent")
    return Agent(
        name="intent_classifier",
        model=create_model(INTENT_MODEL),
        instruction=INTENT_INSTRUCTION,
        output_key="intent_raw",
        before_agent_callback=before_agent,
        after_agent_callback=after_agent,
    )


intent_agent = create_intent_agent()
