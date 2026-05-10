import React from 'react';
import { Navigate, Link } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import LoadingState from '../components/state/LoadingState';

const LandingPage: React.FC = () => {
  const { authenticated, loading } = useAuth();

  if (loading) {
    return <LoadingState title="Loading Blogify AI..." message="Waking up the systems." />;
  }

  if (authenticated) {
    return <Navigate to="/dashboard" replace />;
  }

  return (
    <div className="animate-in state-shell">
      <div className="state-card" style={{ maxWidth: '800px', margin: '0 auto', textAlign: 'center' }}>
        <h1 className="display-title mb-md" style={{ color: 'var(--accent-color)' }}>
          BLOGIFY<span className="text-primary" style={{ color: 'white' }}> AI</span>
        </h1>
        <h2 className="page-title mb-md" style={{ margin: '0 auto', maxWidth: '15ch' }}>
          AI-driven blog generation with a human-in-the-loop review gate.
        </h2>
        <p className="page-subtitle mb-lg" style={{ fontSize: '1.25rem', margin: '0 auto 3rem auto' }}>
          Streamline your editorial process. Set the tone, target your audience, and review outlines before final generation. Maintain your budget and keep full control of the final output.
        </p>
        
        <div style={{ display: 'flex', gap: '1.5rem', justifyContent: 'center' }}>
          <Link to="/signup" className="brutalist-button" style={{ padding: '1rem 2rem', fontSize: '1.2rem' }}>
            Get Started
          </Link>
          <Link to="/login" className="brutalist-button secondary" style={{ padding: '1rem 2rem', fontSize: '1.2rem' }}>
            Log In
          </Link>
        </div>
      </div>
    </div>
  );
};

export default LandingPage;
