"""Services package marker.

Avoid importing service singletons here because some services pull optional ADK
dependencies at import time.
"""

__all__: list[str] = []
