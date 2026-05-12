import React, { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { toast } from 'sonner';
import {
  generateBlog,
  getSession,
  getBlogSessions,
  type GenerateBlogRequest,
} from '../lib/api/blogs';
import { getRouteForStatus } from '../lib/session-routing';
import StatusBadge from '../components/session/StatusBadge';
import LoadingState from '../components/state/LoadingState';
import { useBudgetPolling } from '../hooks/useBudgetPolling';

interface SessionItem {
  session_id: number;
  topic: string;
  audience: string;
  tone: string;
  status: string;
  current_stage: string | null;
  created_at: string;
  completed_at: string | null;
}

const DashboardPage: React.FC = () => {
  const [topic, setTopic] = useState('');
  const [audience, setAudience] = useState('');
  const [tone, setTone] = useState('Practical');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [recentSessions, setRecentSessions] = useState<SessionItem[]>([]);
  const [sessionsLoading, setSessionsLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const { budget, error: budgetError } = useBudgetPolling();
  const navigate = useNavigate();
  // Idempotency key — one UUID per user-intent.
  // Kept across network retries; cleared after a terminal outcome.
  const idempotencyKeyRef = useRef<string | null>(null);
  const carouselRef = useRef<HTMLUListElement>(null);

  const scrollUp = () => {
    if (carouselRef.current) {
      carouselRef.current.scrollBy({ top: -140, behavior: 'smooth' });
    }
  };

  const scrollDown = () => {
    if (carouselRef.current) {
      carouselRef.current.scrollBy({ top: 140, behavior: 'smooth' });
    }
  };

  const fetchSessions = async (showLoading = true) => {
    if (showLoading) setRefreshing(true);
    try {
      const sessions = await getBlogSessions();
      setRecentSessions(sessions);
    } catch (err) {
      console.error('Failed to fetch sessions', err);
      toast.error('Failed to load sessions');
    } finally {
      setSessionsLoading(false);
      if (showLoading) setRefreshing(false);
    }
  };

  useEffect(() => {
    fetchSessions();
  }, []);

  const getActionLabel = (status: string) => {
    const normalizedStatus = status?.toLowerCase();
    switch (normalizedStatus) {
      case 'awaiting_outline_review':
        return 'Review Outline';
      case 'awaiting_final_review':
        return 'Review Draft';
      case 'completed':
        return 'Open Output';
      default:
        return 'Continue';
    }
  };

  const handleGenerate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!topic || topic.length < 10) {
      setError('Topic must be at least 10 characters long.');
      return;
    }

    // Generate a fresh UUID if this is a new intent (no key yet)
    if (!idempotencyKeyRef.current) {
      idempotencyKeyRef.current = crypto.randomUUID();
    }

    setLoading(true);
    setError('');

    try {
      const payload: GenerateBlogRequest = {
        topic,
        audience: audience || 'general readers',
        tone,
        idempotencyKey: idempotencyKeyRef.current,
      };

      const data = await generateBlog(payload);

      // Success → terminal outcome, clear key so next Generate is a fresh intent
      idempotencyKeyRef.current = null;

      const newSession: SessionItem = {
        session_id: data.session_id,
        topic,
        audience: audience || 'general readers',
        tone,
        status: data.status,
        current_stage: null,
        created_at: new Date().toISOString(),
        completed_at: null,
      };

      setRecentSessions([newSession, ...recentSessions]);
      toast.success('Blog generation queued', {
        description: 'The canonical workflow is now processing your request.',
      });
      navigate(getRouteForStatus(data.session_id, data.status));
    } catch (err: any) {
      // SESSION_TERMINAL → the previous run finished; auto-rotate key and advise user
      if (err?.status === 409 && err?.body?.error_code === 'SESSION_TERMINAL') {
        idempotencyKeyRef.current = null;
        setError('Previous generation already completed. Click Generate again to start a new one.');
        toast.info('Previous session was terminal', {
          description: 'A new request ID has been issued — click Generate to proceed.',
        });
      } else {
        // Transient error → keep the key so retries deduplicate
        const message = err.message || 'Generation failed';
        setError(message);
        toast.error('Failed to queue blog generation', { description: message });
      }
    } finally {
      setLoading(false);
    }
  };

  if (sessionsLoading) {
    return <LoadingState title="Booting dashboard..." message="Loading your blog sessions." />;
  }

  return (
    <div className="animate-in page-shell">
      <div className="page-header">
        <div className="page-header-copy">
          <span className="eyebrow-label">Canonical Workflow</span>
          <h1 className="page-title">Generate blog sessions with an outline review gate.</h1>
          <p className="page-subtitle">
            Start a new session, inspect recent outcomes, and keep the budget in view without losing the current editorial feel.
          </p>
        </div>
      </div>

      <div className="dashboard-grid-centered">
        <section className="bento-card panel-card composer-panel" style={{ borderLeft: '4px solid var(--accent-color)' }}>
          <h2 className="card-title">Compose A New Session</h2>
          <form onSubmit={handleGenerate}>
            <div className="mb-md">
              <label className="eyebrow-label">Topic / Concept</label>
              <input 
                className="brutalist-input"
                type="text" 
                value={topic}
                onChange={(e) => setTopic(e.target.value)}
                placeholder="e.g. quantum cryptography"
                required
              />
            </div>
            
            <div className="mb-md">
              <label className="eyebrow-label">Target Audience</label>
              <input 
                className="brutalist-input"
                type="text" 
                value={audience}
                onChange={(e) => setAudience(e.target.value)}
                placeholder="e.g. Technical SEOs"
              />
            </div>

            <div className="mb-md">
              <label className="eyebrow-label">Tone Direction</label>
              <input
                className="brutalist-input"
                type="text"
                value={tone}
                onChange={(e) => setTone(e.target.value)}
                placeholder="e.g. practical, executive, technical"
              />
            </div>
            
            <button 
              className="brutalist-button"
              type="submit" 
              disabled={loading}
              style={{ width: '100%', padding: '1rem', fontSize: '1.2rem', marginTop: '0.5rem' }}
            >
              {loading ? <span className="spinner"></span> : null}
              {loading ? 'Queueing Session...' : 'Commence Generation'}
            </button>
          </form>
          {error && <div className="mb-sm" style={{ color: 'var(--error-color)', fontWeight: 'bold', marginTop: '1rem' }}>{error}</div>}
        </section>

        <section className="bento-card panel-card recent-sessions-panel">
          <div className="panel-header-row">
            <h2 className="card-title">Recent Sessions</h2>
            <span className="eyebrow-label">Resume canonical flow</span>
          </div>
          {recentSessions.length === 0 ? (
            <p className="text-secondary italic">No recent sessions found.</p>
          ) : (
            <div className="vertical-carousel-wrapper">
              <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '0.5rem', marginBottom: '0.75rem' }}>
                <button type="button" onClick={scrollUp} className="brutalist-button secondary" style={{ padding: '0.3rem 0.6rem', fontSize: '0.9rem' }} aria-label="Scroll Up">
                  ▲
                </button>
                <button type="button" onClick={scrollDown} className="brutalist-button secondary" style={{ padding: '0.3rem 0.6rem', fontSize: '0.9rem' }} aria-label="Scroll Down">
                  ▼
                </button>
              </div>
              <ul 
                className="session-list" 
                ref={carouselRef}
                style={{ 
                  maxHeight: '400px', 
                  overflowY: 'auto', 
                  scrollSnapType: 'y mandatory',
                  scrollbarWidth: 'none',
                  msOverflowStyle: 'none'
                }}
              >
                <style>{`.session-list::-webkit-scrollbar { display: none; }`}</style>
                {recentSessions.map((session) => (
                  <li 
                    key={session.session_id} 
                    className="session-list-item"
                    style={{ scrollSnapAlign: 'start' }}
                  >
                  <div className="session-list-row">
                    <div className="session-list-copy">
                      <h4 className="session-list-title">{session.topic}</h4>
                      <div className="text-secondary session-list-meta">
                        Audience: {session.audience}
                      </div>
                      <div className="text-secondary session-list-meta">Tone: {session.tone}</div>
                      <div className="text-secondary session-list-meta">Session {session.session_id}</div>
                    </div>
                    <div className="session-list-actions">
                      <StatusBadge status={session.status} />
                      <button
                        className="brutalist-button secondary"
                        onClick={() => navigate(getRouteForStatus(String(session.session_id), session.status))}
                      >
                        {getActionLabel(session.status)}
                      </button>
                    </div>
                  </div>
                </li>
              ))}
              </ul>
            </div>
          )}
        </section>

        <aside className="bento-card panel-card budget-snapshot-panel">
          <div className="panel-header-row">
            <h2 className="card-title">Budget Snapshot</h2>
            <span className="eyebrow-label">Live limits</span>
          </div>
          {budgetError ? (
            <p className="text-secondary">{budgetError}</p>
          ) : budget ? (
            <div className="stat-stack">
              <div className="meta-row" style={{ flexDirection: 'column', alignItems: 'stretch' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '0.2rem' }}>
                  <span className="eyebrow-label" style={{ margin: 0 }}>Daily Blogs Remaining</span>
                  <span className="meta-value">{budget.daily_blog_limit_left || 0} / 100</span>
                </div>
                <div className="progress-bar-container">
                  <div 
                    className="progress-bar-fill" 
                    style={{ width: `${Math.max(0, Math.min(100, ((budget.daily_blog_limit_left || 0) / 100) * 100))}%` }} 
                  />
                </div>
              </div>
              <div className="meta-row">
                <span className="eyebrow-label" style={{ margin: 0 }}>Remaining Credits</span>
                <span className="meta-value">{(budget.balance_tokens || 0).toLocaleString()}</span>
              </div>
              <div className="meta-row">
                <span className="eyebrow-label" style={{ margin: 0 }}>Balance USD</span>
                <span className="meta-value" style={{ color: 'var(--accent-color)' }}>${(budget.balance_usd || 0).toFixed(2)}</span>
              </div>
              <button className="brutalist-button secondary" type="button" onClick={() => navigate('/budget')} style={{ marginTop: '1rem' }}>
                Open Budget View
              </button>
            </div>
          ) : (
            <p className="text-secondary">Budget data is loading.</p>
          )}
        </aside>
      </div>
    </div>
  );
};

export default DashboardPage;