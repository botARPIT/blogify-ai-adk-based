"""Validation policy with semantic, business rule, and quality checks."""

from typing import Any

from src.config.logging_config import get_logger
from src.models.schemas import EditorReviewSchema, IntentSchema, OutlineSchema, ResearchDataSchema

logger = get_logger(__name__)


class ValidationError(Exception):
    """Custom validation error."""

    pass


class ValidationPolicy:
    """Validation policy for agent outputs with retry support."""

    def __init__(self, max_retries: int = 2) -> None:
        self.max_retries = max_retries

    def validate_intent(self, intent_result: IntentSchema, topic: str) -> tuple[bool, str]:
        """
        Validate intent classification output.
        
        Checks:
        - Status is one of valid values
        - Message is meaningful (not empty)
        - Topic relevance (semantic)
        """
        # Business rule: status must be valid
        valid_statuses = ["CLEAR", "UNCLEAR_TOPIC", "MULTI_TOPIC", "MISSING_AUDIENCE"]
        if intent_result.status not in valid_statuses:
            return False, f"Invalid status: {intent_result.status}"

        # Semantic: message should be non-empty and relevant
        if not intent_result.message or len(intent_result.message.strip()) < 10:
            return False, "Message too short or empty"

        # Quality: message should not be generic
        generic_phrases = ["error", "unknown", "failed"]
        if any(phrase in intent_result.message.lower() for phrase in generic_phrases):
            return False, "Message appears to be an error message rather than classification"

        return True, ""

    def validate_outline(self, outline: OutlineSchema) -> tuple[bool, str]:
        """
        Validate outline output.
        
        Checks:
        - Title length and quality
        - Section count and structure
        - Word count consistency
        - No duplicate section IDs
        """
        # Business rule: title length
        if len(outline.title) > 120:
            return False, f"Title too long: {len(outline.title)} chars (max 120)"

        if len(outline.title) < 10:
            return False, "Title too short (min 10 chars)"

        # Business rule: section count
        if not (3 <= len(outline.sections) <= 7):
            return False, f"Section count {len(outline.sections)} not in range [3, 7]"

        # Semantic: no duplicate section IDs
        section_ids = [s.id for s in outline.sections]
        if len(section_ids) != len(set(section_ids)):
            return False, "Duplicate section IDs found"

        # Business rule: word count consistency
        calculated_total = sum(s.target_words for s in outline.sections)
        if calculated_total != outline.estimated_total_words:
            return (
                False,
                f"Word count mismatch: sum={calculated_total}, estimated={outline.estimated_total_words}",
            )

        # Quality: each section must have meaningful content
        for section in outline.sections:
            if not section.heading or len(section.heading.strip()) < 3:
                return False, f"Section {section.id} has invalid heading"
            if not section.goal or len(section.goal.strip()) < 10:
                return False, f"Section {section.id} has invalid goal"

        return True, ""

    def validate_research(self, research: ResearchDataSchema) -> tuple[bool, str]:
        """
        Validate research data.
        
        Checks:
        - Has at least one source
        - Sources have valid URLs and content
        - Summary is not empty
        """
        # Business rule: must have sources
        if research.total_sources == 0 or not research.sources:
            return False, "No research sources found"

        # Semantic: sources must have valid structure
        for idx, source in enumerate(research.sources):
            if not source.url or not source.url.startswith("http"):
                return False, f"Source {idx} has invalid URL"
            if not source.content or len(source.content.strip()) < 50:
                return False, f"Source {idx} has insufficient content"

        # Quality: summary should be meaningful
        if not research.summary or len(research.summary.strip()) < 100:
            return False, "Research summary too short or empty"

        return True, ""

    def validate_blog_draft(
        self, blog_draft: str, outline: OutlineSchema, research: ResearchDataSchema
    ) -> tuple[bool, str]:
        """
        Validate blog draft from writer.
        
        Checks:
        - Word count in acceptable range
        - Citations exist and match research sources
        - No repetitive content
        - Coherent structure
        """
        # Business rule: word count
        words = blog_draft.split()
        word_count = len(words)

        if word_count < 300:
            return False, f"Blog too short: {word_count} words (min 300)"

        if word_count > 5000:
            return False, f"Blog too long: {word_count} words (max 5000)"

        # Semantic: citations should reference actual research
        import re

        citations = re.findall(r"\[(\d+)\]", blog_draft)
        unique_citations = set(citations)

        if not unique_citations:
            return False, "No citations found in blog draft"

        # Check if citation numbers are reasonable
        max_citation = max(int(c) for c in unique_citations)
        if max_citation > research.total_sources:
            return (
                False,
                f"Citation [{max_citation}] exceeds available sources ({research.total_sources})",
            )

        # Quality: check for excessive repetition (same sentence appearing multiple times)
        sentences = blog_draft.split(".")
        sentence_counts = {}
        for sentence in sentences:
            clean = sentence.strip().lower()
            if len(clean) > 20:  # Only check substantial sentences
                sentence_counts[clean] = sentence_counts.get(clean, 0) + 1

        repeated = [s for s, count in sentence_counts.items() if count > 2]
        if repeated:
            return False, "Excessive content repetition detected"

        return True, ""

    def validate_editor_review(
        self, review: EditorReviewSchema, outline: OutlineSchema
    ) -> tuple[bool, str]:
        """
        Validate editor review output.
        
        Checks:
        - Approval decision is valid
        - If approved, final_blog exists
        - If not approved, feedback exists
        - Sources section is formatted correctly
        """
        # Business rule: if approved, must have final blog
        if review.approved and (not review.final_blog or len(review.final_blog.strip()) < 300):
            return False, "Approved but final_blog is empty or too short"

        # Business rule: if not approved, must have feedback
        if not review.approved and (not review.feedback or len(review.feedback.strip()) < 10):
            return False, "Rejected but feedback is empty or too short"

        # Semantic: sources section should exist if approved
        if review.approved and (
            not review.sources_section or len(review.sources_section.strip()) < 20
        ):
            return False, "Approved but sources_section is missing or too short"

        # Quality: sources section should have proper formatting
        if review.approved and "sources" not in review.sources_section.lower():
            return False, "Sources section missing 'Sources' heading"

        return True, ""


# Global instance
validation_policy = ValidationPolicy(max_retries=2)
