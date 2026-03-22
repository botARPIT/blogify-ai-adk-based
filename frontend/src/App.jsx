import React, { useState, useEffect } from 'react';
import Dashboard from './components/Dashboard';
import GenerationProgress from './components/GenerationProgress';
import BlogOutput from './components/BlogOutput';

function App() {
  const [view, setView] = useState('dashboard'); // 'dashboard', 'progress', 'output'
  const [activeJob, setActiveJob] = useState(null);

  // Simple sidebar navigation for the demo
  const switchView = (newView) => setView(newView);

  return (
    <div className="min-h-screen bg-background text-on-surface font-body selection:bg-primary/30 antialiased">
      {/* Top Bar (Shared) */}
      <header className="fixed top-0 w-full z-50 bg-[#131313]/80 backdrop-blur-xl border-b border-white/5 shadow-2xl flex justify-between items-center px-6 py-3">
        <div className="flex items-center gap-4">
          <span className="text-lg font-bold text-primary tracking-tighter">Blogify-AI</span>
          {view === 'dashboard' && (
            <div className="flex items-center gap-2 px-3 py-1 bg-primary/10 rounded-full">
              <div className="w-2 h-2 rounded-full bg-primary emerald-pulse"></div>
              <span className="text-[10px] uppercase tracking-widest font-bold text-primary">Operational</span>
            </div>
          )}
        </div>
        <div className="flex gap-4">
          <button 
            onClick={() => switchView('dashboard')}
            className={`text-sm px-3 py-1 rounded transition-colors ${view === 'dashboard' ? 'text-primary bg-primary/10' : 'text-on-surface/60 hover:bg-white/5'}`}
          >
            Monitor
          </button>
          <button 
             onClick={() => switchView('progress')}
             className={`text-sm px-3 py-1 rounded transition-colors ${view === 'progress' ? 'text-primary bg-primary/10' : 'text-on-surface/60 hover:bg-white/5'}`}
          >
            active_jobs
          </button>
        </div>
        <div className="flex items-center gap-4">
           <span className="material-symbols-outlined text-primary cursor-pointer">sensors</span>
           <div className="w-8 h-8 rounded-full bg-surface-container-highest overflow-hidden border border-white/10">
              <img src="https://lh3.googleusercontent.com/aida-public/AB6AXuBBsOeK1PO9cGSPcm6E7AY-uV7Fc9AuXdBP4rNaXDshunlfYiLtpurBLPC7vkMq0S1MJF7sLRw-CBEu0zdSs5O0xTkDgWWLhu57XW-v39rf6-9EH9Azw7nLJdbMg3PnVXNSjuNmzwBwBEb3V4vCiK3DtvND6N6aYI608fWgrZHbL8yRGdVQEQEzQ6L44ju1eNaJfhWD6ZQy8b-qJCB5cQZxLjAZyOOjQc_tZzFnJrhM9A0BLxOWU-w7i6x8hYxWz9OkAv7Vs_zp6cfX" alt="User" />
           </div>
        </div>
      </header>

      {/* Main Content Area */}
      {view === 'dashboard' && <Dashboard />}
      {view === 'progress' && <GenerationProgress jobData={activeJob} />}
      {view === 'output' && <BlogOutput blogData={activeJob} />}

      {/* Global Sidebar (Dashboard style) */}
      {view === 'dashboard' && (
        <aside className="fixed left-0 h-full w-64 z-40 bg-[#1C1B1B] border-r border-white/5 shadow-2xl hidden lg:flex flex-col pt-20 pb-6 px-4">
            <div className="mb-8 px-2">
                <h2 className="text-primary font-black tracking-widest text-xs uppercase">The Observer</h2>
                <p className="text-[#E5E2E1]/50 text-[10px] uppercase tracking-tighter">AI Ops Flight Deck</p>
            </div>
            <nav className="flex-1 space-y-1">
                <button className="w-full flex items-center gap-3 px-3 py-3 bg-primary/10 text-primary border-r-2 border-primary transition-all">
                    <span className="material-symbols-outlined text-[20px]">dashboard</span>
                    <span className="text-sm tracking-wide uppercase font-medium">Dashboard</span>
                </button>
                {/* Other Nav Items */}
            </nav>
        </aside>
      )}

      {/* Footer (Shared) */}
      <footer className="fixed bottom-0 w-full z-30 bg-[#131313] flex justify-between items-center px-8 py-2 lg:ml-64 border-t border-white/5">
        <span className="text-[10px] uppercase tracking-widest text-on-surface-variant/40">Blogify-AI v4.2.0-stable | System Uptime: 99.99%</span>
        <div className="flex gap-4">
           <button onClick={() => switchView('output')} className="text-[10px] uppercase text-on-surface-variant/40 hover:text-primary transition-colors">Latest Output</button>
        </div>
      </footer>
    </div>
  );
}

export default App;
