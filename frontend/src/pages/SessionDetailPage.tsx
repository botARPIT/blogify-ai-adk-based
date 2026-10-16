import React, { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { getSessionDetail, type SessionDetailView } from '../lib/api/blogs';
import SessionHeader from '../components/session/SessionHeader';
import LoadingState from '../components/state/LoadingState';
import ErrorState from '../components/state/ErrorState';
import MarkdownArticle from '../components/content/MarkdownArticle';

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
    <div className="animate-in workspace-content session-detail-page">
      <SessionHeader
        sessionId={sessionId || String(detail.session.session_id)}
        title={detail.latest_version?.title || detail.session.topic}
        subtitle={detail.session.topic}
        status={detail.session.status}
      />

      <section className="detail-overview-grid" aria-label="Story performance">
        <article className="detail-overview-card detail-cost-card"><span className="eyebrow-label">TOTAL GENERATION COST</span><strong>${detail.total_cost_usd.toFixed(4)}</strong><small>Recorded across {detail.agent_runs.length} agent runs</small></article>
        <article className="detail-overview-card"><span className="eyebrow-label">WORDS</span><strong>{detail.total_words.toLocaleString()}</strong><small>In the latest version</small></article>
        <article className="detail-overview-card"><span className="eyebrow-label">TOKENS USED</span><strong>{detail.total_tokens.toLocaleString()}</strong><small>Across all workflow stages</small></article>
        <article className="detail-overview-card"><span className="eyebrow-label">CURRENT STAGE</span><strong className="detail-stage-value">{detail.session.current_stage?.replaceAll('_', ' ') || 'Getting started'}</strong><small>{detail.session.iteration_count} {detail.session.iteration_count === 1 ? 'draft' : 'drafts'} created</small></article>
      </section>

      <div className="detail-grid session-detail-grid">
        <section className="bento-card panel-card detail-outline-card">
          <div className="detail-section-heading"><div><span className="eyebrow">THE STORY SHAPE</span><h2 className="card-title">Outline</h2></div><span className="detail-count">{detail.outline?.sections.length || 0} sections</span></div>
          {detail.outline ? (
            <div className="outline-snapshot">
              <h3 className="outline-title">{detail.outline.title}</h3>
              {detail.outline.sections.map((section, index) => <div key={section.id} className="outline-section"><span>{String(index + 1).padStart(2, '0')}</span><div><div className="eyebrow-label">{section.heading}</div><p className="text-secondary">{section.goal}</p></div></div>)}
            </div>
          ) : (
            <p className="text-secondary">No outline has been materialized for this session.</p>
          )}
        </section>

        <section className="bento-card panel-card detail-version-card">
          <div className="detail-section-heading"><div><span className="eyebrow">EDITORIAL STATUS</span><h2 className="card-title">Latest version</h2></div><span className="detail-count">v{detail.latest_version?.version_number || 1}</span></div>
          {detail.latest_version ? (
            <div className="version-summary">
              <p>{detail.latest_version.title || 'Untitled version'}</p>
              <div className="version-metrics"><span>{detail.latest_version.word_count.toLocaleString()} words</span><span>{detail.latest_version.sources_count} sources</span><span>{detail.latest_version.editor_status.replaceAll('_', ' ')}</span></div>
              {detail.latest_version.content_markdown ? <Link className="button button-primary" to={`/sessions/${sessionId}/output`}>Read the full article <span aria-hidden="true">↗</span></Link> : <span className="text-secondary">The article is not ready to read yet.</span>}
            </div>
          ) : (
            <p className="text-secondary">No version has been materialized yet.</p>
          )}
        </section>

        <section className="bento-card panel-card detail-article-card">
          <div className="detail-section-heading"><div><span className="eyebrow">DRAFT PREVIEW</span><h2 className="card-title">The article</h2></div>{detail.latest_version?.content_markdown ? <Link to={`/sessions/${sessionId}/output`} className="text-link">Open full article ↗</Link> : null}</div>
          {detail.latest_version?.content_markdown ? <div className="detail-article-preview"><MarkdownArticle markdown={detail.latest_version.content_markdown}/></div> : <p className="detail-pending">The writing stage will appear here once a draft has been generated.</p>}
        </section>

        <section className="bento-card panel-card detail-wide-card">
          <div className="detail-section-heading"><div><span className="eyebrow">YOUR CHECKPOINTS</span><h2 className="card-title">Review history</h2></div><span className="detail-count">{detail.review_events.length} events</span></div>
          {detail.review_events.length === 0 ? (
            <p className="detail-pending">No review decisions have been recorded for this story yet.</p>
          ) : (
            <ol className="detail-event-list">{detail.review_events.map((event) => <li key={event.event_id}><span className="review-event-mark">✓</span><div><strong>{event.action.replaceAll('_', ' ')}</strong><p>{event.feedback_text || 'No feedback added.'}</p></div><time dateTime={event.created_at}>{new Date(event.created_at).toLocaleDateString()}</time></li>)}</ol>
          )}
        </section>

        <section className="bento-card panel-card detail-wide-card detail-runs-card">
          <div className="detail-section-heading"><div><span className="eyebrow">GENERATION COST BREAKDOWN</span><h2 className="card-title">Workflow runs</h2></div><strong className="detail-total-cost">${detail.total_cost_usd.toFixed(4)} total</strong></div>
          {detail.agent_runs.length === 0 ? (
            <p className="detail-pending">No agent runs have been recorded yet.</p>
          ) : (
            <ul className="agent-cost-list">{detail.agent_runs.map((run) => <li key={run.run_id}><div className="agent-cost-stage"><span className={`run-state-dot run-state-${run.status.toLowerCase()}`}/><div><strong>{run.stage.replaceAll('_', ' ')}</strong><small>{run.status.toLowerCase()} · {run.total_tokens.toLocaleString()} tokens</small>{run.error_message ? <small className="agent-run-error">{run.error_message}</small> : null}</div></div><strong>${run.cost_usd.toFixed(6)}</strong></li>)}</ul>
          )}
        </section>
      </div>
    </div>
  );
};

export default SessionDetailPage;
