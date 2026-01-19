"""Input sanitization for LLM prompt injection protection."""

import re
from typing import Any

from src.config.logging_config import get_logger

logger = get_logger(__name__)


# Dangerous patterns that indicate prompt injection attempts
INJECTION_PATTERNS = [
    # Direct instruction override attempts
    r"ignore\s+(all\s+)?previous\s+instructions?",
    r"ignore\s+(all\s+)?above\s+instructions?",
    r"disregard\s+(all\s+)?previous",
    r"forget\s+(all\s+)?previous",
    r"override\s+(all\s+)?instructions?",
    
    # Role/identity manipulation
    r"you\s+are\s+now\s+(a|an)",
    r"pretend\s+(you\s+are|to\s+be)",
    r"act\s+as\s+(if|a|an)",
    r"roleplay\s+as",
    r"assume\s+the\s+role",
    
    # System prompt extraction
    r"what\s+(is|are)\s+(your|the)\s+system\s+prompt",
    r"show\s+(me\s+)?(your|the)\s+instructions?",
    r"reveal\s+(your|the)\s+prompt",
    r"print\s+(your|the)\s+system",
    r"output\s+(your|the)\s+instructions?",
    
    # Code execution attempts
    r"execute\s+(this\s+)?code",
    r"run\s+(this\s+)?command",
    r"eval\s*\(",
    r"exec\s*\(",
    r"os\.system",
    r"subprocess",
    
    # Jailbreak patterns
    r"dan\s*(mode)?",
    r"developer\s+mode",
    r"unrestricted\s+mode",
    r"no\s+restrictions?",
    
    # Data exfiltration
    r"api[_\s]?key",
    r"secret[_\s]?key",
    r"password",
    r"credential",
    r"access[_\s]?token",
]

# Compiled patterns for performance
COMPILED_PATTERNS = [re.compile(p, re.IGNORECASE) for p in INJECTION_PATTERNS]


def detect_injection(text: str) -> tuple[bool, list[str]]:
    """
    Detect potential prompt injection attacks.
    
    Args:
        text: Input text to check
        
    Returns:
        Tuple of (is_suspicious, matched_patterns)
    """
    matches = []
    
    for pattern in COMPILED_PATTERNS:
        if pattern.search(text):
            matches.append(pattern.pattern)
    
    if matches:
        logger.warning(
            "injection_detected",
            text_preview=text[:100],
            patterns_matched=len(matches)
        )
    
    return len(matches) > 0, matches


def sanitize_for_llm(text: str, strict: bool = False) -> str:
    """
    Sanitize user input before passing to LLM.
    
    Args:
        text: Raw user input
        strict: If True, remove suspicious content; if False, just escape
        
    Returns:
        Sanitized text safe for LLM consumption
    """
    if not text:
        return ""
    
    # Check for injection attempts
    is_suspicious, matches = detect_injection(text)
    
    if is_suspicious and strict:
        # In strict mode, remove the entire suspicious segment
        for pattern in COMPILED_PATTERNS:
            text = pattern.sub("[REDACTED]", text)
        logger.info("content_sanitized", redactions=len(matches))
    
    # Escape special characters that might be interpreted as instructions
    # But preserve normal punctuation for readability
    text = text.replace("{{", "{ {").replace("}}", "} }")
    
    # Remove potential markdown/code injection
    text = re.sub(r"```[\s\S]*```", "[CODE BLOCK REMOVED]", text)
    
    # Limit excessive repetition (potential DOS)
    text = re.sub(r"(.)\1{20,}", r"\1" * 5, text)
    
    # Normalize whitespace
    text = " ".join(text.split())
    
    return text


def sanitize_topic(topic: str) -> tuple[bool, str, str | None]:
    """
    Sanitize blog topic input.
    
    Args:
        topic: User-provided blog topic
        
    Returns:
        Tuple of (is_valid, sanitized_topic, error_message)
    """
    if not topic or len(topic.strip()) < 10:
        return False, "", "Topic must be at least 10 characters"
    
    if len(topic) > 500:
        return False, "", "Topic must be less than 500 characters"
    
    is_suspicious, matches = detect_injection(topic)
    
    if is_suspicious and len(matches) > 2:
        return False, "", "Topic contains suspicious patterns"
    
    sanitized = sanitize_for_llm(topic, strict=False)
    
    return True, sanitized, None


def sanitize_audience(audience: str | None) -> str:
    """
    Sanitize audience input.
    
    Args:
        audience: User-provided target audience
        
    Returns:
        Sanitized audience string
    """
    if not audience:
        return "general readers"
    
    if len(audience) > 200:
        audience = audience[:200]
    
    is_suspicious, _ = detect_injection(audience)
    
    if is_suspicious:
        return "general readers"
    
    return sanitize_for_llm(audience, strict=True)


def sanitize_feedback(feedback: str | None) -> str | None:
    """
    Sanitize approval/rejection feedback.
    
    Args:
        feedback: User-provided feedback
        
    Returns:
        Sanitized feedback
    """
    if not feedback:
        return None
    
    if len(feedback) > 1000:
        feedback = feedback[:1000]
    
    return sanitize_for_llm(feedback, strict=True)


class SanitizationMiddleware:
    """
    Middleware to sanitize all incoming request data.
    
    Usage in FastAPI:
        app.add_middleware(SanitizationMiddleware)
    """
    
    def __init__(self, app):
        self.app = app
    
    async def __call__(self, scope, receive, send):
        # For now, sanitization is done at the guard level
        # This middleware is a placeholder for future global sanitization
        await self.app(scope, receive, send)
