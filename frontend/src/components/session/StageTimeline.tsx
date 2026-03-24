import React from 'react';

interface StageTimelineProps {
  status: string;
  currentStage: string | null;
}

const STAGES = [
  { key: 'queued', label: 'Queued' },
  { key: 'intent', label: 'Intent' },
  { key: 'outline', label: 'Outline' },
  { key: 'awaiting_outline_review', label: 'Outline Review' },
  { key: 'research', label: 'Research' },
  { key: 'writer', label: 'Writing' },
  { key: 'editor', label: 'Editor Review' },
  { key: 'awaiting_human_review', label: 'Final Review' },
  { key: 'completed', label: 'Completed' },
];

function getCurrentIndex(status: string, currentStage: string | null): number {
  const candidates = [status, currentStage || ''];
  for (const value of candidates) {
    const index = STAGES.findIndex((stage) => stage.key === value);
    if (index >= 0) return index;
  }
  return 0;
}

const StageTimeline: React.FC<StageTimelineProps> = ({ status, currentStage }) => {
  const activeIndex = getCurrentIndex(status, currentStage);

  return (
    <div className="bento-card">
      <h2 className="section-title">Execution Pipeline</h2>
      <div style={{ display: 'grid', gap: 'var(--spacing-sm)' }}>
        {STAGES.map((stage, index) => {
          const complete = index < activeIndex;
          const active = index === activeIndex;
          const color = active ? 'var(--accent-color)' : complete ? 'var(--text-primary)' : 'var(--border-color)';

          return (
            <div key={stage.key} style={{ display: 'flex', alignItems: 'center', gap: 'var(--spacing-sm)', opacity: active || complete ? 1 : 0.45 }}>
              <span style={{ width: '12px', height: '12px', background: color, display: 'inline-block' }} />
              <span style={{ fontFamily: 'var(--font-display)', fontSize: '1.5rem', textTransform: 'uppercase', color }}>
                {stage.label}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
};

export default StageTimeline;
