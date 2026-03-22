"""Workers package marker.

Avoid importing worker modules here so package import stays cheap and does not
pull optional ADK dependencies until the worker actually runs.
"""

__all__: list[str] = []
