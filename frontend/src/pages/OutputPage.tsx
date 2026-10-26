import React, { useMemo, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { toast } from 'sonner';
import { useBlogContent } from '../hooks/useBlogContent';
import { useSessionStatus } from '../hooks/useSessionStatus';
import { getRouteForStatus } from '../lib/session-routing';
import { getMarkdownHeadings } from '../lib/markdown-headings';
import SessionHeader from '../components/session/SessionHeader';
import LoadingState from '../components/state/LoadingState';
import ErrorState from '../components/state/ErrorState';
import MarkdownArticle from '../components/content/MarkdownArticle';
import MetadataPanel from '../components/content/MetadataPanel';
import { exportBlog } from '../lib/api/blogs';

const OutputPage: React.FC = () => {
  const { sessionId } = useParams<{ sessionId: string }>();
  const { content, loading, error } = useBlogContent(sessionId);
  const { session } = useSessionStatus(sessionId, false);
  const [exportFormat, setExportFormat] = useState<'pdf' | 'docx'>('pdf');
  const [exporting, setExporting] = useState(false);
  const articleMarkdown = useMemo(() => {
    const markdown = content?.content_markdown || '';
    const title = content?.title?.trim();
    if (!title) return markdown;

    const lines = markdown.split('\n');
    const titleHeadingIndex = lines.findIndex((line) => {
      const match = line.trim().match(/^#\s+(.+?)\s*#*$/);
      return match?.[1].trim() === title;
    });
    if (titleHeadingIndex >= 0) {
      lines.splice(titleHeadingIndex, 1);
      return lines.join('\n');
    }
    return markdown;
  }, [content?.content_markdown, content?.title]);
  const headings = useMemo(() => getMarkdownHeadings(articleMarkdown), [articleMarkdown]);

  const handleCopyMarkdown = async () => {
    if (!content) return;
    try {
      await navigator.clipboard.writeText(content.content_markdown);
      toast.success('Markdown copied', { description: 'The article is ready to paste into your editor.' });
    } catch (err) {
      toast.error('Copy failed', { description: err instanceof Error ? err.message : 'Unable to copy markdown.' });
    }
  };

  const handleExport = async () => {
    if (!content || !sessionId || content.status.toLowerCase() !== 'completed' || exporting) return;
    setExporting(true);
    try {
      const { blob, filename } = await exportBlog(sessionId, exportFormat);
      const objectUrl = URL.createObjectURL(blob);
      const download = document.createElement('a');
      download.href = objectUrl;
      download.download = filename || `blog-${sessionId}.${exportFormat}`;
      document.body.append(download);
      download.click();
      download.remove();
      window.setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
      toast.success('Your file is ready', { description: `Downloaded as ${exportFormat.toUpperCase()}.` });
    } catch (err) {
      toast.error('Export failed', { description: err instanceof Error ? err.message : 'Unable to export this blog.' });
    } finally {
      setExporting(false);
    }
  };

  if (!sessionId) return <ErrorState title="No session selected" message="Start a generation from the dashboard to view an article." />;
  if (loading && !content) return <LoadingState title="Opening your article" message="Preparing your finished draft for reading." />;
  if (!content) {
    if (session) return <div className="animate-in workspace-content"><SessionHeader sessionId={sessionId} title="Your article isn’t ready yet" subtitle={session.topic} status={session.status}/><div className="bento-card output-pending-card"><span className="checkpoint-icon">✳</span><h2 className="section-title">Still making its way through the workflow</h2><p className="text-secondary">{error || 'The final content has not been materialized yet. You can return to the current session stage.'}</p><Link className="button button-primary" to={getRouteForStatus(sessionId, session.status)}>Return to session <span aria-hidden="true">↗</span></Link></div></div>;
    return <ErrorState title="Article unavailable" message={error || 'Final content is not available for this session.'} />;
  }

  return <div className="animate-in workspace-content output-page">
    <SessionHeader sessionId={sessionId} title={content.title || 'Your finished article'} subtitle={content.topic} status={content.status}/>
    <div className="article-reading-layout">
      <aside className="article-reading-aside">
        <nav className="article-toc" aria-label="On this page"><span className="eyebrow">IN THIS ARTICLE</span>
          {headings.length ? <ol>{headings.map((heading) => <li className={`toc-level-${heading.level}`} key={heading.id}><a href={`#${heading.id}`}>{heading.text}</a></li>)}</ol> : <a className="toc-start-link" href="#article-start">Start reading <span aria-hidden="true">↓</span></a>}
        </nav>
        <MetadataPanel title="Article details" items={[{ label: 'Version', value: content.version_id }, { label: 'Length', value: `${content.word_count.toLocaleString()} words` }, { label: 'Sources', value: content.sources_count }, { label: 'Audience', value: content.audience || 'General readers' }]}
          footer={<div className="article-tools"><button className="button button-primary" type="button" onClick={() => void handleCopyMarkdown()}>Copy markdown <span aria-hidden="true">↗</span></button>{content.status.toLowerCase() === 'completed' && <div className="article-export"><label htmlFor="article-export-format">Download as</label><select id="article-export-format" className="field-select" value={exportFormat} onChange={(event) => setExportFormat(event.target.value as 'pdf' | 'docx')} disabled={exporting}><option value="pdf">PDF</option><option value="docx">Word document (.docx)</option></select><button className="button button-quiet" type="button" onClick={() => void handleExport()} disabled={exporting} aria-busy={exporting}>{exporting ? 'Preparing file…' : 'Download file'}</button></div>}<Link className="button button-quiet" to={`/sessions/${sessionId}`}>Session details</Link><Link className="button button-quiet" to="/dashboard">All sessions</Link></div>}/>
      </aside>
      <article className="bento-card content-frame article-reader" id="article-start">
        <div className="article-meta-line"><span>{content.audience || 'General readers'}</span><span>{content.word_count.toLocaleString()} words</span><span>{content.sources_count} sources</span></div>
        <MarkdownArticle markdown={articleMarkdown} />
        {content.sources.length > 0 ? (
          <section className="article-sources" aria-labelledby="article-sources-title">
            <div className="article-sources-heading">
              <span className="eyebrow">RESEARCH EVIDENCE</span>
              <h2 id="article-sources-title">Sources</h2>
            </div>
            <ol>
              {content.sources.map((source, index) => (
                <li key={`${source.url}-${index}`}>
                  <a href={source.url} target="_blank" rel="noreferrer noopener">
                    {source.title}
                  </a>
                  <span>{source.provider}</span>
                </li>
              ))}
            </ol>
          </section>
        ) : null}
        <div className="article-endmark" aria-label="End of article"><i /><span>✳</span><i /></div>
      </article>
    </div>
  </div>;
};

export default OutputPage;
