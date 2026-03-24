import React, { useEffect, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { toast } from 'sonner';
import { useSessionStatus } from '../hooks/useSessionStatus';
import { type OutlineSchema } from '../lib/api/blogs';
import { useOutlineReview } from '../hooks/useOutlineReview';
import SessionHeader from '../components/session/SessionHeader';
import OutlineEditor from '../components/outline/OutlineEditor';
import LoadingState from '../components/state/LoadingState';
import ErrorState from '../components/state/ErrorState';

const OutlineReviewPage = () => {
  const { sessionId } = useParams<{ sessionId: string }>();
  const { session } = useSessionStatus(sessionId, true);
  const { outlineView, loading, error, submitting, submit } = useOutlineReview(sessionId);
  const navigate = useNavigate();

  const [feedback, setFeedback] = useState('');
  const [localOutline, setLocalOutline] = useState<OutlineSchema | null>(null);
  const [validationError, setValidationError] = useState('');

  useEffect(() => {
    if (!outlineView) return;
    setLocalOutline(outlineView.outline);
    setFeedback(outlineView.feedback_text || '');
  }, [outlineView]);

  if (loading) {
    return <LoadingState title="Loading outline..." message="Recovering the paused outline review checkpoint." />;
  }
  if (error || !outlineView || !localOutline) {
    return <ErrorState title="Outline Unavailable" message={error || 'No outline review payload was found.'} />;
  }

  const validateOutline = (outline: OutlineSchema) => {
    if (!outline.title.trim()) return 'Outline title is required.';
    if (outline.sections.length < 3 || outline.sections.length > 7) {
      return 'Outline must contain between 3 and 7 sections.';
    }
    for (const section of outline.sections) {
      if (!section.id.trim() || !section.heading.trim() || !section.goal.trim()) {
        return 'Each section must include an id, heading, and goal.';
      }
      if (section.target_words < 80 || section.target_words > 300) {
        return 'Each section target must be between 80 and 300 words.';
      }
    }
    const calculatedWords = outline.sections.reduce((sum, section) => sum + Number(section.target_words || 0), 0);
    if (calculatedWords !== outline.estimated_total_words) {
      return 'Estimated total words must equal the sum of section targets.';
    }
    return '';
  };

  const handleAction = async (action: 'approve' | 'revise') => {
    if (!sessionId || !localOutline) return;
    const issue = validateOutline(localOutline);
    if (issue) {
      setValidationError(issue);
      return;
    }
    setValidationError('');
    try {
      const decision = await submit(action, {
        edited_outline: localOutline,
        feedback_text: feedback,
      });
      if (action === 'approve') {
        toast.success('Outline approved', { description: decision.message });
        navigate(`/sessions/${sessionId}/progress`, { replace: true });
        return;
      }
      toast.success('Outline updated', { description: decision.message });
      setLocalOutline(decision.outline);
    } catch (err) {
      console.error('Failed to submit outline review: ', err);
      const message = err instanceof Error ? err.message : 'Failed to submit outline review';
      setValidationError(message);
      toast.error('Outline review failed', { description: message });
    }
  };

  return (
    <div className="animate-in">
      <SessionHeader
        sessionId={sessionId || String(outlineView.session_id)}
        title="Outline Review"
        subtitle={outlineView.topic}
        status={session?.status || outlineView.status}
      />

      <div className="bento-grid">
        <div style={{ gridColumn: '1 / -1' }}>
          <OutlineEditor value={localOutline} onChange={setLocalOutline} />
        </div>

        <div className="bento-card">
          <h2 className="section-title">Guidance For Final Generation</h2>
          <p className="text-secondary mb-md">
            Use this space to specify what data, examples, metrics, or angles the final draft must include.
          </p>
          <textarea
            className="brutalist-input"
            rows={6}
            placeholder="Include exact details, data requests, examples, or exclusions for the final article."
            value={feedback}
            onChange={(e) => setFeedback(e.target.value)}
            style={{ width: '100%', fontSize: '1rem' }}
          />
          {validationError ? (
            <p style={{ color: 'var(--error-color)', marginBottom: 'var(--spacing-sm)' }}>{validationError}</p>
          ) : null}
          <div style={{ display: 'flex', gap: 'var(--spacing-sm)', flexWrap: 'wrap' }}>
            <button
              className="brutalist-button secondary"
              onClick={() => handleAction('revise')}
              disabled={submitting}
            >
              Save Changes
            </button>
            <button
              className="brutalist-button"
              onClick={() => handleAction('approve')}
              disabled={submitting}
            >
              Approve & Continue
            </button>
          </div>
        </div>

        <div className="bento-card">
          <h2 className="section-title">Checkpoint Rules</h2>
          <ul style={{ paddingLeft: '1.25rem', display: 'grid', gap: '0.5rem' }}>
            <li>Keep the outline between 3 and 7 sections.</li>
            <li>Each section must carry a clear goal and word target.</li>
            <li>The writing pipeline resumes only after approval.</li>
            <li>Saved revisions keep the session in the outline review state.</li>
          </ul>
        </div>
      </div>
    </div>
  );
};

export default OutlineReviewPage;
