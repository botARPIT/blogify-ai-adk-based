import React from 'react';

interface StatusBadgeProps {
  status: string;
}

const STATUS_LABELS: Record<string, string> = {
  queued: 'Queued',
  processing: 'Processing',
  awaiting_outline_review: 'Outline Review',
  awaiting_final_review: 'Final Review',
  revision_requested: 'Revision Requested',
  completed: 'Completed',
  failed: 'Failed',
  cancelled: 'Cancelled',
};

const StatusBadge: React.FC<StatusBadgeProps> = ({ status }) => {
  const normalizedStatus = status?.toLowerCase() || '';
  const isAttention = normalizedStatus.includes('review') || normalizedStatus === 'revision_requested';
  const isFailure = normalizedStatus === 'failed' || normalizedStatus === 'cancelled';
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
      {STATUS_LABELS[normalizedStatus] || status}
    </span>
  );
};

export default StatusBadge;