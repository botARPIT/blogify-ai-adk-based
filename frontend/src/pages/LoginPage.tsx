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
    <div className="auth-screen page-enter">
      <Link to="/" className="auth-brand brand-lockup" aria-label="Blogify home"><span className="brand-mark">b.</span><span>blogify<span className="brand-ai">ai</span></span></Link>
      <div className="auth-panel">
        <span className="auth-overline">WELCOME BACK</span>
        <h1>Sign in to your account</h1>
        <p className="auth-intro">Pick up your writing right where you left it.</p>
        <form className="auth-form" onSubmit={handleSubmit}>
          <div>
            <label htmlFor="login-email">Email</label>
            <input id="login-email" className="brutalist-input" type="email" autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
          </div>
          <div>
            <label htmlFor="login-password">Password</label>
            <input
              id="login-password"
              className="brutalist-input"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
          </div>
          {error ? <p className="auth-error" role="alert">{error}</p> : null}
          <button className="button button-auth" type="submit" disabled={loading}>
            {loading ? 'Signing in…' : 'Continue with email'}
          </button>
        </form>
        <p className="auth-switch">
          New to Blogify? <Link to="/signup">Create an account <span aria-hidden="true">↗</span></Link>
        </p>
      </div>
      <span className="auth-footer-note">Your ideas, your voice. ✳</span>
    </div>
  );
};

export default LoginPage;
