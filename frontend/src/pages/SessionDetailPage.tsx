import React, { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { getSessionDetail, type SessionDetailView } from '../lib/api/blogs';
import SessionHeader from '../components/session/SessionHeader';
import LoadingState from '../components/state/LoadingState';
import ErrorState from '../components/state/ErrorState';

const SessionDetailPage: React.FC = () => {
  const { sessionId } = useParams<{ sessionId: string }>();
  const [detail, setDetail] = useState<SessionDetailView | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!sessionId) {
      setLoading(false);
      setError('Missing session id.');
      return;
    }

    let isActive = true;
    setLoading(true);
    getSessionDetail(sessionId)
      .then((data) => {
        if (!isActive) return;
        setDetail(data);
        setError('');
      })
      .catch((err) => {
        if (!isActive) return;
        setError(err instanceof Error ? err.message : 'Failed to fetch session detail');
      })
      .finally(() => {
        if (isActive) setLoading(false);
      });

    return () => {
      isActive = false;
    };
  }, [sessionId]);

  if (loading) {
    return <LoadingState title="Loading detail..." message="Collecting review events and agent run metadata." />;
  }

  if (error || !detail) {
    return <ErrorState title="Detail Unavailable" message={error || 'No session detail found.'} />;
  }

  return (
    <div className="animate-in page-shell">
      <SessionHeader
        sessionId={sessionId || String(detail.session.session_id)}
        title="Session Detail"
        subtitle={detail.session.topic}
        status={detail.session.status}
      />

      <div className="stat-grid">
        <div className="bento-card panel-card">
          <span className="eyebrow-label">Audience</span>
          <div className="stat-number">{detail.session.audience || 'General'}</div>
        </div>
        <div className="bento-card panel-card">
          <span className="eyebrow-label">Current Stage</span>
          <div className="stat-number stat-number-small">{detail.session.current_stage || 'queued'}</div>
        </div>
        <div className="bento-card panel-card">
          <span className="eyebrow-label">Iterations</span>
          <div className="stat-number">{detail.session.iteration_count}</div>
        </div>
        <div className="bento-card panel-card">
          <span className="eyebrow-label">Spent Tokens</span>
          <div className="stat-number stat-number-small">{detail.session.budget_spent_tokens}</div>
        </div>
      </div>

      <div className="detail-grid">
        <div className="bento-card panel-card">
          <h2 className="card-title">Outline Snapshot</h2>
          {detail.outline ? (
            <div className="outline-snapshot">
              <div className="outline-title">
                {detail.outline.outline.title}
              </div>
              {detail.outline.outline.sections.map((section) => (
                <div key={section.id} className="outline-section">
                  <div className="eyebrow-label">{section.heading}</div>
                  <p className="text-secondary">{section.goal}</p>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-secondary">No outline has been materialized for this session.</p>
          )}
        </div>

        <div className="bento-card panel-card">
          <h2 className="card-title">Latest Version</h2>
          {detail.latest_version ? (
            <div className="outline-snapshot">
              <div className="outline-title">
                {detail.latest_version.title || 'Untitled version'}
              </div>
              <div className="text-secondary detail-copy">
                Version {detail.latest_version.version_number} | {detail.latest_version.word_count} words | {detail.latest_version.sources_count} sources
              </div>
              <div className="text-secondary detail-copy">
                Editor status: {detail.latest_version.editor_status}
              </div>
              <Link className="brutalist-button secondary" to={`/sessions/${sessionId}/output`}>
                Open Output
              </Link>
            </div>
          ) : (
            <p className="text-secondary">No version has been materialized yet.</p>
          )}
        </div>

        <div className="bento-card panel-card" style={{ gridColumn: '1 / -1' }}>
          <h2 className="card-title">Human Review Events</h2>
          {detail.review_events.length === 0 ? (
            <p className="text-secondary">No human review events recorded yet.</p>
          ) : (
            <div className="event-stack">
              {detail.review_events.map((event) => (
                <div key={event.event_id} className="event-card">
                  <div className="event-header">
                    <span className="eyebrow-label" style={{ margin: 0 }}>{event.action}</span>
                    <span className="text-secondary">{new Date(event.created_at).toLocaleString()}</span>
                  </div>
                  <p style={{ marginTop: '0.75rem' }}>{event.feedback_text || 'No feedback captured.'}</p>
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="bento-card panel-card" style={{ gridColumn: '1 / -1' }}>
          <h2 className="card-title">Agent Runs</h2>
          {detail.agent_runs.length === 0 ? (
            <p className="text-secondary">No agent run records were found.</p>
          ) : (
            <div className="event-stack">
              {detail.agent_runs.map((run) => (
                <div key={run.run_id} className="event-card">
                  <div className="event-header">
                    <strong>{run.stage_name}</strong>
                    <span className="text-secondary">{run.agent_name}</span>
                  </div>
                  <div className="text-secondary detail-copy" style={{ marginTop: '0.5rem' }}>
                    Status: {run.status} | Prompt: {run.prompt_tokens} | Completion: {run.completion_tokens} | Cost: ${run.cost_usd.toFixed(4)}
                  </div>
                  {run.error_message ? <p style={{ color: 'var(--error-color)', marginTop: '0.5rem' }}>{run.error_message}</p> : null}
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default SessionDetailPage;
