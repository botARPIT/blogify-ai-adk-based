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
    <div className="animate-in portfolio-landing">
      <section className="portfolio-hero">
        <div className="portfolio-hero-copy">
          <span className="portfolio-kicker">AI EDITORIAL WORKFLOW / CASE 01</span>
          <h1 className="portfolio-headline">
            Ideas move.<br />
            <span>People decide.</span>
          </h1>
          <p className="portfolio-lede">
            Blogify turns a topic into a researched draft through a durable, staged workflow. A person
            approves the outline and the final article before it moves forward.
          </p>
          <div className="portfolio-actions">
            <Link to="/signup" className="brutalist-button">Try the workflow</Link>
            <a className="brutalist-button secondary" href="#architecture">Explore the system</a>
          </div>
          <div className="portfolio-stack-line">
            <span>REACT</span><i /> <span>FASTAPI</span><i /> <span>POSTGRES</span><i /> <span>REDIS</span>
          </div>
        </div>

        <div className="portfolio-flow-card" aria-label="Blog generation workflow preview">
          <div className="portfolio-flow-topline">
            <span>WORKFLOW / 04 STAGES</span>
            <span className="portfolio-live-mark"><i /> HUMAN CONTROL</span>
          </div>
          <div className="portfolio-flow-title">One request.<br />Two review gates.</div>
          <ol className="portfolio-flow-list">
            <li><span>01</span><div><strong>Brief</strong><small>Topic · audience · tone</small></div><b>API</b></li>
            <li className="is-review"><span>02</span><div><strong>Outline</strong><small>Review and edit structure</small></div><b>YOU</b></li>
            <li><span>03</span><div><strong>Research + write</strong><small>Sources, draft, editor pass</small></div><b>AI</b></li>
            <li className="is-review"><span>04</span><div><strong>Final review</strong><small>Approve or request a revision</small></div><b>YOU</b></li>
          </ol>
          <div className="portfolio-flow-foot"><span>STATE LIVES IN POSTGRES</span><span>EVENTS WAKE REDIS WORKERS ↗</span></div>
        </div>
      </section>

      <section className="portfolio-section" id="workflow">
        <div className="portfolio-section-heading">
          <span className="portfolio-kicker">01 / THE PRODUCT</span>
          <div>
            <h2>Generation with checkpoints.</h2>
            <p>Long-running work is split into steps that can pause, persist, and resume.</p>
          </div>
        </div>
        <div className="portfolio-step-grid">
          <article><span>01</span><h3>Shape the brief</h3><p>Set the topic, audience, and tone before reserving generation budget.</p></article>
          <article><span>02</span><h3>Approve the outline</h3><p>Edit the structure and give the next stage specific editorial guidance.</p></article>
          <article><span>03</span><h3>Research and draft</h3><p>Research, writing, and editorial review run as a sequential background job.</p></article>
          <article><span>04</span><h3>Make the final call</h3><p>Approve the article, reject it, or request a revision with feedback.</p></article>
        </div>
      </section>

      <section className="portfolio-section architecture-section" id="architecture">
        <div className="portfolio-section-heading">
          <span className="portfolio-kicker">02 / THE SYSTEM</span>
          <div>
            <h2>Built to survive the wait.</h2>
            <p>The database owns workflow truth; queue messages are delivery signals.</p>
          </div>
        </div>
        <div className="portfolio-architecture-grid">
          <div className="portfolio-architecture-map" aria-label="System architecture">
            <div className="architecture-node architecture-api"><small>REQUEST</small><strong>FastAPI</strong><span>Validate · reserve · commit</span></div>
            <div className="architecture-connector"><span>transaction</span><b>↓</b></div>
            <div className="architecture-node architecture-db"><small>SOURCE OF TRUTH</small><strong>PostgreSQL</strong><span>Session · version · outbox</span></div>
            <div className="architecture-branch">
              <div className="architecture-node architecture-redis"><small>WAKE-UP + DELIVERY</small><strong>Redis</strong><span>Job list · Pub/Sub signal</span></div>
              <div className="architecture-node architecture-worker"><small>EXECUTION</small><strong>Workers</strong><span>Claim · run · persist</span></div>
            </div>
            <div className="architecture-reaper"><span>REAPER</span><b>↺</b><span>Reconcile pending or expired work</span></div>
          </div>
          <div className="portfolio-principles">
            <article><span>A</span><div><h3>Commit before dispatch</h3><p>The API records workflow state and the outbox event before publishing a fast-path queue message.</p></div></article>
            <article><span>B</span><div><h3>Claim before execution</h3><p>Workers claim events and session leases in PostgreSQL so duplicate deliveries do not normally run twice.</p></div></article>
            <article><span>C</span><div><h3>Recover from drift</h3><p>The reaper republishes pending work and recovers expired processing leases.</p></div></article>
            <article><span>D</span><div><h3>Keep humans in control</h3><p>Durable snapshots carry the workflow across outline and final-review pauses.</p></div></article>
          </div>
        </div>
      </section>

      <footer className="portfolio-footer">
        <span>BUILT FOR CONTROLLED GENERATION</span>
        <p>Human approval, durable workflow state, measured model spend.</p>
        <Link to="/login">Sign in <span aria-hidden="true">↗</span></Link>
      </footer>
    </div>
  );
};

export default LandingPage;
