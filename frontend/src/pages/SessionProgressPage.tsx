import React from 'react';
import { Link, useParams } from 'react-router-dom';
import { useSessionStatus } from '../hooks/useSessionStatus';
import SessionHeader from '../components/session/SessionHeader';
import StageTimeline from '../components/session/StageTimeline';
import LoadingState from '../components/state/LoadingState';
import ErrorState from '../components/state/ErrorState';
import StatusBadge from '../components/session/StatusBadge';

const SessionProgressPage = () => {
  const { sessionId } = useParams<{ sessionId: string }>();
  const { session, loading, error, refresh } = useSessionStatus(sessionId, true);

  if (loading && !session) {
    return <LoadingState title="Connecting..." message="Syncing the canonical session with the worker pipeline." />;
  }

  if (error || (!loading && !session)) {
    return <ErrorState title="Session Unavailable" message={error || 'No canonical session was found.'} />;
  }

  const isFailureState = ['failed', 'cancelled', 'budget_exhausted'].includes(session.status);
  const statusMessage: Record<string, string> = {
    queued: 'The request is accepted and waiting for a worker slot.',
    processing: 'Agents are actively moving through the current drafting stage.',
    revision_requested: 'A revision loop was requested and the drafting process is resuming.',
    failed: 'This session hit an execution error and needs operator attention.',
    cancelled: 'This session was cancelled before completion.',
    budget_exhausted: 'Budget guardrails paused the run before it could continue.',
  };

  return (
    <div className="animate-in">
      <SessionHeader
        sessionId={sessionId || session.session_id}
        title="Session Progress"
        subtitle={session.topic}
        status={session.status}
      />

      <div className="bento-grid">
        <StageTimeline status={session.status} currentStage={session.current_stage} />

        <div className="bento-card">
          <h2 className="section-title">Live Session State</h2>
          <div style={{ display: 'grid', gap: 'var(--spacing-sm)' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <span className="brutalist-label" style={{ margin: 0 }}>Status</span>
              <StatusBadge status={session.status} />
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between' }}>
              <span className="brutalist-label" style={{ margin: 0 }}>Current Stage</span>
              <span>{session.current_stage || 'queued'}</span>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between' }}>
              <span className="brutalist-label" style={{ margin: 0 }}>Iteration</span>
              <span>{session.iteration_count}</span>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between' }}>
              <span className="brutalist-label" style={{ margin: 0 }}>Tokens</span>
              <span>{session.budget_spent_tokens}</span>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between' }}>
              <span className="brutalist-label" style={{ margin: 0 }}>Budget Used</span>
              <span>${session.budget_spent_usd.toFixed(2)}</span>
            </div>
            <p className="text-secondary" style={{ marginTop: 'var(--spacing-sm)' }}>
              {statusMessage[session.status] || 'The session is moving through the canonical workflow.'}
            </p>
          </div>
        </div>

        <div className="bento-card" style={{ gridColumn: '1 / -1' }}>
          <h2 className="section-title">Operator Actions</h2>
          <div style={{ display: 'flex', gap: 'var(--spacing-sm)', flexWrap: 'wrap' }}>
            <button className="brutalist-button secondary" onClick={() => refresh()}>
              Refresh Session
            </button>
            <Link className="brutalist-button secondary" to={`/sessions/${sessionId}`}>
              Open Detail View
            </Link>
            {isFailureState ? (
              <Link className="brutalist-button secondary" to="/">
                Start Fresh Session
              </Link>
            ) : null}
          </div>
          {isFailureState ? (
            <p className="text-secondary" style={{ marginTop: 'var(--spacing-sm)' }}>
              This session is no longer active. Use the detail page to inspect review events and agent runs.
            </p>
          ) : null}
        </div>
      </div>
    </div>
  );
};

export default SessionProgressPage;
