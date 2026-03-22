import React from 'react';

const GenerationProgress = ({ jobData }) => {
  const { topic = "Future of AI", estimatedWords = 1200, budget = 0.15, currentStage = 3, thinking = "Searching Tavily for recent healthcare case studies..." } = jobData || {};

  const stages = [
    { name: "Intent Clarification", icon: "check", completed: currentStage > 1, active: currentStage === 1 },
    { name: "Outline Generation", icon: "check", completed: currentStage > 2, active: currentStage === 2 },
    { name: "Researching", icon: "search", completed: currentStage > 3, active: currentStage === 3 },
    { name: "Writing", icon: "edit_note", completed: currentStage > 4, active: currentStage === 4 },
    { name: "Final Review", icon: "visibility", completed: currentStage > 5, active: currentStage === 5 },
  ];

  return (
    <div data-theme="azure" className="flex h-screen bg-surface">
      {/* SideNavBar */}
      <aside className="fixed left-0 top-0 h-full w-64 z-40 bg-[#111C2D] flex flex-col pt-20 pb-6 px-4">
        <div className="mb-8">
          <h2 className="text-primary font-black uppercase text-[0.7rem] tracking-widest mb-4">Job Details</h2>
          <div className="space-y-4">
            <div className="flex items-center gap-3 text-on-surface-variant">
              <span className="material-symbols-outlined text-sm">topic</span>
              <div className="flex flex-col">
                <span className="text-[0.65rem] uppercase text-outline/60 font-bold">Topic</span>
                <span className="text-xs font-medium">{topic}</span>
              </div>
            </div>
            <div className="flex items-center gap-3 text-on-surface-variant">
              <span className="material-symbols-outlined text-sm">format_size</span>
              <div className="flex flex-col">
                <span className="text-[0.65rem] uppercase text-outline/60 font-bold">Estimated Words</span>
                <span className="text-xs font-medium">{estimatedWords}</span>
              </div>
            </div>
            <div className="flex items-center gap-3 text-on-surface-variant">
              <span className="material-symbols-outlined text-sm">payments</span>
              <div className="flex flex-col">
                <span className="text-[0.65rem] uppercase text-outline/60 font-bold">Budget Remaining</span>
                <span className="text-xs font-medium">${budget}</span>
              </div>
            </div>
          </div>
        </div>
        <div className="mt-auto bg-surface-container-high/40 p-4 rounded-xl border border-outline-variant/10">
          <div className="flex items-center gap-2 mb-2">
            <div className="w-2 h-2 rounded-full bg-primary azure-pulse"></div>
            <span className="text-[0.7rem] font-bold text-primary tracking-wide uppercase">Agent Thinking...</span>
          </div>
          <p className="text-xs text-on-surface-variant italic leading-relaxed">{thinking}</p>
        </div>
      </aside>

      {/* Main Content */}
      <main className="ml-64 flex-1 overflow-y-auto p-12">
        <div className="max-w-4xl mx-auto space-y-16">
          {/* Stepper Pipeline */}
          <section>
            <div className="flex justify-between relative">
              <div className="absolute top-5 left-0 w-full h-[2px] bg-surface-container-highest z-0">
                <div 
                  className="h-full bg-primary-container transition-all duration-1000" 
                  style={{ width: `${(Math.min(currentStage - 1, 4) / 4) * 100}%` }}
                ></div>
              </div>
              {stages.map((stage, i) => (
                <div key={i} className="relative z-10 flex flex-col items-center gap-3">
                  <div className={`w-10 h-10 rounded-full flex items-center justify-center transition-all duration-500 ${
                    stage.completed ? 'bg-primary text-on-primary shadow-[0_0_15px_rgba(173,198,255,0.3)]' : 
                    stage.active ? 'bg-surface-container-highest border-2 border-primary text-primary azure-pulse' : 
                    'bg-surface-container-lowest border-2 border-outline-variant/30 text-outline-variant'
                  }`}>
                    <span className="material-symbols-outlined text-xl">{stage.completed ? 'check' : stage.icon}</span>
                  </div>
                  <span className={`text-[0.7rem] font-bold uppercase tracking-wider ${
                    stage.completed || stage.active ? 'text-primary' : 'text-outline-variant/50'
                  }`}>{stage.name}</span>
                </div>
              ))}
            </div>
          </section>

          {/* Live Research Feed (Placeholder) */}
          <section className="space-y-6">
            <div className="flex items-center justify-between">
              <h3 className="text-xl font-headline font-bold tracking-tight">Live Research Feed</h3>
              <div className="px-3 py-1 rounded-full bg-tertiary-container/20 text-tertiary text-[0.65rem] font-bold uppercase tracking-widest flex items-center gap-2">
                <span className="w-1.5 h-1.5 rounded-full bg-tertiary animate-pulse"></span>
                Active Capture
              </div>
            </div>
            <div className="grid gap-4">
              <div className="bg-surface-container-low p-5 rounded-xl border-l-2 border-primary flex items-start gap-4 hover:bg-surface-container transition-colors duration-300">
                <div className="w-8 h-8 rounded bg-primary-container/20 flex items-center justify-center text-primary flex-shrink-0">
                  <span className="material-symbols-outlined text-sm">article</span>
                </div>
                <div className="space-y-1">
                  <div className="flex items-center gap-2">
                    <span className="text-[0.65rem] font-bold text-primary uppercase">Source: Nature.com</span>
                    <span className="text-[0.65rem] text-outline-variant">• 2m ago</span>
                  </div>
                  <p className="text-sm text-on-surface leading-relaxed">Found data on AI in surgeries: Precision metrics showing a 15% reduction in invasive errors.</p>
                </div>
              </div>
            </div>
          </section>
        </div>
      </main>
    </div>
  );
};

export default GenerationProgress;
