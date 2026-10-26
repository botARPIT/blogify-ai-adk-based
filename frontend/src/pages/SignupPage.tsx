import React, { useEffect, useState } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { toast } from 'sonner';
import { useAuth } from '../context/AuthContext';

const SignupPage: React.FC = () => {
  const { signup, authenticated } = useAuth();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [displayName, setDisplayName] = useState('');
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
      await signup({ email, password, display_name: displayName || undefined });
      toast.success('Account created', { description: 'Welcome to Blogify!' });
      navigate(from, { replace: true });
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Signup failed';
      setError(message);
      toast.error('Signup failed', { description: message });
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="auth-screen page-enter">
      <Link to="/" className="auth-brand brand-lockup" aria-label="Blogify home"><span className="brand-mark">b.</span><span>blogify<span className="brand-ai">ai</span></span></Link>
      <div className="auth-panel">
        <span className="auth-overline">MAKE ROOM FOR GOOD IDEAS</span>
        <h1>Create your account</h1>
        <p className="auth-intro">A thoughtful process for getting from idea to article.</p>
        <form className="auth-form" onSubmit={handleSubmit}>
          <div>
            <label htmlFor="signup-email">Email</label>
            <input 
              id="signup-email"
              className="brutalist-input" 
              type="email" 
              autoComplete="email"
              value={email} 
              onChange={(e) => setEmail(e.target.value)}
              placeholder="you@example.com"
              required
            />
          </div>
          <div>
            <label htmlFor="signup-name">Display name (optional)</label>
            <input 
              id="signup-name"
              className="brutalist-input" 
              type="text" 
              autoComplete="name"
              value={displayName} 
              onChange={(e) => setDisplayName(e.target.value)}
              placeholder="Your name"
            />
          </div>
          <div>
            <label htmlFor="signup-password">Password</label>
            <input
              id="signup-password"
              className="brutalist-input"
              type="password"
              autoComplete="new-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="8-100 characters"
              minLength={8}
              maxLength={100}
              required
            />
            <span className="text-xs text-muted">Must be 8-100 characters</span>
          </div>
          {error ? <p className="auth-error" role="alert">{error}</p> : null}
          <button className="button button-auth" type="submit" disabled={loading}>
            {loading ? 'Creating your account…' : 'Continue with email'}
          </button>
        </form>
        <p className="auth-switch">
          Already have an account? <Link to="/login">Sign in <span aria-hidden="true">↗</span></Link>
        </p>
      </div>
      <span className="auth-footer-note">Your ideas, your voice. ✳</span>
    </div>
  );
};

export default SignupPage;
