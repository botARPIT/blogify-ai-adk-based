import React from 'react';

interface StageTimelineProps { status: string; currentStage: string | null; currentAgent?: string | null; }
const STAGES = [
  { key: 'intent', label: 'Clarify intent', hint: 'Understanding the brief' },
  { key: 'outline', label: 'Build outline', hint: 'Giving the story shape' },
  { key: 'outline-review', label: 'Approve outline', hint: 'Your first checkpoint', checkpoint: true },
  { key: 'research', label: 'Gather research', hint: 'Finding useful context' },
  { key: 'writing', label: 'Write the blog', hint: 'Building the first draft' },
  { key: 'editing', label: 'Editorial pass', hint: 'Checking clarity and flow' },
  { key: 'final-review', label: 'Review the draft', hint: 'Your final checkpoint', checkpoint: true },
  { key: 'complete', label: 'Ready to read', hint: 'Your article is finished' },
];

function stageIndex(status: string, stage: string | null, agent: string | null): number {
  const normalizedStatus = status.toLowerCase();
  const active = `${agent || ''} ${stage || ''}`.toLowerCase();
  if (normalizedStatus === 'awaiting_outline_review' || active.includes('outline_review')) return 2;
  if (normalizedStatus === 'agent_rejected') return 0;
  if (normalizedStatus === 'awaiting_final_review' || normalizedStatus === 'rejected' || active.includes('final_review') || active.includes('rejected')) return 6;
  if (normalizedStatus === 'completed') return 7;
  if (active.includes('editor')) return 5;
  if (active.includes('writer')) return 4;
  if (active.includes('research') || active.includes('revision_')) return 3;
  if (active.includes('outline')) return 1;
  if (active.includes('intent')) return 0;
  return 0;
}

const StageTimeline: React.FC<StageTimelineProps> = ({ status, currentStage, currentAgent = null }) => {
  const active = stageIndex(status, currentStage, currentAgent);
  const normalizedStatus = status.toLowerCase();
  const failed = normalizedStatus === 'failed';
  const cancelled = ['cancelled', 'rejected', 'agent_rejected'].includes(normalizedStatus);
  const complete = normalizedStatus === 'completed';
  const activeLabel = STAGES[active].label;
  const stateLabel = failed ? `Stopped during ${activeLabel}` : cancelled ? normalizedStatus : complete ? 'Complete' : normalizedStatus.replaceAll('_', ' ');

  return <section className="bento-card workflow-progress-card" aria-label="Blog generation workflow">
    <div className="workflow-progress-heading"><div><span className="eyebrow">THE STORY SO FAR</span><h2 className="section-title">A thoughtful process, step by step</h2></div><span className={`progress-pulse ${failed || cancelled ? 'is-failed' : ''}`}>{stateLabel}</span></div>
    <ol className="progress-stages">{STAGES.map((stage, index) => {
      const done = complete || index < active;
      const current = !done && index === active && !cancelled;
      return <li className={`progress-stage ${done ? 'is-done' : ''} ${current ? 'is-current' : ''} ${stage.checkpoint ? 'is-checkpoint' : ''} ${failed && current ? 'is-failed' : ''}`} key={stage.key} aria-current={current ? 'step' : undefined}>
        <span className="progress-marker">{done ? '✓' : current ? <i /> : String(index + 1).padStart(2, '0')}</span>
        <span className="progress-stage-copy"><strong>{stage.label}</strong><small>{stage.hint}</small>{stage.checkpoint && <small className="checkpoint-label">YOUR REVIEW</small>}</span>
      </li>;
    })}</ol>
    {currentAgent && !failed && !cancelled && !complete ? <p className="timeline-live-agent" role="status"><i /> Now running <strong>{currentAgent.replaceAll('_', ' ')}</strong></p> : null}
  </section>;
};

export default StageTimeline;
