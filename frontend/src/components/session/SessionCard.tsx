import React from 'react';
import { Link } from 'react-router-dom';
import type { BlogSessionItem } from '../../lib/api/blogs';
import { getRouteForStatus } from '../../lib/session-routing';

const prettyDate = (value: string) => new Intl.DateTimeFormat(undefined, {
  month: 'short', day: 'numeric', year: 'numeric',
}).format(new Date(value));

const actionFor = (status: string) => {
  switch (status.toLowerCase()) {
    case 'awaiting_outline_review': return 'Review outline';
    case 'awaiting_final_review': return 'Review draft';
    case 'completed': return 'Read article';
    default: return 'View progress';
  }
};

const stageFor = (stage: string | null) => {
  if (!stage) return 'Getting started';
  return stage.replaceAll('_', ' ');
};

interface SessionCardProps {
  session: BlogSessionItem;
}

const SessionCard: React.FC<SessionCardProps> = ({ session }) => {
  const status = session.status.toLowerCase();
  const href = getRouteForStatus(String(session.session_id), status);
  const isDone = status === 'completed';
  const isFailed = ['failed', 'rejected', 'cancelled'].includes(status);
  const marker = isDone ? '✓' : isFailed ? '!' : '✳';

  return (
    <article className={`story-card ${isFailed ? 'story-card-failed' : ''} ${isDone ? 'story-card-complete' : ''}`} role="listitem">
      <div className="story-card-topline">
        <span className={`story-card-mark ${isFailed ? 'is-failed' : ''} ${isDone ? 'is-done' : ''}`} aria-hidden="true">{marker}</span>
        <span className="story-date">{prettyDate(session.created_at)}</span>
      </div>
      <div className="story-card-copy">
        <Link to={`/sessions/${session.session_id}`} className="story-card-title">{session.topic}</Link>
        <p>{session.audience || 'General readers'} <span aria-hidden="true">·</span> {stageFor(session.current_stage)}</p>
      </div>
      <div className="story-card-footer">
        <span className="story-card-session">STORY <span>#{session.session_id}</span></span>
        <span className="story-card-cost">${session.cost_usd.toFixed(4)}</span>
        <Link className="story-card-action" to={href}>{actionFor(session.status)} <span aria-hidden="true">↗</span></Link>
      </div>
    </article>
  );
};

export default SessionCard;
