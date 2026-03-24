import React from 'react';
import { Link, useParams } from 'react-router-dom';
import { toast } from 'sonner';
import { useBlogContent } from '../hooks/useBlogContent';
import { useSessionStatus } from '../hooks/useSessionStatus';
import { getRouteForStatus } from '../lib/session-routing';
import SessionHeader from '../components/session/SessionHeader';
import LoadingState from '../components/state/LoadingState';
import ErrorState from '../components/state/ErrorState';
import MarkdownArticle from '../components/content/MarkdownArticle';
import MetadataPanel from '../components/content/MetadataPanel';

const OutputPage: React.FC = () => {
  const { sessionId } = useParams<{ sessionId: string }>();
  const { content, loading, error } = useBlogContent(sessionId);
  const { session } = useSessionStatus(sessionId, false);

  if (!sessionId) {
    return <ErrorState title="No Session Selected" message="Start a generation from the dashboard to view output." />;
  }

  if (loading && !content) {
    return <LoadingState title="Loading output..." message="Fetching the latest canonical content artifact." />;
  }

  if (!content) {
    if (session) {
      return (
        <div className="animate-in">
          <SessionHeader
            sessionId={sessionId}
            title="Output Not Ready"
            subtitle={session.topic}
            status={session.status}
          />
          <div className="bento-card">
            <p className="text-secondary" style={{ marginBottom: 'var(--spacing-md)' }}>
              {error || 'The final content has not been materialized yet for this session.'}
            </p>
            <Link className="brutalist-button secondary" to={getRouteForStatus(sessionId, session.status)}>
              Return To Active Session
            </Link>
          </div>
        </div>
      );
    }
    return <ErrorState title="Output Unavailable" message={error || 'Final content is not available for this session.'} />;
  }

  return (
    <div className="animate-in page-shell">
      <SessionHeader
        sessionId={sessionId}
        title={content.title || 'Final Output'}
        subtitle={content.topic}
        status={content.status}
      />

      <div className="content-grid">
        <article className="bento-card panel-card content-frame">
          <div className="article-meta-line">
            <span>{content.audience || 'General audience'}</span>
            <span>{content.word_count} words</span>
            <span>{content.sources_count} sources</span>
          </div>
          <MarkdownArticle markdown={content.content_markdown} />
        </article>

        <div className="aside-stack">
          <MetadataPanel
            title="Publication"
            items={[
              { label: 'Version', value: content.version_id },
              { label: 'Words', value: content.word_count },
              { label: 'Sources', value: content.sources_count },
              { label: 'Audience', value: content.audience || 'General' },
              { label: 'Status', value: content.status },
            ]}
            footer={
              <div style={{ display: 'grid', gap: '0.75rem' }}>
                <Link className="brutalist-button secondary" to={`/sessions/${sessionId}`}>
                  Open Session Detail
                </Link>
                <button
                  className="brutalist-button secondary"
                  onClick={() => void handleCopyMarkdown()}
                >
                  Copy Markdown
                </button>
                <Link className="brutalist-button secondary" to="/">
                  Back To Dashboard
                </Link>
              </div>
            }
          />
        </div>
      </div>
    </div>
  );
};

export default OutputPage;
  const handleCopyMarkdown = async () => {
    if (!content) return;
    try {
      await navigator.clipboard.writeText(content.content_markdown);
      toast.success('Markdown copied', {
        description: 'The final blog content is now on your clipboard.',
      });
    } catch (err) {
      toast.error('Copy failed', {
        description: err instanceof Error ? err.message : 'Unable to copy markdown.',
      });
    }
  };
