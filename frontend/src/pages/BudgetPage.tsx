import React, { useEffect, useState } from 'react';
import { getBudget, type BudgetSnapshot } from '../lib/api/blogs';
import LoadingState from '../components/state/LoadingState';
import ErrorState from '../components/state/ErrorState';

const BudgetPage: React.FC = () => {
  const [budget, setBudget] = useState<BudgetSnapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    let isActive = true;
    getBudget()
      .then((data) => {
        if (!isActive) return;
        setBudget(data);
      })
      .catch((err) => {
        if (!isActive) return;
        setError(err instanceof Error ? err.message : 'Failed to fetch budget');
      })
      .finally(() => {
        if (isActive) setLoading(false);
      });

    return () => {
      isActive = false;
    };
  }, []);

  if (loading) {
    return <LoadingState title="Loading budget..." message="Fetching current tenant and end-user budget state." />;
  }

  if (error || !budget) {
    return <ErrorState title="Budget Unavailable" message={error || 'No budget snapshot found.'} />;
  }

  return (
    <div className="animate-in page-shell">
      <div className="page-header">
        <div className="page-header-copy">
          <span className="eyebrow-label">Operational Finance</span>
          <h1 className="page-title">Budget controls and current session pressure.</h1>
          <p className="page-subtitle">
            Track spend, active concurrency, and remaining revision headroom without the oversized utility-page treatment.
          </p>
        </div>
      </div>

      <div className="stat-grid">
        <div className="bento-card panel-card">
          <span className="eyebrow-label">Daily Spend</span>
          <h3 className="stat-number text-accent">${budget.daily_spent_usd.toFixed(2)}</h3>
          <p className="text-secondary">{budget.daily_spent_tokens} tokens consumed today</p>
        </div>

        <div className="bento-card panel-card">
          <span className="eyebrow-label">Daily Limit</span>
          <h3 className="stat-number">${budget.daily_limit_usd.toFixed(2)}</h3>
          <p className="text-secondary">{budget.daily_limit_tokens} token ceiling</p>
        </div>
        
        <div className="bento-card panel-card">
          <span className="eyebrow-label">Active Sessions</span>
          <h3 className="stat-number">{budget.active_sessions}</h3>
          <p className="text-secondary">Max concurrent: {budget.max_concurrent_sessions}</p>
        </div>

        <div className="bento-card panel-card">
          <span className="eyebrow-label">Remaining Revisions</span>
          <h3 className="stat-number">{budget.remaining_revision_iterations}</h3>
          <p className="text-secondary">Available revision loops for this user</p>
        </div>
      </div>

      <div className="bento-card panel-card">
          <h2 className="card-title">Budget Notes</h2>
          <ul style={{ paddingLeft: '1.25rem', display: 'grid', gap: '0.5rem' }}>
            <li>Spend is enforced before a new blog session is queued.</li>
            <li>Active sessions consume both concurrency and budget headroom.</li>
            <li>Revision allowances are tracked separately from simple session count.</li>
          </ul>
      </div>
    </div>
  );
};

export default BudgetPage;
