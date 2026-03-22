import React, { useState } from 'react';
import { BrowserRouter as Router, Routes, Route, Link, useLocation } from 'react-router-dom';
import Dashboard from './components/Dashboard';
import GenerationProgress from './components/GenerationProgress';
import BlogOutput from './components/BlogOutput';

function AppContent() {
  const [activeJob, setActiveJob] = useState(null);
  const location = useLocation();
  const view = location.pathname.substring(1) || 'dashboard';

  return (
    <div className="min-h-screen bg-background text-on-surface font-body selection:bg-primary/30 antialiased">
      {/* Top Bar (Shared) */}
      <header className="fixed top-0 w-full z-50 bg-[#131313]/80 backdrop-blur-xl border-b border-white/5 shadow-2xl flex justify-between items-center px-6 py-3">
        <div className="flex items-center gap-4">
          <Link to="/" className="text-lg font-bold text-primary tracking-tighter">Blogify-AI</Link>
          {view === 'dashboard' && (
            <div className="flex items-center gap-2 px-3 py-1 bg-primary/10 rounded-full">
              <div className="w-2 h-2 rounded-full bg-primary emerald-pulse"></div>
              <span className="text-[10px] uppercase tracking-widest font-bold text-primary">Operational</span>
            </div>
          )}
        </div>
        <div className="flex gap-4">
          <Link 
            to="/"
            className={`text-sm px-3 py-1 rounded transition-colors ${view === 'dashboard' ? 'text-primary bg-primary/10' : 'text-on-surface/60 hover:bg-white/5'}`}
          >
            Monitor
          </Link>
          <Link 
             to="/progress"
             className={`text-sm px-3 py-1 rounded transition-colors ${view === 'progress' ? 'text-primary bg-primary/10' : 'text-on-surface/60 hover:bg-white/5'}`}
          >
            active_jobs
          </Link>
        </div>
        <div className="flex items-center gap-4">
           <span className="material-symbols-outlined text-primary cursor-pointer">sensors</span>
           <div className="w-8 h-8 rounded-full bg-surface-container-highest overflow-hidden border border-white/10">
              <img src="https://lh3.googleusercontent.com/aida-public/AB6AXuBBsOeK1PO9cGSPcm6E7AY-uV7Fc9AuXdBP4rNaXDshunlfYiLtpurBLPC7vkMq0S1MJF7sLRw-CBEu0zdSs5O0xTkDgWWLhu57XW-v39rf6-9EH9Azw7nLJdbMg3PnVXNSjuNmzwBwBEb3V4vCiK3DtvND6N6aYI608fWgrZHbL8yRGdVQEQEzQ6L44ju1eNaJfhWD6ZQy8b-qJCB5cQZxLjAZyOOjQc_tZzFnJrhM9A0BLxOWU-w7i6x8hYxWz9OkAv7Vs_zp6cfX" alt="User" />
           </div>
        </div>
      </header>

      {/* Main Content Area */}
      <Routes>
        <Route path="/" element={<Dashboard />} />
        <Route path="/progress" element={<GenerationProgress jobData={activeJob} />} />
        <Route path="/output" element={<BlogOutput blogData={activeJob} />} />
      </Routes>

      {/* Global Sidebar (Dashboard style) - only on dash */}
      {view === 'dashboard' && (
        <aside className="fixed left-0 h-full w-64 z-40 bg-[#1C1B1B] border-r border-white/5 shadow-2xl hidden lg:flex flex-col pt-20 pb-6 px-4">
            <div className="mb-8 px-2">
                <h2 className="text-primary font-black tracking-widest text-xs uppercase">The Observer</h2>
                <p className="text-[#E5E2E1]/50 text-[10px] uppercase tracking-tighter">AI Ops Flight Deck</p>
            </div>
            <nav className="flex-1 space-y-1">
                <Link to="/" className="w-full flex items-center gap-3 px-3 py-3 bg-primary/10 text-primary border-r-2 border-primary transition-all">
                    <span className="material-symbols-outlined text-[20px]">dashboard</span>
                    <span className="text-sm tracking-wide uppercase font-medium">Dashboard</span>
                </Link>
            </nav>
        </aside>
      )}

      {/* Footer (Shared) */}
      <footer className="fixed bottom-0 w-full z-30 bg-[#131313] flex justify-between items-center px-8 py-2 border-t border-white/5">
        <span className="text-[10px] uppercase tracking-widest text-on-surface-variant/40">Blogify-AI v4.2.0-stable | System Uptime: 99.99%</span>
        <div className="flex gap-4">
           <Link to="/output" className="text-[10px] uppercase text-on-surface-variant/40 hover:text-primary transition-colors">Latest Output</Link>
        </div>
      </footer>
    </div>
  );
}

function App() {
  return (
    <Router>
      <AppContent />
    </Router>
  );
}

export default App;
