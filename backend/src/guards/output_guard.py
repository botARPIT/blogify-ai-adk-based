"""Schema-based output validation for generated blog content."""

from typing import Optional


class OutputGuard:
    """Validates generated blog content using schema rules."""

    MIN_WORD_COUNT = 300
    MIN_SECTIONS = 1

    def validate(self, content: dict) -> tuple[bool, str]:
        """
        Validate generated blog content structure.
        
        Args:
            content: Dict with keys: title, sections, final_content, word_count
            
        Returns:
            tuple[bool, str]: (is_valid, error_message)
        """
        if not content:
            return False, "Content is required"

        if "title" in content:
            title = content.get("title")
            if title is not None and not isinstance(title, str):
                return False, "Title must be a string"
            if title and len(title.strip()) < 1:
                return False, "Title cannot be empty"
            if title and len(title) > 120:
                return False, "Title must not exceed 120 characters"

        word_count = content.get("word_count", 0)
        if not isinstance(word_count, int):
            return False, "Word count must be an integer"
        if word_count < self.MIN_WORD_COUNT:
            return False, f"Content must have at least {self.MIN_WORD_COUNT} words (got {word_count})"

        if "sections" in content:
            sections = content.get("sections")
            if sections is not None:
                if not isinstance(sections, list):
                    return False, "Sections must be a list"
                if len(sections) < self.MIN_SECTIONS:
                    return False, f"Content must have at least {self.MIN_SECTIONS} section"

        if "final_content" in content:
            final_content = content.get("final_content")
            if final_content is not None and not isinstance(final_content, str):
                return False, "Final content must be a string"

        return True, ""


def validate_blog_output(content: dict) -> None:
    """
    Validates blog output and raises ValueError if invalid.
    
    Raises:
        ValueError: If validation fails
    """
    guard = OutputGuard()
    is_valid, error_message = guard.validate(content)
    if not is_valid:
        raise ValueError(error_message)