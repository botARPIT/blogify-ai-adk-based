"""Intent classification agent."""

from google.adk.agents import Agent
from google.adk.models.google_llm import Gemini

from src.config import INTENT_MODEL, create_retry_config
from src.models.schemas import IntentSchema

# Create intent agent
intent_agent = Agent(
    name="intent_classifier",
    model=Gemini(
        model=INTENT_MODEL.name,
        retry_options=create_retry_config(attempts=INTENT_MODEL.retry_attempts),
        temperature=INTENT_MODEL.temperature,
        max_output_tokens=INTENT_MODEL.max_output_tokens,
    ),
    instruction="""
    Analyze the user's topic and audience to determine if it's suitable for blog generation.
    
    Classification rules:
    - CLEAR: Single, well-defined topic with clear audience
    - UNCLEAR_TOPIC: Topic is too vague, ambiguous, or needs clarification
    - MULTI_TOPIC: Multiple unrelated topics mixed together
    - MISSING_AUDIENCE: Topic is clear but audience is not specified or unclear
    
    Return a JSON object with 'status' and 'message' fields.
    """.strip(),
    output_schema=IntentSchema,
    output_key="intent_result",
)
