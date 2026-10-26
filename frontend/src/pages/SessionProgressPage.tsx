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

  const currentSession = session!;
  const isFailureState = ['failed', 'rejected', 'agent_rejected', 'cancelled'].includes(currentSession.status);
  const statusMessage: Record<string, string> = {
    queued: 'The request is accepted and waiting for a worker slot.',
    processing: 'Agents are actively moving through the current drafting stage.',
    revision_requested: 'A revision loop was requested and the drafting process is resuming.',
    failed: 'This session hit an execution error and needs operator attention.',
    rejected: 'This session was explicitly rejected by the reviewer and will not resume.',
    agent_rejected: 'The automated intent gate blocked this request before outline or research began.',
    cancelled: 'This session was cancelled before completion.',
  };

  return (
    <div className="animate-in workspace-content">
      <SessionHeader
        sessionId={sessionId || String(currentSession.session_id)}
        title="Session Progress"
        subtitle={currentSession.current_stage || 'Processing'}
        status={currentSession.status}
      />

      {currentSession.status === 'failed' ? <div className="workflow-error-banner" role="alert"><span>!</span><div><strong>This run stopped before it finished.</strong><p>Review the session detail for stage logs and try a new story when you’re ready. You can refresh this page to check whether the status changed.</p></div></div> : null}
      {currentSession.status === 'rejected' ? <div className="workflow-notice"><span>↗</span><div><strong>This draft was rejected.</strong><p>The session is complete and will not resume. Its outline and review history remain available in the detail view.</p></div></div> : null}
      {currentSession.status === 'agent_rejected' ? <div className="workflow-notice"><span>!</span><div><strong>This request was blocked by the intent gate.</strong><p>No outline, research, or draft was generated. The session detail retains the intent-agent audit record.</p></div></div> : null}
      <div className="progress-page-grid">
        <StageTimeline status={currentSession.status} currentStage={currentSession.current_stage} currentAgent={currentSession.current_agent} />

        <div className="bento-card live-state-card">
          <span className="eyebrow">RIGHT NOW</span><h2 className="section-title">Session status</h2>
          <div className="live-state-list">
            <div className="live-state-row">
              <span className="brutalist-label">Status</span>
              <StatusBadge status={currentSession.status} />
            </div>
            <div className="live-state-row">
              <span className="brutalist-label">Current stage</span>
              <span className="live-value">{currentSession.current_stage?.replaceAll('_', ' ') || 'Getting started'}</span>
            </div>
            {currentSession.current_agent && (
              <div className="live-state-row">
                <span className="brutalist-label">Working on</span>
                <span className="live-value live-agent">
                  {currentSession.current_agent.replaceAll('_', ' ')}
                </span>
              </div>
            )}
            <p className="text-secondary live-state-description">
              {statusMessage[currentSession.status] || 'The session is moving through the canonical workflow.'}
            </p>
          </div>
        </div>

        <div className="bento-card progress-actions-card">
          <span className="eyebrow">PICK UP THE THREAD</span><h2 className="section-title">Your next step</h2>
          <div className="progress-actions">
            <button className="button button-quiet" onClick={() => void refresh()}>
              Refresh status <span aria-hidden="true">↻</span>
            </button>
            <Link className="button button-quiet" to={`/sessions/${sessionId}`}>
              Session details <span aria-hidden="true">↗</span>
            </Link>
            {isFailureState ? (
              <Link className="button button-primary" to="/dashboard">
                Start a new story <span aria-hidden="true">↗</span>
              </Link>
            ) : null}
          </div>
          {isFailureState ? (
            <p className="text-secondary" style={{ marginTop: 'var(--spacing-sm)' }}>
              Intent-gate and human-review rejections are final. Failed runs can be inspected from session details; create a fresh session to try again.
            </p>
          ) : null}
        </div>
      </div>
    </div>
  );
};

export default SessionProgressPage;
