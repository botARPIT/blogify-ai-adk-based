"""Input guardrail plugin for validating user requests."""

from typing import Any

from src.config.logging_config import get_logger

logger = get_logger(__name__)


class InputGuardrail:
    """Input validation guardrail using callback pattern."""

    def __init__(self) -> None:
        self.max_topic_length = 500
        self.max_audience_length = 200
        self.blocked_patterns = ["hack", "exploit", "malicious", "attack"]

    def validate_input(self, topic: str, audience: str | None = None) -> tuple[bool, str]:
        """
        Validate user input before processing.
        
        Args:
            topic: Blog topic from user
            audience: Target audience (optional)
        
        Returns:
            (is_valid, error_message)
        """
        # Check topic length
        if len(topic) > self.max_topic_length:
            return False, f"Topic too long (max {self.max_topic_length} chars)"
        
        # Check audience length
        if audience and len(audience) > self.max_audience_length:
            return False, f"Audience too long (max {self.max_audience_length} chars)"
        
        # Check for empty topic
        if not topic or not topic.strip():
            return False, "Topic cannot be empty"
        
        # Check for blocked patterns (simple content safety)
        topic_lower = topic.lower()
        for pattern in self.blocked_patterns:
            if pattern in topic_lower:
                logger.warning(f"blocked_pattern_detected", pattern=pattern)
                return False, f"Topic contains inappropriate content"
        
        return True, ""

    def before_model_callback(self, callback_context: Any, llm_request: Any) -> None:
        """
        Callback executed before model call (ADK pattern).
        
        Can be used to inject safety checks into the prompt.
        """
        # For now, this is a placeholder for the ADK callback pattern
        # In production, this would modify llm_request.system_instruction
        pass


# Global instance
input_guardrail = InputGuardrail()
