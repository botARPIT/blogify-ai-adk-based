"""Shared service-layer exception types."""


class InsufficientBudgetError(Exception):
    """Raised when a user's available budget is below the required reservation."""


class DailyBlogLimitExceededError(Exception):
    """Raised when a user has consumed all blog-generation slots for the UTC day."""

    def __init__(self, daily_limit: int) -> None:
        self.daily_limit = daily_limit
        super().__init__(f"Daily blog generation limit reached ({daily_limit} per UTC day).")


class SessionTerminalError(Exception):
    """Raised when an idempotency key maps to a session that is already in a terminal state.

    The caller (API route) should return HTTP 409 with error_code=SESSION_TERMINAL
    so the frontend can generate a new idempotency key and retry as a fresh request.
    """
