import { useEffect, useState } from 'react';
import { getBudget, type BudgetSnapshot } from '../lib/api/blogs';

export function useBudgetPolling(intervalMs = 10_000) {
  const [budget, setBudget] = useState<BudgetSnapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    let isActive = true;

    const refreshBudget = async () => {
      try {
        const snapshot = await getBudget();
        if (!isActive) return;
        setBudget(snapshot);
        setError('');
      } catch (err) {
        if (!isActive) return;
        setError(err instanceof Error ? err.message : 'Failed to fetch budget');
      } finally {
        if (isActive) setLoading(false);
      }
    };

    refreshBudget();
    const interval = setInterval(refreshBudget, intervalMs);

    return () => {
      isActive = false;
      clearInterval(interval);
    };
  }, [intervalMs]);

  return { budget, loading, error };
}
