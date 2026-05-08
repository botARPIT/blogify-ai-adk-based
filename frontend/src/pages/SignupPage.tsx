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
    <div className="animate-in state-shell">
      <div className="state-card auth-card">
        <h1 className="page-title">Create your Blogify account.</h1>
        <p className="page-subtitle">
          Sign up to start creating AI-powered blog posts.
        </p>
        <form className="auth-form" onSubmit={handleSubmit}>
          <div>
            <label className="eyebrow-label">Email</label>
            <input 
              className="brutalist-input" 
              type="email" 
              value={email} 
              onChange={(e) => setEmail(e.target.value)}
              placeholder="you@example.com"
              required
            />
          </div>
          <div>
            <label className="eyebrow-label">Display Name (optional)</label>
            <input 
              className="brutalist-input" 
              type="text" 
              value={displayName} 
              onChange={(e) => setDisplayName(e.target.value)}
              placeholder="Your name"
            />
          </div>
          <div>
            <label className="eyebrow-label">Password</label>
            <input
              className="brutalist-input"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="8-100 characters"
              minLength={8}
              maxLength={100}
              required
            />
            <span className="text-xs text-muted">Must be 8-100 characters</span>
          </div>
          {error ? <p className="text-error">{error}</p> : null}
          <button className="brutalist-button" type="submit" disabled={loading}>
            {loading ? 'Creating Account...' : 'Sign Up'}
          </button>
        </form>
        <p className="text-center text-muted mt-4">
          Already have an account? <Link to="/login" className="text-link">Sign in</Link>
        </p>
      </div>
    </div>
  );
};

export default SignupPage;