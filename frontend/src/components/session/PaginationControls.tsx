import React from 'react';

interface PaginationControlsProps {
  page: number;
  pageSize: number;
  total: number;
  totalPages: number;
  onPageChange: (page: number) => void;
}

const PaginationControls: React.FC<PaginationControlsProps> = ({ page, pageSize, total, totalPages, onPageChange }) => {
  if (totalPages <= 1) return null;
  const firstItem = (page - 1) * pageSize + 1;
  const lastItem = Math.min(page * pageSize, total);
  const pageWindowStart = Math.max(1, Math.min(page - 2, totalPages - 4));
  const pageWindowEnd = Math.min(totalPages, pageWindowStart + 4);

  return (
    <nav className="pagination-controls" aria-label="Story pages">
      <span className="pagination-summary">Showing <strong>{firstItem}–{lastItem}</strong> of <strong>{total}</strong> stories</span>
      <div className="pagination-buttons">
        <button type="button" className="pagination-button" disabled={page <= 1} onClick={() => onPageChange(page - 1)} aria-label="Previous page">← <span>Previous</span></button>
        {Array.from({ length: pageWindowEnd - pageWindowStart + 1 }, (_, index) => pageWindowStart + index).map((pageNumber) => (
          <button key={pageNumber} type="button" className={`pagination-number ${page === pageNumber ? 'is-current' : ''}`} aria-current={page === pageNumber ? 'page' : undefined} aria-label={`Page ${pageNumber}`} onClick={() => onPageChange(pageNumber)}>{pageNumber}</button>
        ))}
        <button type="button" className="pagination-button" disabled={page >= totalPages} onClick={() => onPageChange(page + 1)} aria-label="Next page"><span>Next</span> →</button>
      </div>
    </nav>
  );
};

export default PaginationControls;
