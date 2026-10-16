import React from 'react';
import type { DailyBlogInsight } from '../../lib/api/blogs';

interface GenerationChartProps {
  data: DailyBlogInsight[];
}

const dateLabel = (value: string, options?: Intl.DateTimeFormatOptions) =>
  new Date(`${value}T12:00:00`).toLocaleDateString(undefined, options || { month: 'short', day: 'numeric' });

const GenerationChart: React.FC<GenerationChartProps> = ({ data }) => {
  const width = 720;
  const height = 250;
  const left = 40;
  const right = 16;
  const top = 20;
  const bottom = 36;
  const plotWidth = width - left - right;
  const plotHeight = height - top - bottom;
  const peak = Math.max(1, ...data.map((item) => item.generated_count));
  const points = data.map((item, index) => {
    const x = left + (data.length <= 1 ? plotWidth / 2 : (index / (data.length - 1)) * plotWidth);
    const y = top + plotHeight - (item.generated_count / peak) * plotHeight;
    return { x, y, item };
  });
  const line = points.map((point) => `${point.x},${point.y}`).join(' ');
  const area = points.length ? `M ${points[0].x},${top + plotHeight} L ${line.replaceAll(' ', ' L ')} L ${points[points.length - 1].x},${top + plotHeight} Z` : '';
  const labelIndices = [...new Set([0, Math.floor((data.length - 1) / 3), Math.floor(((data.length - 1) * 2) / 3), data.length - 1])].filter((index) => index >= 0);

  return (
    <div className="insight-chart-wrap">
      {data.every((item) => item.generated_count === 0) ? <div className="chart-empty-note">Your daily activity will take shape here as you create stories.</div> : null}
      <svg className="generation-chart" viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Blog generations per day over the selected period">
        <defs><linearGradient id="generation-area" x1="0" x2="0" y1="0" y2="1"><stop offset="0%" stopColor="#c46c4e" stopOpacity=".24"/><stop offset="100%" stopColor="#c46c4e" stopOpacity="0"/></linearGradient></defs>
        {[0, 0.5, 1].map((fraction) => {
          const y = top + plotHeight * fraction;
          const value = Math.round(peak * (1 - fraction));
          return <g key={fraction}><line x1={left} x2={width - right} y1={y} y2={y} className="chart-gridline"/><text x={left - 12} y={y + 4} className="chart-axis-label" textAnchor="end">{value}</text></g>;
        })}
        {points.length > 1 && <path d={area} fill="url(#generation-area)"/>}
        {points.length > 1 && <polyline points={line} className="generation-line"/>}
        {points.map(({ x, y, item }) => <circle key={item.date} cx={x} cy={y} r="3.5" className="generation-point"><title>{dateLabel(item.date, { month: 'long', day: 'numeric' })}: {item.generated_count} stories</title></circle>)}
        {labelIndices.map((index) => points[index] && <text key={index} x={points[index].x} y={height - 9} className="chart-axis-label" textAnchor={index === 0 ? 'start' : index === points.length - 1 ? 'end' : 'middle'}>{dateLabel(points[index].item.date)}</text>)}
      </svg>
    </div>
  );
};

export default GenerationChart;
