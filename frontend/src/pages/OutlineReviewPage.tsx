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
        toast.success('Outline approved', { description: decision.message || 'Research and writing are moving ahead.' });
        navigate(`/sessions/${sessionId}/progress`, { replace: true });
        return;
      }
      toast.success('Outline saved', { description: decision.message || 'Your changes are saved. Approve when you’re ready to continue.' });
      setLocalOutline(decision.outline || localOutline);
    } catch (err) {
      console.error('Failed to submit outline review: ', err);
      const message = err instanceof Error ? err.message : 'Failed to submit outline review';
      setValidationError(message);
      toast.error('Outline review failed', { description: message });
    }
  };

  return (
    <div className="animate-in workspace-content review-page">
      <SessionHeader
        sessionId={sessionId || String(outlineView.session_id)}
        title="Outline Review"
        subtitle={outlineView.topic}
        status={session?.status || outlineView.status}
      />

      <div className="review-layout">
        <div className="review-main"><OutlineEditor value={localOutline} onChange={setLocalOutline} />
        <section className="bento-card guidance-card">
          <span className="eyebrow">A NOTE FOR THE WRITING STAGE</span><h2 className="section-title">What should we keep in mind?</h2>
          <p className="text-secondary mb-md">Call out examples, details, or angles you want the final article to include.</p>
          <label className="sr-only" htmlFor="outline-feedback">Guidance for writing</label>
          <textarea id="outline-feedback" className="field-input guidance-input" rows={4} maxLength={3000} placeholder="A source to include, an example to use, or a point to handle carefully…" value={feedback} onChange={(e) => setFeedback(e.target.value)} />
          {validationError ? (
            <p className="inline-alert" role="alert">{validationError}</p>
          ) : null}
          <div className="review-actions"><button className="button button-quiet" onClick={() => void handleAction('revise')} disabled={submitting}>{submitting ? 'Saving…' : 'Save changes'}</button><button className="button button-primary" onClick={() => void handleAction('approve')} disabled={submitting}>{submitting ? 'Working…' : <>Approve outline <span aria-hidden="true">↗</span></>}</button></div>
        </section></div>
        <aside className="review-aside"><section className="checkpoint-card"><span className="checkpoint-icon">✳</span><span className="eyebrow">YOUR FIRST CHECKPOINT</span><h2>Make the shape feel right.</h2><p>We’ll wait here until you approve. Your outline and guidance travel with the article.</p><div className="checkpoint-rule"><span>03–07</span><small>sections</small><i /><span>80–300</span><small>words each</small></div></section></aside>
      </div>
    </div>
  );
};

export default OutlineReviewPage;
