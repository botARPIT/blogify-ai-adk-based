import React from 'react';
import { BrowserRouter as Router, Routes, Route, Link, NavLink, useLocation } from 'react-router-dom';
import { Toaster, toast } from 'sonner';
import DashboardPage from './pages/DashboardPage';
import InsightsPage from './pages/InsightsPage';
import MyBlogsPage from './pages/MyBlogsPage';
import SessionProgressPage from './pages/SessionProgressPage';
import OutlineReviewPage from './pages/OutlineReviewPage';
import FinalReviewPage from './pages/FinalReviewPage';
import OutputPage from './pages/OutputPage';
import SessionDetailPage from './pages/SessionDetailPage';
import BudgetPage from './pages/BudgetPage';
import LoginPage from './pages/LoginPage';
import SignupPage from './pages/SignupPage';
import LandingPage from './pages/LandingPage';
import ProfilePage from './pages/ProfilePage';
import { AuthProvider, useAuth } from './context/AuthContext';
import ProtectedRoute from './components/auth/ProtectedRoute';
import NotificationBell from './components/notifications/NotificationBell';
import GradientMenu from './components/navigation/GradientMenu';
import { useNotifications } from './hooks/useNotifications';

function AppContent() {
  const { pathname } = useLocation();
  const { authenticated, user, logout } = useAuth();
  const notifications = useNotifications(authenticated);
  const isMarketing = pathname === '/';
  const isAuthPage = pathname === '/login' || pathname === '/signup';

  const handleLogout = async () => {
    try {
      await logout();
      toast.success('You’re signed out');
    } catch (err) {
      toast.error('Could not sign out', { description: err instanceof Error ? err.message : 'Please try again.' });
    }
  };

  return (
    <div className={`app-frame ${isMarketing ? 'marketing-frame' : isAuthPage ? 'auth-frame' : 'workspace-frame'}`}>
      {isMarketing ? (
        <header className="marketing-nav">
          <Link to="/" className="brand-lockup" aria-label="Blogify home"><span className="brand-mark">b.</span><span>blogify<span className="brand-ai">ai</span></span></Link>
          <nav aria-label="Main navigation">
            <a href="/#workflow">How it works</a>
            <a href="/#principles">Our approach</a>
          </nav>
          <div className="marketing-nav-actions">
            {authenticated ? <Link className="button button-quiet" to="/dashboard">Open workspace</Link> : <Link className="button button-quiet" to="/login">Sign in</Link>}
            {!authenticated && <Link className="button button-primary" to="/signup">Get started <span aria-hidden="true">↗</span></Link>}
          </div>
        </header>
      ) : !isAuthPage ? (
        <>
          <aside className="app-sidebar">
            <Link to="/dashboard" className="brand-lockup" aria-label="Blogify workspace"><span className="brand-mark">b.</span><span>blogify<span className="brand-ai">ai</span></span></Link>
            <div className="sidebar-caption">WORKSPACE</div>
            <GradientMenu label="Workspace navigation" items={[
              { to: '/dashboard', label: 'Overview', icon: '⌂' },
              { to: '/blogs', label: 'My blogs', icon: '▤' },
              { to: '/insights', label: 'Insights', icon: '⌁' },
              { to: '/budget', label: 'Usage & budget', icon: '◷' },
            ]}/>
            <div className="sidebar-bottom">
              <NavLink to="/profile" className={({ isActive }) => `account-card ${isActive ? 'active' : ''}`}>
                <span className="avatar">{(user?.display_name || user?.email || 'B').slice(0, 1).toUpperCase()}</span>
                <span className="account-copy"><strong>{user?.display_name || 'Your account'}</strong><small>{user?.email}</small></span><span className="account-dots" aria-hidden="true">···</span>
              </NavLink>
              <button className="sidebar-signout" type="button" onClick={() => void handleLogout()}>Sign out <span aria-hidden="true">↗</span></button>
            </div>
          </aside>
          <header className="mobile-topbar">
            <Link to="/dashboard" className="brand-lockup"><span className="brand-mark">b.</span><span>blogify<span className="brand-ai">ai</span></span></Link>
            <div className="mobile-actions"><GradientMenu orientation="horizontal" label="Workspace navigation" items={[
              { to: '/dashboard', label: 'Desk', icon: '⌂' },
              { to: '/blogs', label: 'Blogs', icon: '▤' },
              { to: '/insights', label: 'Insights', icon: '⌁' },
              { to: '/budget', label: 'Usage', icon: '◷' },
            ]}/><NotificationBell items={notifications.items} unreadCount={notifications.unreadCount} onMarkRead={notifications.markRead} onMarkAllRead={notifications.markAllRead} /><Link to="/profile" className="avatar" aria-label="Profile">{(user?.display_name || user?.email || 'B').slice(0, 1).toUpperCase()}</Link></div>
          </header>
          <header className="workspace-topbar">
            <div className="breadcrumb"><span>Workspace</span><span aria-hidden="true">/</span><strong>{pathname === '/dashboard' ? 'Overview' : pathname === '/blogs' ? 'My blogs' : pathname === '/insights' ? 'Insights' : pathname.startsWith('/sessions/') ? 'Editorial session' : pathname === '/budget' ? 'Usage & budget' : 'Account'}</strong></div>
            <div className="topbar-actions"><span className="secure-indicator"><i /> Private workspace</span><NotificationBell items={notifications.items} unreadCount={notifications.unreadCount} onMarkRead={notifications.markRead} onMarkAllRead={notifications.markAllRead} /></div>
          </header>
        </>
      ) : null}
      <main className={isMarketing ? 'marketing-main' : isAuthPage ? 'auth-main' : 'workspace-main'}>
        <Routes>
          <Route path="/" element={<LandingPage />} />
          <Route path="/login" element={<LoginPage />} />
          <Route path="/signup" element={<SignupPage />} />
          <Route path="/dashboard" element={<ProtectedRoute><DashboardPage /></ProtectedRoute>} />
          <Route path="/blogs" element={<ProtectedRoute><MyBlogsPage /></ProtectedRoute>} />
          <Route path="/insights" element={<ProtectedRoute><InsightsPage /></ProtectedRoute>} />
          <Route path="/profile" element={<ProtectedRoute><ProfilePage /></ProtectedRoute>} />
          <Route path="/sessions/:sessionId/progress" element={<ProtectedRoute><SessionProgressPage /></ProtectedRoute>} />
          <Route path="/sessions/:sessionId/outline-review" element={<ProtectedRoute><OutlineReviewPage /></ProtectedRoute>} />
          <Route path="/sessions/:sessionId/final-review" element={<ProtectedRoute><FinalReviewPage /></ProtectedRoute>} />
          <Route path="/sessions/:sessionId/output" element={<ProtectedRoute><OutputPage /></ProtectedRoute>} />
          <Route path="/sessions/:sessionId" element={<ProtectedRoute><SessionDetailPage /></ProtectedRoute>} />
          <Route path="/budget" element={<ProtectedRoute><BudgetPage /></ProtectedRoute>} />
        </Routes>
      </main>
      <Toaster position="top-right" richColors closeButton theme="light" />
    </div>
  );
}

function App() {
  return <Router><AuthProvider><AppContent /></AuthProvider></Router>;
}

export default App;
