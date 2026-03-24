"""Backend entrypoint for the FastAPI application."""

import os
import sys

# Add the current directory to sys.path to resolve 'src' imports
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

from src.api.main import app

__all__ = ["app"]
