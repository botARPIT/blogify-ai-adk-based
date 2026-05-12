import React from 'react';
import LoadingState from '../components/state/LoadingState';
import ErrorState from '../components/state/ErrorState';
import { useBudgetPolling } from '../hooks/useBudgetPolling';

const BudgetPage: React.FC = () => {
  const { budget, loading, error } = useBudgetPolling();

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
        {error && (
          <div className="bento-card panel-card">
            <span className="eyebrow-label">Refresh Status</span>
            <p className="text-secondary">{error}</p>
          </div>
        )}

        <div className="bento-card panel-card">
          <span className="eyebrow-label">Balance</span>
          <h3 className="stat-number text-accent">${(budget.balance_usd ?? 0).toFixed(2)}</h3>
          <p className="text-secondary">{budget.balance_tokens?.toLocaleString() ?? 0} tokens available</p>
        </div>

        <div className="bento-card panel-card">
          <span className="eyebrow-label">Daily Blog Limit Left</span>
          <h3 className="stat-number">{budget.daily_blog_limit_left ?? 0}</h3>
          <p className="text-secondary">Sessions remaining today</p>
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
