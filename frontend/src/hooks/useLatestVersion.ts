import { useEffect, useState } from 'react';
import { getLatestVersion, type BlogVersionView } from '../lib/api/blogs';

export function useLatestVersion(sessionId: string | undefined) {
  const [version, setVersion] = useState<BlogVersionView | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!sessionId) {
      setLoading(false);
      return;
    }

    let isActive = true;
    setLoading(true);
    getLatestVersion(sessionId)
      .then((data) => {
        if (!isActive) return;
        setVersion(data);
        setError(null);
      })
      .catch((err) => {
        if (!isActive) return;
        setError(err instanceof Error ? err.message : 'Failed to fetch version');
      })
      .finally(() => {
        if (isActive) setLoading(false);
      });

    return () => {
      isActive = false;
    };
  }, [sessionId]);

  return { version, loading, error };
}
