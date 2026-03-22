import React from 'react';

const BlogOutput = ({ blogData }) => {
  const { title = "The Future of AI in Surgery: Beyond the Scalpel", content = "", wordCount = 1240, readTime = 8, seoScore = 92 } = blogData || {};

  return (
    <div data-theme="azure" className="flex min-h-screen bg-surface">
      {/* SideNavBar */}
      <aside className="h-screen w-64 fixed left-0 top-0 pt-20 flex flex-col gap-4 p-4 bg-[#111C2D] z-40">
        <div className="px-4 py-2 mb-4">
          <h2 className="text-lg font-black text-on-surface">Post Engine</h2>
          <p className="text-[10px] text-on-surface-variant uppercase tracking-widest">Drafting Mode</p>
        </div>
        <nav className="flex-1 space-y-1">
          <button className="w-full flex items-center gap-3 px-4 py-3 text-primary bg-surface-container-high rounded-lg active:translate-x-1 transition-all">
            <span className="material-symbols-outlined">edit</span>
            <span>Edit</span>
          </button>
          <button className="w-full flex items-center gap-3 px-4 py-3 text-on-surface-variant hover:bg-surface-container hover:text-on-surface transition-all">
            <span className="material-symbols-outlined">download</span>
            <span>Export</span>
          </button>
        </nav>
        <button className="mt-4 w-full bg-gradient-to-br from-primary to-primary-container text-on-primary font-bold py-3 rounded-lg active:scale-95 transition-transform">
          Generate New
        </button>
      </aside>

      {/* Main Content */}
      <main className="ml-64 pt-24 pb-16 px-12 grid grid-cols-12 gap-8 w-full">
        <article className="col-span-8 space-y-10">
          <header className="space-y-6">
            <div className="flex items-center gap-2 text-primary font-medium tracking-wide text-sm">
              <span className="px-2 py-0.5 bg-surface-container-high rounded uppercase text-[10px]">AI Insight</span>
              <span>• {readTime} min read</span>
            </div>
            <h1 className="text-[2.75rem] font-bold leading-[1.1] tracking-tight text-on-surface">{title}</h1>
            <div className="flex items-center gap-4 py-4 border-b border-outline-variant/15">
              <div className="w-10 h-10 rounded-full bg-surface-container-highest flex items-center justify-center text-primary">
                <span className="material-symbols-outlined">smart_toy</span>
              </div>
              <div>
                <div className="text-on-surface font-semibold">Blogify-AI Assistant</div>
                <div className="text-on-surface-variant text-xs">Medical Tech Specialist • Published Oct 24, 2024</div>
              </div>
            </div>
          </header>

          <div className="space-y-6 text-on-surface text-lg leading-relaxed">
            <p>The integration of Artificial Intelligence (AI) into the operating theater marks one of the most significant shifts in medical history...</p>
            {/* Full content would go here */}
          </div>
        </article>

        {/* Sidebar */}
        <aside className="col-span-4 space-y-6">
          <div className="bg-surface-container-low p-6 rounded-xl space-y-6 shadow-xl">
            <h3 className="text-sm font-bold uppercase tracking-widest text-primary">Content Metrics</h3>
            <div className="grid grid-cols-2 gap-4">
              <div className="p-4 bg-surface-container-lowest rounded-lg text-center">
                <span className="text-2xl font-bold text-on-surface">{wordCount}</span>
                <p className="text-[10px] text-on-surface-variant uppercase">Words</p>
              </div>
              <div className="p-4 bg-surface-container-lowest rounded-lg text-center">
                <span className="text-2xl font-bold text-on-surface">{readTime}</span>
                <p className="text-[10px] text-on-surface-variant uppercase">Mins Read</p>
              </div>
            </div>
            <div className="space-y-2">
              <div className="flex justify-between items-end">
                <span className="text-xs font-medium text-on-surface-variant uppercase">SEO Score</span>
                <span className="text-lg font-bold text-tertiary">{seoScore}/100</span>
              </div>
              <div className="h-2 w-full bg-surface-container-highest rounded-full overflow-hidden">
                <div className="h-full bg-gradient-to-r from-primary to-primary-container" style={{ width: `${seoScore}%` }}></div>
              </div>
            </div>
          </div>
        </aside>
      </main>
    </div>
  );
};

export default BlogOutput;
