import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { toast } from 'sonner';
import {
  generateBlog,
  getBudget,
  getSession,
  type BudgetSnapshot,
  type GenerateBlogRequest,
} from '../lib/api/blogs';
import { getRouteForStatus } from '../lib/session-routing';
import StatusBadge from '../components/session/StatusBadge';
import LoadingState from '../components/state/LoadingState';

interface RecentSession {
  sessionId: string;
  topic: string;
  audience: string;
  tone: string;
  status: string;
  timestamp: number;
}

const DashboardPage: React.FC = () => {
  const [topic, setTopic] = useState('');
  const [audience, setAudience] = useState('');
  const [tone, setTone] = useState('Practical');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [recentSessions, setRecentSessions] = useState<RecentSession[]>([]);
  const [budget, setBudget] = useState<BudgetSnapshot | null>(null);
  const [budgetError, setBudgetError] = useState('');
  const [hydrated, setHydrated] = useState(false);
  const navigate = useNavigate();

  useEffect(() => {
    try {
      const stored = localStorage.getItem('blogify:recentSessions');
      if (stored) {
        setRecentSessions(JSON.parse(stored));
      }
    } catch (e) {
      console.error('Failed to parse recent sessions', e);
    } finally {
      setHydrated(true);
    }
  }, []);

  useEffect(() => {
    if (!hydrated) return;

    getBudget()
      .then((snapshot) => {
        setBudget(snapshot);
        setBudgetError('');
      })
      .catch((err) => {
        setBudgetError(err instanceof Error ? err.message : 'Failed to load budget');
      });
  }, [hydrated]);

  useEffect(() => {
    if (!hydrated || recentSessions.length === 0) return;

    let isActive = true;
    const refreshRecentStatuses = async () => {
      const nextSessions = await Promise.all(
        recentSessions.map(async (session) => {
          try {
            const latest = await getSession(session.sessionId);
            return { ...session, status: latest.status };
          } catch {
            return session;
          }
        }),
      );
      if (!isActive) return;
      setRecentSessions(nextSessions);
      localStorage.setItem('blogify:recentSessions', JSON.stringify(nextSessions));
    };

    refreshRecentStatuses().catch(() => undefined);
    return () => {
      isActive = false;
    };
  }, [hydrated, recentSessions.length]);

  const saveRecentSession = (nextSession: RecentSession) => {
    const updated = [nextSession, ...recentSessions.filter((session) => session.sessionId !== nextSession.sessionId)].slice(0, 10);
    localStorage.setItem('blogify:recentSessions', JSON.stringify(updated));
    setRecentSessions(updated);
  };

  const navigateToSession = (session: RecentSession) => {
    navigate(getRouteForStatus(session.sessionId, session.status));
  };

  const getActionLabel = (status: string) => {
    switch (status) {
      case 'awaiting_outline_review':
        return 'Review Outline';
      case 'awaiting_human_review':
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
    
    setLoading(true);
    setError('');

    try {
      const payload: GenerateBlogRequest = {
        topic,
        audience: audience || 'general readers',
        tone,
      };

      const data = await generateBlog(payload);

      const sessionState: RecentSession = {
        sessionId: data.session_id,
        topic,
        audience: audience || 'general readers',
        tone,
        status: data.status,
        timestamp: Date.now(),
      };

      saveRecentSession(sessionState);
      toast.success('Blog generation queued', {
        description: 'The canonical workflow is now processing your request.',
      });
      navigate(getRouteForStatus(data.session_id, data.status));
    } catch (err: any) {
      const message = err.message || 'Generation failed';
      setError(message);
      toast.error('Failed to queue blog generation', { description: message });
    } finally {
      setLoading(false);
    }
  };

  if (!hydrated) {
    return <LoadingState title="Booting dashboard..." message="Recovering your recent canonical sessions." />;
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

      <div className="dashboard-grid">
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
                style={{ fontSize: 'clamp(1rem, 3vw, 1.5rem)' }}
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
                style={{ fontSize: 'clamp(1rem, 3vw, 1.5rem)' }}
              />
            </div>
            
            <button 
              className="brutalist-button"
              type="submit" 
              disabled={loading}
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
            <ul className="session-list">
              {recentSessions.map((session) => (
                <li key={session.sessionId} className="session-list-item">
                  <div className="session-list-row">
                    <div className="session-list-copy">
                      <h4 className="session-list-title">{session.topic}</h4>
                      <div className="text-secondary session-list-meta">
                        Audience: {session.audience}
                      </div>
                      <div className="text-secondary session-list-meta">Tone: {session.tone}</div>
                      <div className="text-secondary session-list-meta">Session {session.sessionId}</div>
                    </div>
                    <div className="session-list-actions">
                      <StatusBadge status={session.status} />
                      <button
                        className="brutalist-button secondary"
                        onClick={() => navigateToSession(session)}
                        style={{ padding: '0.5rem 1rem', fontSize: '0.875rem' }}
                      >
                        {getActionLabel(session.status)}
                      </button>
                    </div>
                  </div>
                </li>
              ))}
            </ul>
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
              <div className="meta-row">
                <span className="eyebrow-label" style={{ margin: 0 }}>Daily Spend</span>
                <span className="meta-value">${budget.daily_spent_usd.toFixed(2)}</span>
              </div>
              <div className="meta-row">
                <span className="eyebrow-label" style={{ margin: 0 }}>Daily Tokens</span>
                <span className="meta-value">{budget.daily_spent_tokens}</span>
              </div>
              <div className="meta-row">
                <span className="eyebrow-label" style={{ margin: 0 }}>Active Sessions</span>
                <span className="meta-value">{budget.active_sessions}</span>
              </div>
              <button className="brutalist-button secondary" type="button" onClick={() => navigate('/budget')}>
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
