"""API package marker.

Do not import the FastAPI app here; importing `src.api` should not construct the
entire application or pull optional ADK dependencies into unrelated code paths.
"""

__all__: list[str] = []
