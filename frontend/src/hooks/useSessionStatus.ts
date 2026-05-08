import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { getSessionStatus, type SessionStatusPollingResponse } from '../lib/api/blogs';
import { getRouteForStatus } from '../lib/session-routing';

const ACTIVE_STATUSES = new Set(['queued', 'processing', 'revision_requested', 'queued', 'processing']);
const PAUSED_STATUSES = new Set(['awaiting_outline_review', 'awaiting_final_review']);
const TERMINAL_STATUSES = new Set(['completed', 'failed', 'cancelled']);

function normalizeStatus(status: string): string {
  const upper = status?.toUpperCase();
  const statusMap: Record<string, string> = {
    'QUEUED': 'queued',
    'PROCESSING': 'processing',
    'AWAITING_OUTLINE_REVIEW': 'awaiting_outline_review',
    'AWAITING_FINAL_REVIEW': 'awaiting_final_review',
    'REVISION_REQUESTED': 'revision_requested',
    'COMPLETED': 'completed',
    'FAILED': 'failed',
    'CANCELLED': 'cancelled',
  };
  return statusMap[upper] || status.toLowerCase();
}

export function useSessionStatus(sessionId: string | null | undefined, autoRedirect = false) {
  const [session, setSession] = useState<SessionStatusPollingResponse | null>(null);
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
      const data = await getSessionStatus(Number(sessionId));
      const normalizedStatus = normalizeStatus(data.status);
      const normalizedData = { ...data, status: normalizedStatus };
      setSession(normalizedData);
      setError(null);

      if (intervalRef.current && !ACTIVE_STATUSES.has(normalizedStatus)) {
        clearInterval(intervalRef.current);
        intervalRef.current = null;
      }

      if (autoRedirect) {
        const targetRoute = getRouteForStatus(sessionId, normalizedStatus);
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
