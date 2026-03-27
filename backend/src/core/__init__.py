"""Core package for essential system utilities."""

from importlib import import_module

__all__ = [
    "RuntimeManager",
    "ServiceCheck",
    "StartupCheckError",
    "StartupReport",
    "run_startup_checks",
    "runtime_manager",
]


def __getattr__(name: str):
    if name in __all__:
        startup = import_module("src.core.startup")
        return getattr(startup, name)
    raise AttributeError(f"module 'src.core' has no attribute {name!r}")
