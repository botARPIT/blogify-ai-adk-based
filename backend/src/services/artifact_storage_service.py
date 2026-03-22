"""ArtifactStorageService — stores full agent prompt/response artifacts.

Phase 6: LocalArtifactStore for development; GCSArtifactStore to be added later.

Artifacts are keyed by:
    {base_dir}/{session_id}/{agent_run_id}/{prompt|response}.txt
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from pathlib import Path


class ArtifactStore(ABC):
    """Abstract artifact storage interface."""

    @abstractmethod
    async def write(self, uri: str, content: str) -> str:
        """Write content to the store. Returns the artifact URI."""
        ...

    @abstractmethod
    async def read(self, uri: str) -> str:
        """Read content from the store."""
        ...

    def build_uri(self, session_id: int, run_id: int, artifact_type: str) -> str:
        """Build a deterministic URI for an artifact."""
        return f"local://{session_id}/{run_id}/{artifact_type}.txt"


class LocalArtifactStore(ArtifactStore):
    """Stores artifacts as text files under {base_dir}/{session_id}/{run_id}/."""

    def __init__(self, base_dir: str = "./artifacts") -> None:
        self._base_dir = Path(base_dir)
        self._base_dir.mkdir(parents=True, exist_ok=True)

    def _resolve_path(self, uri: str) -> Path:
        # uri format: local://{session_id}/{run_id}/{artifact_type}.txt
        relative = uri.removeprefix("local://")
        return self._base_dir / relative

    async def write(self, uri: str, content: str) -> str:
        path = self._resolve_path(uri)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return uri

    async def read(self, uri: str) -> str:
        path = self._resolve_path(uri)
        if not path.exists():
            return ""
        return path.read_text(encoding="utf-8")


class ArtifactStorageService:
    """Coordinates artifact persistence for agent runs."""

    def __init__(self, store: ArtifactStore) -> None:
        self._store = store

    async def save_prompt(
        self,
        session_id: int,
        run_id: int,
        prompt_text: str,
    ) -> str:
        uri = self._store.build_uri(session_id, run_id, "prompt")
        return await self._store.write(uri, prompt_text)

    async def save_response(
        self,
        session_id: int,
        run_id: int,
        response_text: str,
    ) -> str:
        uri = self._store.build_uri(session_id, run_id, "response")
        return await self._store.write(uri, response_text)

    async def load_prompt(self, session_id: int, run_id: int) -> str:
        uri = self._store.build_uri(session_id, run_id, "prompt")
        return await self._store.read(uri)

    async def load_response(self, session_id: int, run_id: int) -> str:
        uri = self._store.build_uri(session_id, run_id, "response")
        return await self._store.read(uri)


# Default singleton (LocalArtifactStore for dev)
_default_store: ArtifactStorageService | None = None


def get_artifact_service(base_dir: str = "./artifacts") -> ArtifactStorageService:
    global _default_store
    if _default_store is None:
        _default_store = ArtifactStorageService(LocalArtifactStore(base_dir))
    return _default_store
