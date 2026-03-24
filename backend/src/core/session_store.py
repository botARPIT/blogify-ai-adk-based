"""Redis-backed session store for ADK agents.

Replaces InMemorySessionService to enable horizontal scaling.
Sessions are stored in Redis with TTL for automatic cleanup.
"""

import json
from datetime import datetime
from typing import Any

from google.adk.events import Event
from google.adk.sessions import BaseSessionService, Session
from google.adk.sessions.base_session_service import ListSessionsResponse
from src.config.logging_config import get_logger
from src.core.redis_pool import get_redis_client

logger = get_logger(__name__)


class RedisSessionStore:
    """
    Redis-backed session store for ADK agent sessions.
    
    Features:
    - Persistent across application restarts
    - Shared across multiple instances
    - Automatic TTL-based cleanup
    - Atomic operations
    """
    
    SESSION_PREFIX = "adk:session:"
    SESSION_TTL = 86400  # 24 hours
    
    def __init__(self):
        pass

    async def _get_client(self):
        """Return a Redis client from the shared pool."""
        return get_redis_client()
    
    async def create_session(
        self,
        app_name: str,
        user_id: str,
        session_id: str | None = None,
        initial_state: dict | None = None,
    ) -> dict:
        """
        Create a new session.
        
        Args:
            app_name: Application name
            user_id: User identifier
            session_id: Optional session ID (generated if not provided)
            initial_state: Initial state data
            
        Returns:
            Session object with id and metadata
        """
        import uuid
        
        client = await self._get_client()
        
        if session_id is None:
            session_id = str(uuid.uuid4())
        
        session = {
            "id": session_id,
            "app_name": app_name,
            "user_id": user_id,
            "state": initial_state or {},
            "events": [],
            "created_at": datetime.utcnow().isoformat(),
            "updated_at": datetime.utcnow().isoformat(),
        }
        
        key = f"{self.SESSION_PREFIX}{session_id}"
        await client.set(key, json.dumps(session), ex=self.SESSION_TTL)
        
        logger.info("session_created", session_id=session_id, user_id=user_id)
        
        return session
    
    async def get_session(
        self,
        app_name: str,
        user_id: str,
        session_id: str,
    ) -> dict | None:
        """
        Get an existing session.
        
        Args:
            app_name: Application name
            user_id: User identifier
            session_id: Session ID
            
        Returns:
            Session object or None if not found
        """
        client = await self._get_client()
        
        key = f"{self.SESSION_PREFIX}{session_id}"
        data = await client.get(key)
        
        if data is None:
            return None
        
        session = json.loads(data)
        
        # Verify ownership
        if session.get("user_id") != user_id or session.get("app_name") != app_name:
            logger.warning(
                "session_access_denied",
                session_id=session_id,
                requested_user=user_id,
                actual_user=session.get("user_id"),
            )
            return None
        
        return session
    
    async def update_session(
        self,
        session_id: str,
        state: dict | None = None,
        events: list | None = None,
    ) -> dict | None:
        """
        Update session state and/or events.
        
        Args:
            session_id: Session ID
            state: New state (merged with existing)
            events: New events to append
            
        Returns:
            Updated session or None if not found
        """
        client = await self._get_client()
        
        key = f"{self.SESSION_PREFIX}{session_id}"
        data = await client.get(key)
        
        if data is None:
            return None
        
        session = json.loads(data)
        
        if state is not None:
            session["state"] = {**session.get("state", {}), **state}
        
        if events is not None:
            session["events"] = session.get("events", []) + events
        
        session["updated_at"] = datetime.utcnow().isoformat()
        
        await client.set(key, json.dumps(session), ex=self.SESSION_TTL)
        
        logger.debug("session_updated", session_id=session_id)
        
        return session
    
    async def delete_session(self, session_id: str) -> bool:
        """
        Delete a session.
        
        Args:
            session_id: Session ID
            
        Returns:
            True if deleted, False if not found
        """
        client = await self._get_client()
        
        key = f"{self.SESSION_PREFIX}{session_id}"
        deleted = await client.delete(key)
        
        if deleted:
            logger.info("session_deleted", session_id=session_id)
        
        return deleted > 0
    
    async def list_user_sessions(
        self,
        app_name: str,
        user_id: str | None,
        limit: int = 100,
    ) -> list[dict]:
        """
        List all sessions for a user.
        
        Note: This is O(n) where n is total sessions. Use sparingly.
        """
        client = await self._get_client()
        
        sessions = []
        cursor = 0
        
        while True:
            cursor, keys = await client.scan(cursor, match=f"{self.SESSION_PREFIX}*", count=100)
            
            for key in keys:
                data = await client.get(key)
                if data:
                    session = json.loads(data)
                    matches_user = user_id is None or session.get("user_id") == user_id
                    if matches_user and session.get("app_name") == app_name:
                        sessions.append(session)
                        if len(sessions) >= limit:
                            return sessions
            
            if cursor == 0:
                break
        
        return sessions
    
    async def close(self):
        """No-op. Pool cleanup is centralised in redis_pool."""
        pass


# ADK-compatible wrapper
class RedisSessionService(BaseSessionService):
    """
    ADK-compatible session service backed by Redis.
    
    Drop-in replacement for InMemorySessionService.
    """
    
    def __init__(self):
        self._store = RedisSessionStore()
    
    def _to_adk_session(self, session: dict) -> Session:
        events = [
            Event.model_validate(event) if not isinstance(event, Event) else event
            for event in session.get("events", [])
        ]
        return Session(
            id=session["id"],
            appName=session["app_name"],
            userId=session["user_id"],
            state=session.get("state", {}),
            events=events,
            lastUpdateTime=session.get("last_update_time", 0.0),
        )

    async def create_session(
        self,
        *,
        app_name: str,
        user_id: str,
        session_id: str | None = None,
        state: dict | None = None,
    ) -> Session:
        """Create a new session (ADK interface)."""
        session = await self._store.create_session(
            app_name=app_name,
            user_id=user_id,
            session_id=session_id,
            initial_state=state,
        )
        session["last_update_time"] = datetime.utcnow().timestamp()
        return self._to_adk_session(session)
    
    async def get_session(
        self,
        *,
        app_name: str,
        user_id: str,
        session_id: str,
        config: Any | None = None,
    ) -> Session | None:
        """Get a session (ADK interface)."""
        session = await self._store.get_session(
            app_name=app_name,
            user_id=user_id,
            session_id=session_id,
        )

        if session is None:
            return None

        session.setdefault("last_update_time", datetime.utcnow().timestamp())
        return self._to_adk_session(session)

    async def list_sessions(
        self,
        *,
        app_name: str,
        user_id: str | None = None,
    ) -> ListSessionsResponse:
        sessions = await self._store.list_user_sessions(
            app_name=app_name,
            user_id=user_id,
            limit=100,
        )
        return ListSessionsResponse(
            sessions=[self._to_adk_session(session) for session in sessions]
        )

    async def delete_session(
        self,
        *,
        app_name: str,
        user_id: str,
        session_id: str,
    ) -> None:
        await self._store.delete_session(session_id=session_id)

    async def update_session_state(
        self,
        *,
        app_name: str,
        user_id: str,
        session_id: str,
        state: dict[str, Any],
    ) -> Session | None:
        existing = await self._store.get_session(
            app_name=app_name,
            user_id=user_id,
            session_id=session_id,
        )
        if existing is None:
            return None

        updated = await self._store.update_session(
            session_id=session_id,
            state=state,
        )
        if updated is None:
            return None
        updated["last_update_time"] = datetime.utcnow().timestamp()
        return self._to_adk_session(updated)

    async def append_event(self, session: Session, event: Event) -> Event:
        appended_event = await super().append_event(session, event)
        await self._store.update_session(
            session_id=session.id,
            state=session.state,
            events=[appended_event.model_dump(mode="json")],
        )
        return appended_event
    
    async def close(self):
        """Close connections."""
        await self._store.close()


# Global instance
redis_session_service = RedisSessionService()
