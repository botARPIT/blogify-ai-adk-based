import React from 'react';

interface LoadingStateProps {
  title?: string;
  message?: string;
}

const LoadingState: React.FC<LoadingStateProps> = ({
  title = 'Loading...',
  message = 'Please wait while we fetch the latest session state.',
}) => (
  <div className="animate-in state-shell">
    <div className="state-card">
      <span className="eyebrow-label">System State</span>
      <h1 className="page-title">{title}</h1>
      <p className="page-subtitle">{message}</p>
    </div>
  </div>
);

export default LoadingState;
