"""Output guardrail plugin for validating final blog output."""

from typing import Any

from src.config.logging_config import get_logger
from src.models.schemas import EditorReviewSchema, FinalBlogSchema

logger = get_logger(__name__)


class OutputGuardrail:
    """Output validation guardrail using callback pattern."""

    def __init__(self) -> None:
        self.min_word_count = 300
        self.max_word_count = 5000
        self.min_sources = 1
        self.safety_patterns = ["offensive", "harmful", "inappropriate"]

    def validate_output(self, editor_review: EditorReviewSchema) -> tuple[bool, str]:
        """
        Validate editor output before returning to user.
        
        Args:
            editor_review: Editor's review result
        
        Returns:
            (is_valid, error_message)
        """
        # Must be approved
        if not editor_review.approved:
            return False, "Blog not approved by editor"
        
        # Check final blog exists
        if not editor_review.final_blog or not editor_review.final_blog.strip():
            return False, "Final blog content is empty"
        
        # Check word count
        words = editor_review.final_blog.split()
        word_count = len(words)
        
        if word_count < self.min_word_count:
            return False, f"Blog too short ({word_count} words, min {self.min_word_count})"
        
        if word_count > self.max_word_count:
            return False, f"Blog too long ({word_count} words, max {self.max_word_count})"
        
        # Check sources section exists
        if not editor_review.sources_section or not editor_review.sources_section.strip():
            logger.warning("no_sources_section")
            # Don't fail on this, just warn
        
        # Content safety check
        content_lower = editor_review.final_blog.lower()
        for pattern in self.safety_patterns:
            if pattern in content_lower:
                logger.error(f"unsafe_content_detected", pattern=pattern)
                return False, "Content safety check failed"
        
        return True, ""

    def after_model_callback(self, callback_context: Any, response: Any) -> None:
        """
        Callback executed after model call (ADK pattern).
        
        Can be used to scan output for PII, safety issues, etc.
        """
        # Placeholder for ADK callback pattern
        pass


# Global instance
output_guard = OutputGuardrail()
