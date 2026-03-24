import React, { useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { toast } from 'sonner';
import { useSessionStatus } from '../hooks/useSessionStatus';
import { submitFinalReview } from '../lib/api/blogs';
import { useLatestVersion } from '../hooks/useLatestVersion';
import { getRouteForStatus } from '../lib/session-routing';
import SessionHeader from '../components/session/SessionHeader';
import LoadingState from '../components/state/LoadingState';
import ErrorState from '../components/state/ErrorState';
import MarkdownArticle from '../components/content/MarkdownArticle';
import MetadataPanel from '../components/content/MetadataPanel';

const FinalReviewPage = () => {
  const { sessionId } = useParams<{ sessionId: string }>();
  const { session } = useSessionStatus(sessionId, true);
  const { version, loading, error } = useLatestVersion(sessionId);
  const navigate = useNavigate();

  const [feedback, setFeedback] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [showRaw, setShowRaw] = useState(false);
  const [submitError, setSubmitError] = useState('');

  if (loading) {
    return <LoadingState title="Loading final draft..." message="Fetching the latest canonical version for human review." />;
  }
  if (error || !version) {
    return <ErrorState title="Draft Unavailable" message={error || 'No draft version was available for review.'} />;
  }

  const handleAction = async (action: 'approve' | 'request_revision' | 'reject') => {
    if (!sessionId) return;
    if (action === 'request_revision' && !feedback.trim()) {
      setSubmitError('Feedback is required when requesting a revision.');
      return;
    }
    setSubmitting(true);
    setSubmitError('');
    try {
      const decision = await submitFinalReview(sessionId, version.version_id, {
        action,
        feedback_text: feedback,
      });
      toast.success('Review submitted', { description: decision.message });
      navigate(getRouteForStatus(sessionId, decision.new_status), { replace: true });
    } catch (err) {
      console.error('Failed to submit final review: ', err);
      const message = err instanceof Error ? err.message : 'Failed to submit final review';
      setSubmitError(message);
      toast.error('Review failed', { description: message });
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="animate-in">
      <SessionHeader
        sessionId={sessionId || String(version.session_id)}
        title="Final Review"
        subtitle={version.title || session?.topic || 'Latest generated draft'}
        status={session?.status || 'awaiting_human_review'}
      />

      <div className="bento-grid" style={{ alignItems: 'start' }}>
        <article className="bento-card" style={{ gridColumn: '1 / span 2' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 'var(--spacing-md)' }}>
            <span className="brutalist-label" style={{ margin: 0 }}>Latest Version</span>
            <button className="brutalist-button secondary" onClick={() => setShowRaw((value) => !value)}>
              {showRaw ? 'Rendered View' : 'Raw Markdown'}
            </button>
          </div>
          <h2 style={{ marginBottom: 'var(--spacing-md)' }}>{version.title || 'Untitled draft'}</h2>
          {showRaw ? (
            <pre className="markdown-code-block" style={{ whiteSpace: 'pre-wrap' }}>
              <code>{version.content_markdown || ''}</code>
            </pre>
          ) : (
            <MarkdownArticle markdown={version.content_markdown || ''} />
          )}
        </article>

        <MetadataPanel
          title="Version Metrics"
          items={[
            { label: 'Version', value: version.version_number },
            { label: 'Words', value: version.word_count },
            { label: 'Sources', value: version.sources_count },
            { label: 'Editor Status', value: version.editor_status },
            { label: 'Created By', value: version.created_by },
          ]}
        />

        <div className="bento-card">
          <h2 className="section-title">Review Decision</h2>
          <textarea
            className="brutalist-input"
            rows={5}
            placeholder="Add feedback if you want a revision loop or want to leave final reviewer notes."
            value={feedback}
            onChange={(e) => setFeedback(e.target.value)}
            style={{ width: '100%', fontSize: '1rem' }}
          />
          {submitError ? (
            <p style={{ color: 'var(--error-color)', marginBottom: 'var(--spacing-sm)' }}>{submitError}</p>
          ) : null}
          <div style={{ display: 'flex', gap: 'var(--spacing-sm)', flexWrap: 'wrap' }}>
            <button
              className="brutalist-button"
              onClick={() => handleAction('approve')}
              disabled={submitting}
            >
              Approve Release
            </button>
            <button
              className="brutalist-button secondary"
              onClick={() => handleAction('request_revision')}
              disabled={submitting}
            >
              Request Revision
            </button>
            <button
              className="brutalist-button secondary"
              onClick={() => handleAction('reject')}
              disabled={submitting}
            >
              Reject
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};

export default FinalReviewPage;
