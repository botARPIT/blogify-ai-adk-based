import React from 'react';
import SessionLibrary from '../components/session/SessionLibrary';

const MyBlogsPage: React.FC = () => <div className="workspace-content page-enter my-blogs-page">
  <header className="insights-heading">
    <div><span className="eyebrow">YOUR EDITORIAL ARCHIVE</span><h1>My <em>blogs.</em></h1><p>Find a draft, review a finished story, or follow a generation in progress.</p></div>
  </header>
  <SessionLibrary/>
</div>;

export default MyBlogsPage;
