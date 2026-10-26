import { useEffect, useRef, useState } from 'react';

interface ToneOption {
  value: string;
  label: string;
}

interface ToneSelectProps {
  value: string;
  onChange: (value: string) => void;
  options: ToneOption[];
}

const ToneSelect: React.FC<ToneSelectProps> = ({ value, onChange, options }) => {
  const [isOpen, setIsOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  const selected = options.find((o) => o.value === value);

  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setIsOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  return (
    <div className="tone-select" ref={containerRef}>
      <button
        type="button"
        className="tone-select-trigger"
        onClick={() => setIsOpen((prev) => !prev)}
      >
        <span>{selected?.label ?? value}</span>
        <svg
          className={`tone-select-chevron ${isOpen ? 'open' : ''}`}
          width="16"
          height="16"
          viewBox="0 0 16 16"
          fill="none"
        >
          <path d="M4 6l4 4 4-4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>

      {isOpen && (
        <div className="tone-select-panel">
          {options.map((option) => (
            <button
              key={option.value}
              type="button"
              className={`tone-select-option ${option.value === value ? 'selected' : ''}`}
              onClick={() => {
                onChange(option.value);
                setIsOpen(false);
              }}
            >
              {option.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
};

export default ToneSelect;
