"""Schema-based input validation for blog generation requests."""


class InputGuard:
    """Validates blog generation input using schema rules (not keyword matching)."""

    TOPIC_MIN_LENGTH = 3
    TOPIC_MAX_LENGTH = 500
    AUDIENCE_MAX_LENGTH = 255
    TONE_MAX_LENGTH = 100

    def validate(
        self,
        topic: str,
        audience: str | None = None,
        tone: str | None = None,
    ) -> tuple[bool, str]:
        """
        Validate blog generation input using schema rules.

        Returns:
            tuple[bool, str]: (is_valid, error_message)
        """
        if not topic or not isinstance(topic, str):
            return False, "Topic is required and must be a string"

        topic_cleaned = topic.strip()
        if len(topic_cleaned) < self.TOPIC_MIN_LENGTH:
            return False, f"Topic must be at least {self.TOPIC_MIN_LENGTH} characters long"

        if len(topic_cleaned) > self.TOPIC_MAX_LENGTH:
            return False, f"Topic must not exceed {self.TOPIC_MAX_LENGTH} characters"

        if not topic_cleaned.replace(" ", "").replace("-", "").replace("_", "").isalnum():
            return False, "Topic contains invalid characters"

        if audience is not None:
            if not isinstance(audience, str):
                return False, "Audience must be a string"
            if len(audience.strip()) > self.AUDIENCE_MAX_LENGTH:
                return False, f"Audience must not exceed {self.AUDIENCE_MAX_LENGTH} characters"

        if tone is not None:
            if not isinstance(tone, str):
                return False, "Tone must be a string"
            if len(tone.strip()) > self.TONE_MAX_LENGTH:
                return False, f"Tone must not exceed {self.TONE_MAX_LENGTH} characters"

        return True, ""


def validate_generate_input(
    topic: str,
    audience: str | None = None,
    tone: str | None = None,
) -> None:
    """
    Validates and raises HTTPException if invalid.

    Raises:
        ValueError: If validation fails
    """
    guard = InputGuard()
    is_valid, error_message = guard.validate(topic, audience, tone)
    if not is_valid:
        raise ValueError(error_message)
