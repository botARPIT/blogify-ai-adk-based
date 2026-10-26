import React from 'react';
import { Link } from 'react-router-dom';
import type { BlogCostInsight } from '../../lib/api/blogs';

interface CostByBlogChartProps {
  data: BlogCostInsight[];
}

const CostByBlogChart: React.FC<CostByBlogChartProps> = ({ data }) => {
  const highestCost = Math.max(0, ...data.map((item) => item.cost_usd));

  if (!data.length) return <p className="chart-empty-note">No stories were generated in this period.</p>;

  return <ol className="cost-chart-list" aria-label="Cost for each recent blog generation">
    {data.map((item) => {
      const width = highestCost > 0 ? Math.max(2, (item.cost_usd / highestCost) * 100) : 2;
      return <li className="cost-chart-row" key={item.session_id}>
        <div className="cost-chart-copy">
          <Link to={`/sessions/${item.session_id}`} title={item.topic}>{item.topic}</Link>
          <span>{new Date(item.created_at).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })} <i /> {item.status.toLowerCase().replaceAll('_', ' ')}</span>
        </div>
        <div className="cost-chart-track" aria-hidden="true"><span style={{ width: `${width}%` }}/></div>
        <strong className="cost-chart-value" aria-label={`$${item.cost_usd.toFixed(4)}`}>${item.cost_usd.toFixed(4)}</strong>
      </li>;
    })}
  </ol>;
};

export default CostByBlogChart;
