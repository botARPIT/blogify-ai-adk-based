import React from 'react';

interface StatusBadgeProps {
  status: string;
}

const STATUS_LABELS: Record<string, string> = {
  queued: 'Queued',
  processing: 'Processing',
  awaiting_outline_review: 'Outline Review',
  awaiting_human_review: 'Final Review',
  revision_requested: 'Revision Requested',
  completed: 'Completed',
  failed: 'Failed',
  cancelled: 'Cancelled',
  budget_exhausted: 'Budget Exhausted',
};

const StatusBadge: React.FC<StatusBadgeProps> = ({ status }) => {
  const isAttention = status.includes('review') || status === 'revision_requested';
  const isFailure = status === 'failed' || status === 'budget_exhausted' || status === 'cancelled';
  const color = isFailure
    ? 'var(--error-color)'
    : isAttention
      ? 'var(--accent-color)'
      : 'var(--text-primary)';

  return (
    <span
      className="brutalist-label"
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: '0.5rem',
        color,
        margin: 0,
      }}
    >
      <span
        style={{
          width: '10px',
          height: '10px',
          background: color,
          display: 'inline-block',
        }}
      />
      {STATUS_LABELS[status] || status}
    </span>
  );
};

export default StatusBadge;
