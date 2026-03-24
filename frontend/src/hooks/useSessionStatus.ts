import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { getSession, type SessionStatusResponse } from '../lib/api/blogs';
import { getRouteForStatus } from '../lib/session-routing';

const ACTIVE_STATUSES = new Set(['queued', 'processing', 'revision_requested']);
const PAUSED_STATUSES = new Set(['awaiting_outline_review', 'awaiting_human_review']);
const TERMINAL_STATUSES = new Set(['completed', 'failed', 'cancelled', 'budget_exhausted']);

export function useSessionStatus(sessionId: string | null | undefined, autoRedirect = false) {
  const [session, setSession] = useState<SessionStatusResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const navigate = useNavigate();
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const refresh = useCallback(async () => {
    if (!sessionId) {
      setLoading(false);
      return;
    }

    setLoading(true);
    try {
      const data = await getSession(sessionId);
      setSession(data);
      setError(null);

      if (intervalRef.current && !ACTIVE_STATUSES.has(data.status)) {
        clearInterval(intervalRef.current);
        intervalRef.current = null;
      }

      if (autoRedirect) {
        const targetRoute = getRouteForStatus(sessionId, data.status);
        if (window.location.pathname !== targetRoute) {
          navigate(targetRoute, { replace: true });
        }
      }
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to fetch session';
      setError(message);
    } finally {
      setLoading(false);
    }
  }, [autoRedirect, navigate, sessionId]);

  useEffect(() => {
    if (!sessionId) {
      setLoading(false);
      return;
    }

    refresh();

    if (!intervalRef.current) {
      intervalRef.current = setInterval(() => {
        refresh().catch(() => undefined);
      }, 3000);
    }

    return () => {
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
        intervalRef.current = null;
      }
    };
  }, [refresh, sessionId]);

  const isPaused = useMemo(
    () => Boolean(session?.status && PAUSED_STATUSES.has(session.status)),
    [session?.status],
  );
  const isTerminal = useMemo(
    () => Boolean(session?.status && TERMINAL_STATUSES.has(session.status)),
    [session?.status],
  );

  return {
    session,
    loading,
    error,
    isPaused,
    isTerminal,
    refresh,
  };
}
