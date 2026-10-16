import React, { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { getBlogSessions, type BlogSessionPage, type BlogSessionStatusFilter } from '../../lib/api/blogs';
import SessionCard from './SessionCard';
import PaginationControls from './PaginationControls';

type SessionFilter = 'all' | 'review' | 'active' | 'completed' | 'failed';
const SESSION_FILTERS: { id: SessionFilter; label: string }[] = [
  { id: 'all', label: 'All stories' },
  { id: 'review', label: 'Needs review' },
  { id: 'active', label: 'In progress' },
  { id: 'completed', label: 'Completed' },
  { id: 'failed', label: 'Failed' },
];
const FILTER_STATUSES: Partial<Record<SessionFilter, BlogSessionStatusFilter[]>> = {
  review: ['AWAITING_OUTLINE_REVIEW', 'AWAITING_FINAL_REVIEW'],
  active: ['QUEUED', 'PROCESSING'],
  completed: ['COMPLETED'],
  failed: ['FAILED'],
};
const PAGE_SIZE = 9;

interface SessionLibraryProps { heading?: string; eyebrow?: string; latestOnly?: boolean; }

const SessionLibrary: React.FC<SessionLibraryProps> = ({ heading = 'Story library', eyebrow = 'YOUR STORIES, IN PROGRESS', latestOnly = false }) => {
  const [result, setResult] = useState<BlogSessionPage | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [filter, setFilter] = useState<SessionFilter>('all');
  const [page, setPage] = useState(1);
  const [searchInput, setSearchInput] = useState('');
  const [search, setSearch] = useState('');
  const [reloadKey, setReloadKey] = useState(0);
  const sessions = result?.items || [];
  const total = result?.total || 0;

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError('');
    getBlogSessions({ page: latestOnly ? 1 : page, pageSize: latestOnly ? 1 : PAGE_SIZE, statuses: FILTER_STATUSES[filter], search })
      .then((data) => { if (active) setResult(data); })
      .catch((err: unknown) => { if (active) setError(err instanceof Error ? err.message : 'Your stories could not be loaded.'); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [filter, latestOnly, page, reloadKey, search]);

  const changeFilter = (value: SessionFilter) => { setPage(1); setFilter(value); };
  const submitSearch = (event: React.FormEvent) => { event.preventDefault(); setPage(1); setSearch(searchInput.trim()); };
  const clearFilters = () => { setSearchInput(''); setSearch(''); changeFilter('all'); };
  const emptyLabel = filter === 'failed' ? 'failed' : SESSION_FILTERS.find((item) => item.id === filter)?.label.toLowerCase();

  return <section className={`sessions-section story-library-section ${latestOnly ? 'latest-story-section' : ''}`}>
      <div className="section-bar">
      <div><span className="eyebrow">{eyebrow}</span><h2>{heading} {!latestOnly && <span>{total}</span>}</h2></div>
      <div className="section-actions"><button className="icon-button" type="button" onClick={() => setReloadKey((value) => value + 1)} disabled={loading} aria-label="Refresh stories" title="Refresh stories">↻</button></div>
    </div>
    {!latestOnly && <div className="library-toolbar">
      <div className="story-filters" role="group" aria-label="Filter stories by status">
        {SESSION_FILTERS.map((item) => <button key={item.id} type="button" className={`story-filter ${filter === item.id ? 'is-active' : ''}`} aria-pressed={filter === item.id} onClick={() => changeFilter(item.id)}>{item.label}</button>)}
      </div>
      <form className="library-search" onSubmit={submitSearch} role="search">
        <label className="sr-only" htmlFor="story-search">Search topics or audiences</label>
        <span aria-hidden="true">⌕</span><input id="story-search" value={searchInput} onChange={(event) => setSearchInput(event.target.value)} placeholder="Search your stories" maxLength={100}/>
        {searchInput && <button type="button" aria-label="Clear search" onClick={() => { setSearchInput(''); setSearch(''); setPage(1); }}>×</button>}
        <button className="library-search-submit" type="submit">Search</button>
      </form>
    </div>}
    {loading ? <div className="story-grid-skeleton" aria-label="Loading stories"><i/><i/><i/></div> : error ? <div className="empty-sessions"><span className="empty-icon">↻</span><h3>We lost the thread.</h3><p>{error}</p><button type="button" className="button button-quiet" onClick={() => setReloadKey((value) => value + 1)}>Try again</button></div> : total === 0 && !search && filter === 'all' ? <div className="empty-sessions"><span className="empty-icon">✳</span><h3>Your next story starts here.</h3><p>When you start a session, you’ll find its progress and reviews waiting here.</p><Link className="text-action" to="/dashboard#story-topic">Start with a topic <span aria-hidden="true">↑</span></Link></div> : sessions.length === 0 ? <div className="empty-sessions filter-empty"><span className="empty-icon">⌕</span><h3>No stories found.</h3><p>{search ? `Nothing matched “${search}”.` : `There are no ${emptyLabel} stories yet.`}</p><button className="text-action" type="button" onClick={clearFilters}>Clear filters <span aria-hidden="true">↗</span></button></div> : <>
      <div className="story-grid" role="list" aria-label="Blog generation sessions">{sessions.map((session) => <SessionCard session={session} key={session.session_id}/>)}</div>
      {!latestOnly && <PaginationControls page={page} pageSize={PAGE_SIZE} total={total} totalPages={result?.total_pages || 0} onPageChange={setPage}/>}
    </>}
  </section>;
};

export default SessionLibrary;
