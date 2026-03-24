import React, { useEffect, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { toast } from 'sonner';
import { useAuth } from '../context/AuthContext';

const LoginPage: React.FC = () => {
  const { login, authenticated } = useAuth();
  const [email, setEmail] = useState('dev@blogify.local');
  const [password, setPassword] = useState('devpassword123');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const navigate = useNavigate();
  const location = useLocation();
  const from = (location.state as { from?: { pathname?: string } } | null)?.from?.pathname || '/';

  useEffect(() => {
    if (authenticated) {
      navigate(from, { replace: true });
    }
  }, [authenticated, from, navigate]);

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    setLoading(true);
    setError('');
    try {
      await login({ email, password });
      toast.success('Logged in', { description: 'Your local auth session is active.' });
      navigate(from, { replace: true });
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Login failed';
      setError(message);
      toast.error('Login failed', { description: message });
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="animate-in state-shell">
      <div className="state-card auth-card">
        <span className="eyebrow-label">Local Auth</span>
        <h1 className="page-title">Sign in to your Blogify workspace.</h1>
        <p className="page-subtitle">
          Use the seeded local credentials in development or the account you created for this environment.
        </p>
        <form className="auth-form" onSubmit={handleSubmit}>
          <div>
            <label className="eyebrow-label">Email</label>
            <input className="brutalist-input" value={email} onChange={(e) => setEmail(e.target.value)} />
          </div>
          <div>
            <label className="eyebrow-label">Password</label>
            <input
              className="brutalist-input"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </div>
          {error ? <p className="text-error">{error}</p> : null}
          <button className="brutalist-button" type="submit" disabled={loading}>
            {loading ? 'Signing In...' : 'Sign In'}
          </button>
        </form>
      </div>
    </div>
  );
};

export default LoginPage;
