import React, { useEffect, useState } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { toast } from 'sonner';
import { useAuth } from '../context/AuthContext';

const LoginPage: React.FC = () => {
  const { login, authenticated } = useAuth();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
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
        <h1 className="page-title">Sign in to Blogify</h1>
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
        <p className="text-center text-muted mt-4">
          Don't have an account? <Link to="/signup" className="text-link">Sign up</Link>
        </p>
      </div>
    </div>
  );
};

export default LoginPage;
