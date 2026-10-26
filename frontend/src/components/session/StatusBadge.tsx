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
  rejected: 'Rejected by you',
  agent_rejected: 'Blocked by safety check',
  cancelled: 'Cancelled',
};

const StatusBadge: React.FC<StatusBadgeProps> = ({ status }) => {
  const normalizedStatus = status?.toLowerCase() || '';
  const isAttention = normalizedStatus.includes('review') || normalizedStatus === 'revision_requested';
  const isFailure =
    normalizedStatus === 'failed' ||
    normalizedStatus === 'cancelled' ||
    normalizedStatus === 'rejected' ||
    normalizedStatus === 'agent_rejected';
  const badgeClass = isFailure ? 'status-failure' : isAttention ? 'status-attention' : normalizedStatus === 'completed' ? 'status-done' : '';

  return (
    <span
      className={`status-badge ${badgeClass}`}
      aria-label={`Status: ${STATUS_LABELS[normalizedStatus] || status}`}
    >
      {STATUS_LABELS[normalizedStatus] || status}
    </span>
  );
};

export default StatusBadge;
