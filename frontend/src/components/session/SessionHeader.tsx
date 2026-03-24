import React from 'react';
import { Link } from 'react-router-dom';
import StatusBadge from './StatusBadge';

interface SessionHeaderProps {
  sessionId: string;
  title: string;
  subtitle?: string | null;
  status: string;
}

const SessionHeader: React.FC<SessionHeaderProps> = ({ sessionId, title, subtitle, status }) => (
  <div className="page-header">
    <div className="page-header-copy">
      <Link to="/" className="brutalist-button secondary" style={{ fontSize: '0.875rem', padding: '0.5rem 1rem', marginBottom: 'var(--spacing-sm)', textDecoration: 'none' }}>
        &larr; Dashboard
      </Link>
      <h1 className="page-title">{title}</h1>
      {subtitle ? <p className="page-subtitle">{subtitle}</p> : null}
    </div>
    <div className="page-header-meta">
      <span className="eyebrow-label">Session</span>
      <div className="session-code">{sessionId}</div>
      <StatusBadge status={status} />
    </div>
  </div>
);

export default SessionHeader;
