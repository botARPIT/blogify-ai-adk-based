import React from 'react';
import { Link, Navigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import LoadingState from '../components/state/LoadingState';
import TextGenerateEffect from '../components/landing/TextGenerateEffect';

const LandingPage: React.FC = () => {
  const { authenticated, loading } = useAuth();
  if (loading) return <LoadingState title="Getting your desk ready" message="Checking your workspace." />;
  if (authenticated) return <Navigate to="/dashboard" replace />;

  return <div className="landing-page">
    <section className="hero-section">
      <div className="hero-copy">
        <div className="eyebrow"><span className="eyebrow-dot" /> THE THOUGHTFUL WAY TO PUBLISH</div>
        <h1><TextGenerateEffect words={'Good writing\nstarts with a plan.'} highlight="plan" /></h1>
        <p className="hero-lede">From the first idea to a finished article, Blogify keeps every draft moving—and keeps you in the editor’s seat.</p>
        <div className="hero-actions"><Link to="/signup" className="button button-primary button-large">Start your first story <span aria-hidden="true">↗</span></Link><a href="#workflow" className="text-action">Take a look around <span aria-hidden="true">↓</span></a></div>
        <div className="hero-note"><span className="avatar-stack"><i>✳</i><i>✎</i><i>✓</i></span><span>Research, structure, and a human point of view.</span></div>
      </div>
      <div className="hero-art" aria-label="A preview of the Blogify writing workspace">
        <div className="art-orbit orbit-one" /><div className="art-orbit orbit-two" />
        <div className="paper-card paper-back"><span className="paper-kicker">A GOOD STORY HAS SHAPE</span><div className="paper-lines"><i /><i /><i /><i /></div><span className="paper-stamp">NOTES<br />01—04</span></div>
        <div className="paper-card paper-front"><div className="paper-top"><span className="tiny-brand"><i>b.</i> blogify ai</span><span className="live-chip"><i /> IN REVIEW</span></div><span className="paper-kicker">YOUR NEXT ARTICLE</span><h2>The quiet craft<br />of <em>building trust</em></h2><div className="mini-outline"><div><b>01</b><span>Start with the reader</span><i>✓</i></div><div><b>02</b><span>Make the case</span><i>✓</i></div><div className="mini-active"><b>03</b><span>Bring it to life</span><i>↗</i></div></div><div className="paper-footer"><span>OUTLINE APPROVED</span><span>YOU’RE UP NEXT</span></div></div>
        <div className="floating-note"><span className="note-icon">✦</span><div><strong>Your call, always.</strong><small>Review before the next step.</small></div></div>
        <span className="art-caption">A little structure makes room for better ideas.</span>
      </div>
      <div className="hero-index"><span>01</span><i /> EDITORIAL WORKFLOW</div>
    </section>

    <section className="trust-strip"><span>MADE FOR PEOPLE WHO CARE ABOUT THE WORK</span><div><span>THOUGHTFUL BY DESIGN</span><i /> <span>HUMAN-LED</span><i /> <span>BUILT TO FINISH</span></div></section>

    <section className="workflow-section" id="workflow">
      <div className="section-heading"><div><span className="eyebrow">A CLEAR PATH FROM IDEA TO ARTICLE</span><h2>Progress you can<br /><em>actually follow.</em></h2></div><p>Long-form work deserves more than a loading spinner. See what’s happening, know when you’re needed, and pick up right where you left off.</p></div>
      <div className="workflow-cards">
        <article className="workflow-card"><span className="step-number">01</span><span className="step-mark mark-orange">↗</span><h3>Set the direction</h3><p>Share a topic, audience, and tone. Your brief gives every stage a useful north star.</p><small>YOUR BRIEF</small></article>
        <article className="workflow-card"><span className="step-number">02</span><span className="step-mark mark-lilac">⌘</span><h3>Shape the story</h3><p>Review and edit the outline before research and writing begin. The next step waits for you.</p><small>YOUR FIRST CHECKPOINT</small></article>
        <article className="workflow-card"><span className="step-number">03</span><span className="step-mark mark-green">✳</span><h3>Let it take shape</h3><p>Research, writing, and an editorial pass happen in sequence—with visible progress throughout.</p><small>IN THE WORKS</small></article>
        <article className="workflow-card"><span className="step-number">04</span><span className="step-mark mark-blue">✓</span><h3>Make it yours</h3><p>Approve the final draft, ask for a focused revision, or keep the article for another pass.</p><small>YOUR FINAL CHECKPOINT</small></article>
      </div>
    </section>

    <section className="principle-section" id="principles"><div className="principle-art"><div className="quote-card"><span>✳</span><p>Technology should give good ideas more room to breathe.</p><small>THE BLOGIFY PRINCIPLE</small></div><div className="circle-sketch" /></div><div className="principle-copy"><span className="eyebrow">A BETTER KIND OF ASSISTANT</span><h2>Helpful at every step.<br /><em>Never in the way.</em></h2><p>Blogify handles the legwork so you can spend your attention where it matters. Every session is saved, every stage is visible, and every important decision stays with you.</p><ul><li><span>✓</span> Your work stays yours, from brief to final draft</li><li><span>✓</span> Clear checkpoints instead of black-box generation</li><li><span>✓</span> A place to return when inspiration does</li></ul><Link to="/signup" className="text-action">Make something good <span aria-hidden="true">↗</span></Link></div></section>

    <section className="landing-cta"><span className="cta-glow" aria-hidden="true" /><div className="cta-content"><span className="eyebrow">YOUR IDEA DESERVES A GOOD FIRST DRAFT</span><h2>Let’s make something<br /><em>worth reading.</em></h2><p>Bring the idea. Blogify will help you shape the story—one clear step at a time.</p><Link to="/signup" className="button button-light button-large">Start writing with Blogify <span aria-hidden="true">↗</span></Link></div><div className="cta-orbit" aria-hidden="true"><span>✳</span><i /><b /></div></section>

    <footer className="landing-footer"><Link to="/" className="brand-lockup"><span className="brand-mark">b.</span><span>blogify<span className="brand-ai">ai</span></span></Link><span>Make the work worth reading.</span><Link to="/login">Already have an account? <b>Sign in ↗</b></Link></footer>
  </div>;
};

export default LandingPage;
