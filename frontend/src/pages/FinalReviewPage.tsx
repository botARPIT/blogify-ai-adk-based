import React, { useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
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
  const [selectedAction, setSelectedAction] = useState<'revision_requested' | null>(null);

  if (loading) return <LoadingState title="Opening your draft" message="Bringing the latest version into the review room." />;
  if (error || !version) return <ErrorState title="Draft unavailable" message={error || 'No draft version was available for review.'} />;

  const handleAction = async (action: 'approved' | 'revision_requested' | 'rejected') => {
    if (!sessionId) return;
    if (action === 'revision_requested' && !feedback.trim()) { setSubmitError('Add a note about what you want changed.'); return; }
    setSubmitting(true);
    setSubmitError('');
    try {
      const result = await submitFinalReview(sessionId, { action, ...(action === 'revision_requested' ? { feedback_text: feedback.trim() } : {}) });
      toast.success(action === 'approved' ? 'Article approved' : action === 'revision_requested' ? 'Revision requested' : 'Article rejected', { description: 'Your decision has been saved.' });
      navigate(getRouteForStatus(sessionId, result.status), { replace: true });
    } catch (err) {
      const message = err instanceof Error ? err.message : 'We couldn’t save your review. Try again.';
      setSubmitError(message);
      toast.error('Review not saved', { description: message });
    } finally { setSubmitting(false); }
  };

  return <div className="animate-in workspace-content review-page">
    <SessionHeader sessionId={sessionId || String(version.session_id)} title="Final review" subtitle={version.title || session?.topic || 'Latest generated draft'} status={session?.status || 'awaiting_final_review'} />
    <div className="final-review-layout">
      <article className="bento-card final-article-card">
        <div className="article-toolbar"><div><span className="eyebrow">THE LATEST DRAFT</span><div className="article-version">Version {version.version_number} <i /> {version.word_count.toLocaleString()} words</div></div><button className="button button-quiet" type="button" onClick={() => setShowRaw((value) => !value)} aria-pressed={showRaw}>{showRaw ? 'Rendered view' : 'Raw markdown'}</button></div>
        {showRaw ? <pre className="markdown-code-block raw-article"><code>{version.content_markdown || ''}</code></pre> : <MarkdownArticle markdown={version.content_markdown || ''} />}
      </article>
      <aside className="final-review-aside">
        <section className="checkpoint-card final-checkpoint"><span className="checkpoint-icon">✓</span><span className="eyebrow">YOUR FINAL CHECKPOINT</span><h2>Is it ready to go?</h2><p>Approve the article, or tell us exactly what needs a second pass.</p>
          <MetadataPanel title="Draft details" items={[{ label: 'Version', value: version.version_number }, { label: 'Words', value: version.word_count.toLocaleString() }, { label: 'Sources', value: version.sources_count }, { label: 'Editor pass', value: version.editor_status }]} />
          <div className="bento-card decision-card"><h2 className="section-title">Your decision</h2>
            {selectedAction === 'revision_requested' && <div className="field-group"><label htmlFor="revision-feedback">What should change?</label><textarea id="revision-feedback" className="field-input guidance-input" rows={4} maxLength={3000} placeholder="Be specific: what should be added, changed, or clarified?" value={feedback} onChange={(event) => setFeedback(event.target.value)} /></div>}
            {submitError && <p className="inline-alert" role="alert">{submitError}</p>}
            <div className="decision-actions"><button className="button button-primary" type="button" onClick={() => { setSelectedAction(null); setSubmitError(''); void handleAction('approved'); }} disabled={submitting}>{submitting ? 'Saving…' : <>Approve article <span aria-hidden="true">✓</span></>}</button>
              {selectedAction === 'revision_requested' ? <><button className="button button-quiet" type="button" onClick={() => { setSelectedAction(null); setSubmitError(''); }} disabled={submitting}>Cancel revision</button><button className="button button-secondary-warm" type="button" onClick={() => void handleAction('revision_requested')} disabled={submitting}>{submitting ? 'Sending…' : 'Send revision request'}</button></> : <button className="button button-quiet" type="button" onClick={() => { setSelectedAction('revision_requested'); setSubmitError(''); }} disabled={submitting}>Request a revision</button>}
              <button className="reject-action" type="button" onClick={() => { setSelectedAction(null); setSubmitError(''); void handleAction('rejected'); }} disabled={submitting}>Reject this draft</button>
            </div>
          </div>
        </section>
      </aside>
    </div>
  </div>;
};

export default FinalReviewPage;
