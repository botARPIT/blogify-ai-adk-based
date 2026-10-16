import React, { useEffect, useRef, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { toast } from 'sonner';
import { generateBlog, getTones, type GenerateBlogRequest, type ToneOption } from '../lib/api/blogs';
import { getRouteForStatus } from '../lib/session-routing';
import SessionLibrary from '../components/session/SessionLibrary';
import { useBudgetPolling } from '../hooks/useBudgetPolling';

const DashboardPage: React.FC = () => {
  const practicalTone: ToneOption = {
    value: 'practical',
    label: 'Practical',
    description: 'Clear, useful guidance readers can put into action.',
  };
  const [topic, setTopic] = useState('');
  const [audience, setAudience] = useState('');
  const [tone, setTone] = useState(practicalTone.value);
  const [tones, setTones] = useState<ToneOption[]>([practicalTone]);
  const [tonesLoading, setTonesLoading] = useState(true);
  const [tonesUnavailable, setTonesUnavailable] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const { budget, error: budgetError } = useBudgetPolling();
  const navigate = useNavigate();
  const idempotencyKeyRef = useRef<string | null>(null);

  useEffect(() => {
    let active = true;
    getTones()
      .then(({ items }) => {
        if (!active || items.length === 0) return;
        setTones(items);
        setTone((currentTone) =>
          items.some((option) => option.value === currentTone) ? currentTone : items[0].value,
        );
        setTonesUnavailable(false);
      })
      .catch(() => {
        if (active) setTonesUnavailable(true);
      })
      .finally(() => {
        if (active) setTonesLoading(false);
      });

    return () => {
      active = false;
    };
  }, []);

  const selectedTone = tones.find((option) => option.value === tone) ?? practicalTone;

  const handleGenerate = async (event: React.FormEvent) => {
    event.preventDefault();
    if (topic.trim().length < 10) { setError('Add a little more detail. Topics need at least 10 characters.'); return; }
    if (!idempotencyKeyRef.current) idempotencyKeyRef.current = crypto.randomUUID();
    setLoading(true);
    setError('');
    try {
      const payload: GenerateBlogRequest = { topic: topic.trim(), audience: audience.trim() || 'general readers', tone, idempotencyKey: idempotencyKeyRef.current };
      const response = await generateBlog(payload);
      idempotencyKeyRef.current = null;
      toast.success('Your story is underway', { description: 'We’ll bring you back when it’s time to review.' });
      navigate(getRouteForStatus(String(response.session_id), response.status));
    } catch (err) {
      const message = err instanceof Error ? err.message : 'We couldn’t start this session. Try again.';
      setError(message);
      toast.error('Couldn’t start your story', { description: message });
    } finally { setLoading(false); }
  };

  return <div className="workspace-content page-enter">
    <section className="welcome-header"><div><span className="eyebrow">YOUR EDITORIAL DESK</span><h1>Make room for <em>good ideas.</em></h1><p>Pick up where you left off, or give a new story its first shape.</p></div><div className="welcome-date"><span className="welcome-spark">✳</span><span>ONE THOUGHTFUL STEP AT A TIME</span></div></section>

    <section className="dashboard-hero-grid">
      <form className="compose-card" onSubmit={(event) => void handleGenerate(event)}>
        <div className="compose-heading"><span className="compose-icon">✎</span><div><span className="eyebrow">START SOMETHING NEW</span><h2>What’s on your mind?</h2></div></div>
        <div className="field-group"><label htmlFor="story-topic">Your topic</label><input id="story-topic" className="field-input topic-input" value={topic} onChange={(event) => setTopic(event.target.value)} placeholder="e.g. Why small rituals make teams stronger" minLength={10} maxLength={500} required aria-describedby="topic-hint"/><div id="topic-hint" className="field-hint"><span>Start with an idea, a question, or a point of view.</span><span>{topic.length}/500</span></div></div>
        <div className="field-row"><div className="field-group"><label htmlFor="story-audience">Who’s it for?</label><input id="story-audience" className="field-input" value={audience} onChange={(event) => setAudience(event.target.value)} placeholder="e.g. Curious founders" maxLength={255}/></div><div className="field-group"><label htmlFor="story-tone">What should it sound like?</label><select id="story-tone" className="field-input field-select" value={tone} onChange={(event) => setTone(event.target.value)} aria-describedby="tone-hint"><option value="practical">Practical</option>{tones.filter((option) => option.value !== 'practical').map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}</select><div id="tone-hint" className="field-hint" aria-live="polite">{tonesUnavailable ? 'Tone options are unavailable right now. Practical remains available.' : tonesLoading ? 'Loading tone options…' : selectedTone.description}</div></div></div>
        {error && <div className="inline-alert" role="alert">{error}</div>}
        <div className="compose-footer"><span><i /> You’ll review the outline before we write.</span><button className="button button-primary" type="submit" disabled={loading}>{loading ? <><span className="spinner" /> Getting things ready…</> : <>Build my outline <span aria-hidden="true">↗</span></>}</button></div>
      </form>
      <aside className="desk-aside">
        <div className="flow-card"><div className="flow-card-top"><span className="eyebrow">A LITTLE STRUCTURE</span><span className="flow-spark">✳</span></div><h2>From your idea<br />to <em>something real.</em></h2><ol className="mini-flow"><li><span className="flow-index">01</span><span>Shape a brief</span><i>✓</i></li><li className="flow-checkpoint"><span className="flow-index">02</span><span>Approve the outline</span><i>YOU</i></li><li><span className="flow-index">03</span><span>Research & write</span><i>✳</i></li><li className="flow-checkpoint"><span className="flow-index">04</span><span>Review the draft</span><i>YOU</i></li></ol><Link to="/#workflow" className="flow-link">See how the process works <span aria-hidden="true">↗</span></Link></div>
        <div className="usage-card"><div><span className="eyebrow">TODAY’S ROOM TO CREATE</span><Link to="/budget" aria-label="View usage and budget">↗</Link></div>{budgetError ? <p className="usage-error">Usage details are temporarily unavailable.</p> : <><strong>{budget?.daily_blog_limit_left ?? '—'} <small>blogs left today</small></strong><div className="usage-progress"><span style={{ width: `${Math.max(0, Math.min(100, ((budget?.daily_blog_limit_left ?? 0) / Math.max(1, budget?.daily_blog_limit ?? 5)) * 100))}%` }}/></div><span className="usage-meta">${(budget?.balance_usd ?? 0).toFixed(2)} available</span></>}</div>
      </aside>
    </section>

    <SessionLibrary latestOnly heading="Latest generation" eyebrow="MOST RECENT STORY" />
    <div className="dashboard-footnote"><span>✳</span> Your work is saved automatically, so you can always come back to it.</div>
  </div>;
};

export default DashboardPage;
