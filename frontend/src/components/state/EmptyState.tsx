import React from 'react';

interface EmptyStateProps {
  title: string;
  message: string;
}

const EmptyState: React.FC<EmptyStateProps> = ({ title, message }) => (
  <div className="bento-card">
    <h2 className="section-title">{title}</h2>
    <p className="text-secondary">{message}</p>
  </div>
);

export default EmptyState;
