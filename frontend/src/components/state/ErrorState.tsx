import React from 'react';

interface ErrorStateProps {
  title?: string;
  message: string;
  requestId?: string;
}

const ErrorState: React.FC<ErrorStateProps> = ({ title = 'Request Failed', message, requestId }) => (
  <div className="animate-in state-shell">
    <div className="state-card">
      <span className="eyebrow-label">Error</span>
      <h1 className="page-title text-error">{title}</h1>
      <p className="page-subtitle">{message}</p>
      {requestId ? <p className="text-secondary" style={{ marginTop: '0.75rem' }}>Reference: {requestId}</p> : null}
    </div>
  </div>
);

export default ErrorState;
