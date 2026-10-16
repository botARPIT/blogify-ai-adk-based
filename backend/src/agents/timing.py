"""Wall-clock timing callbacks for ADK workflow agents."""

from __future__ import annotations

import inspect
import json
from datetime import datetime, timezone
from time import perf_counter_ns
from typing import Any

from src.core import redis_pool

AGENT_TIMINGS_STATE_KEY = "_blogify_agent_durations_ms"


def agent_timing_callbacks(stage: str) -> tuple[Any, Any]:
    """Return callbacks that accumulate an agent's wall time in workflow state.

    The interval covers the whole agent execution, including model calls and
    tools invoked by that agent. Repeated runs of a stage are accumulated.
    """
    started_key = f"_blogify_agent_started_ns_{stage}"

    async def before_agent(context) -> None:
        try:
            context.state[started_key] = perf_counter_ns()
        except Exception:
            # Timing state is best-effort and must not block the agent.
            pass
        session_id = getattr(getattr(context, "session", None), "id", None)
        if session_id:
            try:
                redis = redis_pool.get_redis_client()
                if inspect.isawaitable(redis):
                    redis = await redis
                await redis.set(
                    active_agent_key(str(session_id)),
                    json.dumps({
                        "stage": stage,
                        "started_at": datetime.now(timezone.utc).isoformat(),
                    }),
                    ex=3600,
                )
            except Exception:
                # Diagnostics must never make a generation fail.
                pass

    async def after_agent(context) -> None:
        try:
            started_at = context.state.get(started_key)
            if started_at is not None:
                # ADK State supports indexed writes but intentionally does not
                # expose dict.pop()/del; clearing with None keeps the key out
                # of the persisted timing values on the next invocation.
                context.state[started_key] = None
                durations = dict(context.state.get(AGENT_TIMINGS_STATE_KEY, {}))
                duration_ms = max(0, round((perf_counter_ns() - started_at) / 1_000_000))
                durations[stage] = int(durations.get(stage, 0)) + duration_ms
                context.state[AGENT_TIMINGS_STATE_KEY] = durations
        except Exception:
            # Diagnostic timing must never fail an otherwise successful run.
            pass

        session_id = getattr(getattr(context, "session", None), "id", None)
        if session_id:
            try:
                redis = redis_pool.get_redis_client()
                if inspect.isawaitable(redis):
                    redis = await redis
                await redis.delete(active_agent_key(str(session_id)))
            except Exception:
                pass
        return None

    return before_agent, after_agent


def active_agent_key(adk_session_id: str) -> str:
    return f"blogify:workflow:session:{adk_session_id}:active_agent"
