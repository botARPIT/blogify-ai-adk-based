import React from 'react';
import { BrowserRouter as Router, Routes, Route, Link, useLocation } from 'react-router-dom';
import { Toaster, toast } from 'sonner';
import DashboardPage from './pages/DashboardPage';
import SessionProgressPage from './pages/SessionProgressPage';
import OutlineReviewPage from './pages/OutlineReviewPage';
import FinalReviewPage from './pages/FinalReviewPage';
import OutputPage from './pages/OutputPage';
import SessionDetailPage from './pages/SessionDetailPage';
import BudgetPage from './pages/BudgetPage';
import LoginPage from './pages/LoginPage';
import { AuthProvider, useAuth } from './context/AuthContext';
import ProtectedRoute from './components/auth/ProtectedRoute';
import NotificationBell from './components/notifications/NotificationBell';
import { useNotifications } from './hooks/useNotifications';

function AppContent() {
  const location = useLocation();
  const path = location.pathname;
  const { authenticated, user, logout } = useAuth();
  const notifications = useNotifications(authenticated);

  const handleLogout = async () => {
    try {
      await logout();
      toast.success('Logged out', { description: 'Your local auth session has been cleared.' });
    } catch (err) {
      toast.error('Logout failed', {
        description: err instanceof Error ? err.message : 'Unable to end your session.',
      });
    }
  };

  return (
    <div className="app-container">
      <header className="top-bar">
        <Link to="/" className="brand-logo">
          Blogify<span className="text-accent">AI</span>
        </Link>
        <nav className="top-bar-nav">
           <Link 
            to="/" 
            className="top-nav-link"
            data-active={path === '/'}
          >
            Dashboard
          </Link>
          <Link
            to="/budget"
            className="top-nav-link"
            data-active={path === '/budget'}
          >
            Budget
          </Link>
          {authenticated ? (
            <>
              <NotificationBell
                items={notifications.items}
                unreadCount={notifications.unreadCount}
                onMarkRead={notifications.markRead}
                onMarkAllRead={notifications.markAllRead}
              />
              <div className="user-chip">
                <span>{user?.display_name || user?.email}</span>
                <button className="text-button" type="button" onClick={() => void handleLogout()}>
                  Logout
                </button>
              </div>
            </>
          ) : null}
        </nav>
      </header>

      <main className="main-content">
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/" element={<ProtectedRoute><DashboardPage /></ProtectedRoute>} />
          <Route path="/sessions/:sessionId/progress" element={<ProtectedRoute><SessionProgressPage /></ProtectedRoute>} />
          <Route path="/sessions/:sessionId/outline-review" element={<ProtectedRoute><OutlineReviewPage /></ProtectedRoute>} />
          <Route path="/sessions/:sessionId/final-review" element={<ProtectedRoute><FinalReviewPage /></ProtectedRoute>} />
          <Route path="/sessions/:sessionId/output" element={<ProtectedRoute><OutputPage /></ProtectedRoute>} />
          <Route path="/sessions/:sessionId" element={<ProtectedRoute><SessionDetailPage /></ProtectedRoute>} />
          <Route path="/budget" element={<ProtectedRoute><BudgetPage /></ProtectedRoute>} />
        </Routes>
      </main>
      <Toaster position="top-right" richColors closeButton theme="dark" />
    </div>
  );
}

function App() {
  return (
    <Router>
      <AuthProvider>
        <AppContent />
      </AuthProvider>
    </Router>
  );
}

export default App;
