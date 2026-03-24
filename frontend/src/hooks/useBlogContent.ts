import { useEffect, useState } from 'react';
import { getContent, type BlogContentView } from '../lib/api/blogs';

export function useBlogContent(sessionId: string | undefined) {
  const [content, setContent] = useState<BlogContentView | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!sessionId) {
      setLoading(false);
      return;
    }

    let isActive = true;
    setLoading(true);
    getContent(sessionId)
      .then((data) => {
        if (!isActive) return;
        setContent(data);
        setError(null);
      })
      .catch((err) => {
        if (!isActive) return;
        setError(err instanceof Error ? err.message : 'Failed to fetch blog content');
      })
      .finally(() => {
        if (isActive) setLoading(false);
      });

    return () => {
      isActive = false;
    };
  }, [sessionId]);

  return { content, loading, error };
}
