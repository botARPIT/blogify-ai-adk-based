import React, { useEffect, useState } from 'react';
import { getBlogInsights, type BlogInsights } from '../lib/api/blogs';
import LoadingState from '../components/state/LoadingState';
import ErrorState from '../components/state/ErrorState';
import GenerationChart from '../components/insights/GenerationChart';
import CostByBlogChart from '../components/insights/CostByBlogChart';
import { Link } from 'react-router-dom';

const PERIODS = [7, 30, 90] as const;

const InsightsPage: React.FC = () => {
  const [period, setPeriod] = useState<number>(30);
  const [insights, setInsights] = useState<BlogInsights | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    let active = true;
    setLoading(true);
    getBlogInsights(period)
      .then((response) => { if (active) { setInsights(response); setError(''); } })
      .catch((err: unknown) => { if (active) setError(err instanceof Error ? err.message : 'Insights could not be loaded.'); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [period]);

  if (loading && !insights) return <LoadingState title="Gathering your insights" message="Looking across your recent blog sessions and generation costs."/>;
  if (error && !insights) return <ErrorState title="Insights are unavailable" message={error}/>;
  if (!insights) return <ErrorState title="Insights are unavailable" message="No usage data was returned."/>;

  return <div className="workspace-content page-enter insights-page">
    <header className="insights-heading">
      <div><span className="eyebrow">A CLEARER VIEW OF YOUR WORK</span><h1>Ideas, in <em>motion.</em></h1><p>Track the stories you make and what each generation uses.</p></div>
      <label className="insights-period">Time period
        <select value={period} onChange={(event) => setPeriod(Number(event.target.value))}>
          {PERIODS.map((days) => <option key={days} value={days}>Last {days} days</option>)}
        </select>
      </label>
    </header>
    {error ? <div className="inline-alert" role="alert">Could not refresh these insights: {error}</div> : null}
    <section className="insight-stat-grid" aria-label="Summary metrics">
      <article className="insight-stat-card"><span>COMPLETED</span><strong>{insights.completed_count}</strong><small>approved and ready</small></article>
      <article className="insight-stat-card"><span>FAILED</span><strong>{insights.failed_count}</strong><small>sessions that stopped</small></article>
      <article className="insight-stat-card"><span>TOTAL GENERATION COST</span><strong>${insights.total_cost_usd.toFixed(4)}</strong><small>recorded in this period</small></article>
    </section>
    <section className="insight-charts-grid">
      <article className="insight-panel generation-panel">
        <div className="insight-panel-heading"><div><span className="eyebrow">PUBLISHING RHYTHM</span><h2>Stories by day</h2></div><span className="chart-key"><i/> Not failed</span></div>
        <GenerationChart data={insights.daily}/>
      </article>
      <article className="insight-panel cost-panel">
        <div className="insight-panel-heading"><div><span className="eyebrow">COST PER GENERATION · NON-FAILED</span><h2>Recent story spend</h2></div><span className="chart-caption">Latest 12</span></div>
        <CostByBlogChart data={insights.blog_costs}/>
      </article>
    </section>
    {insights.total_generated === 0 ? <p className="insights-footnote">Your charts will fill in as soon as a non-failed story is generated in this period.</p> : <p className="insights-footnote">Generation and cost charts exclude failed, rejected, and cancelled sessions. Browse all stories in <Link to="/blogs">My blogs</Link>; open any story for stage-level usage and review history.</p>}
  </div>;
};

export default InsightsPage;
