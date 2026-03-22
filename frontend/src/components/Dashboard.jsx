import React from 'react';

const Dashboard = () => {
  return (
    <div className="lg:ml-64 pt-24 pb-16 px-6 md:px-10">
      {/* Hero Section / KPI Bento Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-10">
        {/* Total Generations */}
        <div className="glass-card p-6 rounded-xl border-t border-white/5 shadow-xl hover:scale-[1.01] transition-all duration-200 group">
          <div className="flex justify-between items-start mb-4">
            <span className="text-[10px] font-bold uppercase tracking-[0.1em] text-on-surface-variant">Total Generations</span>
            <span className="text-[10px] font-bold text-primary bg-primary/10 px-2 py-0.5 rounded-full">+12%</span>
          </div>
          <div className="flex items-end justify-between">
            <h3 className="text-4xl font-black text-on-surface tracking-tighter">1,284</h3>
            <span className="material-symbols-outlined text-primary-fixed-dim/30 group-hover:text-primary transition-colors">auto_stories</span>
          </div>
        </div>

        {/* Active Jobs */}
        <div className="glass-card p-6 rounded-xl border-t border-white/5 shadow-xl hover:scale-[1.01] transition-all duration-200">
          <div className="flex justify-between items-start mb-4">
            <span className="text-[10px] font-bold uppercase tracking-[0.1em] text-on-surface-variant">Active Jobs</span>
            <div className="flex gap-1">
              <div className="w-1.5 h-1.5 rounded-full bg-primary animate-pulse"></div>
              <div className="w-1.5 h-1.5 rounded-full bg-primary/30"></div>
              <div className="w-1.5 h-1.5 rounded-full bg-primary/30"></div>
            </div>
          </div>
          <div className="flex items-center gap-6">
            <div className="relative flex items-center justify-center">
              <svg className="w-12 h-12 transform -rotate-90">
                <circle className="text-white/5" cx="24" cy="24" fill="transparent" r="20" stroke="currentColor" strokeWidth="4"></circle>
                <circle className="text-primary" cx="24" cy="24" fill="transparent" r="20" stroke="currentColor" strokeDasharray="125.6" strokeDashoffset="37.6" strokeWidth="4"></circle>
              </svg>
              <span className="absolute text-[10px] font-bold">3</span>
            </div>
            <div>
              <p className="text-xl font-bold text-on-surface">3 Processing</p>
              <p className="text-[10px] uppercase font-medium text-on-surface-variant">5 in queue</p>
            </div>
          </div>
        </div>

        {/* Daily Budget */}
        <div className="glass-card p-6 rounded-xl border-t border-white/5 shadow-xl hover:scale-[1.01] transition-all duration-200">
          <span className="text-[10px] font-bold uppercase tracking-[0.1em] text-on-surface-variant block mb-4">Daily Budget</span>
          <div className="mb-4">
            <div className="flex justify-between items-end mb-2">
              <h3 className="text-2xl font-bold text-on-surface">$42.50</h3>
              <span className="text-[10px] text-on-surface-variant">$100.00 CAP</span>
            </div>
            <div className="w-full h-1.5 bg-white/5 rounded-full overflow-hidden">
              <div className="h-full bg-gradient-to-r from-primary to-primary-container" style={{ width: '42.5%' }}></div>
            </div>
          </div>
        </div>

        {/* Success Rate */}
        <div className="glass-card p-6 rounded-xl border-t border-white/5 shadow-xl hover:scale-[1.01] transition-all duration-200">
          <span className="text-[10px] font-bold uppercase tracking-[0.1em] text-on-surface-variant block mb-4">Success Rate</span>
          <div className="flex items-center justify-between">
            <h3 className="text-4xl font-black text-primary tracking-tighter">98.2%</h3>
            <div className="w-20 h-10 overflow-hidden">
              <svg className="w-full h-full" viewBox="0 0 100 40">
                <path d="M0 35 Q 20 20, 40 30 T 80 10 T 100 5" fill="none" stroke="#4edea3" strokeLinecap="round" strokeWidth="3"></path>
                <path d="M0 35 Q 20 20, 40 30 T 80 10 T 100 5 V 40 H 0 Z" fill="url(#sparkGradient)"></path>
                <defs>
                  <linearGradient id="sparkGradient" x1="0" x2="0" y1="0" y2="1">
                    <stop offset="0%" stopColor="#4edea3" stopOpacity="0.3"></stop>
                    <stop offset="100%" stopColor="#4edea3" stopOpacity="0"></stop>
                  </linearGradient>
                </defs>
              </svg>
            </div>
          </div>
        </div>
      </div>

      {/* Main Charts Area */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 mb-10">
        {/* Area Chart: Generation Latency */}
        <div className="lg:col-span-2 glass-card rounded-xl border-t border-white/5 p-8">
          <div className="flex justify-between items-center mb-10">
            <div>
              <h4 className="text-lg font-bold text-on-surface">Generation Latency (P95)</h4>
              <p className="text-xs text-on-surface-variant">Response time metrics across last 24h window</p>
            </div>
            <div className="flex gap-2">
              <div className="bg-surface-container-high px-3 py-1 rounded text-[10px] font-bold border border-white/5">24H</div>
              <div className="px-3 py-1 rounded text-[10px] font-bold text-on-surface-variant hover:bg-white/5 transition-colors cursor-pointer">7D</div>
            </div>
          </div>
          <div className="relative h-64 w-full">
            <svg className="w-full h-full overflow-visible" preserveAspectRatio="none">
              <line className="text-outline-variant opacity-10" stroke="currentColor" strokeDasharray="4" x1="0" x2="100%" y1="0%" y2="0%"></line>
              <line className="text-outline-variant opacity-10" stroke="currentColor" strokeDasharray="4" x1="0" x2="100%" y1="25%" y2="25%"></line>
              <line className="text-outline-variant opacity-10" stroke="currentColor" strokeDasharray="4" x1="0" x2="100%" y1="50%" y2="50%"></line>
              <line className="text-outline-variant opacity-10" stroke="currentColor" strokeDasharray="4" x1="0" x2="100%" y1="75%" y2="75%"></line>
              <line className="text-outline-variant opacity-10" stroke="currentColor" x1="0" x2="100%" y1="100%" y2="100%"></line>
              <path d="M0 180 Q 50 160, 100 170 T 200 140 T 300 155 T 400 120 T 500 130 T 600 100 T 700 110 T 800 80 T 900 90 T 1000 70 V 256 H 0 Z" fill="url(#areaGradient)"></path>
              <path d="M0 180 Q 50 160, 100 170 T 200 140 T 300 155 T 400 120 T 500 130 T 600 100 T 700 110 T 800 80 T 900 90 T 1000 70" fill="none" stroke="#4edea3" strokeWidth="2" vectorEffect="non-scaling-stroke"></path>
              <defs>
                <linearGradient id="areaGradient" x1="0" x2="0" y1="0" y2="1">
                  <stop offset="0%" stopColor="#4edea3" stopOpacity="0.2"></stop>
                  <stop offset="100%" stopColor="#131313" stopOpacity="0"></stop>
                </linearGradient>
              </defs>
            </svg>
            <div className="absolute top-[65px] right-[10%] group">
              <div className="w-3 h-3 bg-primary rounded-full shadow-[0_0_15px_rgba(78,222,163,0.8)] border-2 border-background"></div>
              <div className="absolute bottom-full left-1/2 -translate-x-1/2 mb-2 bg-surface-container-highest px-2 py-1 rounded text-[10px] font-bold whitespace-nowrap border border-white/10 opacity-0 group-hover:opacity-100 transition-opacity">1.4s P95</div>
            </div>
          </div>
        </div>

        {/* Bar Chart: Agent Success */}
        <div className="glass-card rounded-xl border-t border-white/5 p-8">
          <h4 className="text-lg font-bold text-on-surface mb-2">Agent Success Rate</h4>
          <p className="text-xs text-on-surface-variant mb-10">Relative performance by agent role</p>
          <div className="space-y-6">
            {[
              { label: 'Intent', value: 99.8 },
              { label: 'Outline', value: 97.5 },
              { label: 'Research', value: 94.2 },
              { label: 'Writer', value: 91.0 },
            ].map((agent) => (
              <div key={agent.label}>
                <div className="flex justify-between items-center mb-2">
                  <span className="text-[10px] font-bold uppercase tracking-widest">{agent.label}</span>
                  <span className="text-[10px] font-bold text-primary">{agent.value}%</span>
                </div>
                <div className="h-4 bg-white/5 rounded-full overflow-hidden">
                  <div className="h-full bg-primary rounded-r-lg" style={{ width: `${agent.value}%` }}></div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Lower Section: Logs & Infrastructure */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Real-time Logs */}
        <div className="lg:col-span-2 glass-card rounded-xl border-t border-white/5 overflow-hidden">
          <div className="px-6 py-4 border-b border-white/5 bg-white/2 flex justify-between items-center">
            <h4 className="text-sm font-bold uppercase tracking-widest flex items-center gap-2">
              <span className="material-symbols-outlined text-sm text-primary">list_alt</span>
              System Events
            </h4>
            <span className="text-[10px] text-primary/60 font-mono">LIVE CONNECTED</span>
          </div>
          <div className="p-2 h-[300px] overflow-y-auto font-mono text-[11px] leading-relaxed">
            {[
              { time: '14:28:44', tag: 'WRITER', color: 'text-primary', msg: 'Writer Agent completed for Job #892' },
              { time: '14:28:42', tag: 'RESEARCH', color: 'text-secondary', msg: 'External data synthesis finalized for "Quantum Computing"' },
              { time: '14:28:39', tag: 'OUTLINE', color: 'text-primary', msg: 'Outline Agent completed for Job #892' },
              { time: '14:28:35', tag: 'SYSTEM', color: 'text-on-primary-container', msg: 'New generation request received: ID_X992-B' },
              { time: '14:28:30', tag: 'INTENT', color: 'text-tertiary-container', msg: 'Intent parsed with 99.4% confidence (Job #891)' },
            ].map((log, i) => (
              <div key={i} className={`p-3 ${i % 2 !== 0 ? 'bg-surface-container-lowest' : ''} hover:bg-white/5 rounded transition-colors flex gap-4 items-start`}>
                <span className="text-on-surface-variant shrink-0">{log.time}</span>
                <span className={`${log.color} shrink-0`}>[{log.tag}]</span>
                <span className="text-on-surface">{log.msg}</span>
              </div>
            ))}
          </div>
        </div>

        {/* Circuit Breakers */}
        <div className="space-y-6">
          <div className="glass-card rounded-xl border-t border-white/5 p-6">
            <h4 className="text-sm font-bold uppercase tracking-widest mb-6">Circuit Breakers</h4>
            <div className="space-y-4">
              {[
                { name: 'Google Gemini', sub: 'Model: Pro 1.5', icon: 'token', status: 'CLOSED', state: 'Healthy' },
                { name: 'Tavily Search', sub: 'External API', icon: 'search', status: 'CLOSED', state: 'Healthy' },
                { name: 'Vector DB', sub: 'Pinecone Index', icon: 'database', status: 'IDLE', state: 'Standby', idle: true },
              ].map((cb) => (
                <div key={cb.name} className={`flex items-center justify-between p-3 rounded-lg bg-surface-container-lowest border border-white/5 ${cb.idle ? 'opacity-50' : ''}`}>
                  <div className="flex items-center gap-3">
                    <span className="material-symbols-outlined text-primary text-xl">{cb.icon}</span>
                    <div>
                      <p className="text-xs font-bold">{cb.name}</p>
                      <p className="text-[10px] text-on-surface-variant">{cb.sub}</p>
                    </div>
                  </div>
                  <div className="text-right">
                    <span className={`text-[10px] font-bold block ${cb.idle ? 'text-on-surface-variant' : 'text-primary'}`}>{cb.status}</span>
                    <span className="text-[9px] text-on-surface-variant uppercase">{cb.state}</span>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* System Info */}
          <div className="glass-card rounded-xl border border-primary/20 bg-primary/5 p-6">
            <div className="flex items-center gap-4">
              <div className="w-10 h-10 rounded-full flex items-center justify-center bg-primary/20 text-primary">
                <span className="material-symbols-outlined">rocket_launch</span>
              </div>
              <div>
                <h5 className="text-xs font-bold text-primary uppercase">Version 4.2.0-stable</h5>
                <p className="text-[10px] text-on-surface-variant">Running on Edge Node: US-EAST-1</p>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

export default Dashboard;
