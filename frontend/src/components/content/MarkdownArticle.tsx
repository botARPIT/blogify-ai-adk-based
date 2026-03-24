import React from 'react';

interface MarkdownArticleProps {
  markdown: string;
  className?: string;
}

function renderInline(text: string, keyPrefix: string): React.ReactNode[] {
  const nodes: React.ReactNode[] = [];
  let cursor = 0;
  const pattern = /(\[([^\]]+)\]\(([^)]+)\)|\*\*([^*]+)\*\*|\*([^*]+)\*|`([^`]+)`)/g;
  let match: RegExpExecArray | null;

  while ((match = pattern.exec(text)) !== null) {
    if (match.index > cursor) {
      nodes.push(text.slice(cursor, match.index));
    }

    if (match[2] && match[3]) {
      nodes.push(
        <a key={`${keyPrefix}-${match.index}`} href={match[3]} target="_blank" rel="noreferrer noopener">
          {match[2]}
        </a>,
      );
    } else if (match[4]) {
      nodes.push(<strong key={`${keyPrefix}-${match.index}`}>{match[4]}</strong>);
    } else if (match[5]) {
      nodes.push(<em key={`${keyPrefix}-${match.index}`}>{match[5]}</em>);
    } else if (match[6]) {
      nodes.push(<code key={`${keyPrefix}-${match.index}`} className="markdown-inline-code">{match[6]}</code>);
    }

    cursor = pattern.lastIndex;
  }

  if (cursor < text.length) {
    nodes.push(text.slice(cursor));
  }

  return nodes;
}

function isTableSeparator(line: string): boolean {
  return /^\s*\|?[\s:-]+\|[\s|:-]*$/.test(line);
}

const MarkdownArticle: React.FC<MarkdownArticleProps> = ({ markdown, className }) => {
  const lines = markdown.split('\n');
  const elements: React.ReactNode[] = [];
  let paragraph: string[] = [];
  let unorderedItems: string[] = [];
  let orderedItems: string[] = [];
  let quoteLines: string[] = [];
  let codeLines: string[] = [];
  let tableHeader: string[] | null = null;
  let tableRows: string[][] = [];
  let inCodeBlock = false;

  const flushParagraph = (key: string) => {
    if (paragraph.length === 0) return;
    elements.push(<p key={key}>{renderInline(paragraph.join(' ').trim(), key)}</p>);
    paragraph = [];
  };

  const flushUnorderedList = (key: string) => {
    if (unorderedItems.length === 0) return;
    elements.push(
      <ul key={key}>
        {unorderedItems.map((item, index) => (
          <li key={`${key}-${index}`}>{renderInline(item, `${key}-${index}`)}</li>
        ))}
      </ul>,
    );
    unorderedItems = [];
  };

  const flushOrderedList = (key: string) => {
    if (orderedItems.length === 0) return;
    elements.push(
      <ol key={key}>
        {orderedItems.map((item, index) => (
          <li key={`${key}-${index}`}>{renderInline(item, `${key}-${index}`)}</li>
        ))}
      </ol>,
    );
    orderedItems = [];
  };

  const flushQuote = (key: string) => {
    if (quoteLines.length === 0) return;
    elements.push(<blockquote key={key}>{renderInline(quoteLines.join(' '), key)}</blockquote>);
    quoteLines = [];
  };

  const flushCode = (key: string) => {
    if (codeLines.length === 0) return;
    elements.push(
      <pre key={key} className="markdown-code-block">
        <code>{codeLines.join('\n')}</code>
      </pre>,
    );
    codeLines = [];
  };

  const flushTable = (key: string) => {
    if (!tableHeader || tableRows.length === 0) return;
    elements.push(
      <div key={key} className="markdown-table-wrap">
        <table>
          <thead>
            <tr>
              {tableHeader.map((cell, index) => (
                <th key={`${key}-head-${index}`}>{renderInline(cell, `${key}-head-${index}`)}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {tableRows.map((row, rowIndex) => (
              <tr key={`${key}-row-${rowIndex}`}>
                {row.map((cell, cellIndex) => (
                  <td key={`${key}-cell-${rowIndex}-${cellIndex}`}>
                    {renderInline(cell, `${key}-cell-${rowIndex}-${cellIndex}`)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>,
    );
    tableHeader = null;
    tableRows = [];
  };

  const flushAll = (key: string) => {
    flushParagraph(`${key}-paragraph`);
    flushUnorderedList(`${key}-ul`);
    flushOrderedList(`${key}-ol`);
    flushQuote(`${key}-quote`);
    flushCode(`${key}-code`);
    flushTable(`${key}-table`);
  };

  lines.forEach((rawLine, index) => {
    const line = rawLine.trimEnd();
    const trimmed = line.trim();
    const key = `line-${index}`;

    if (trimmed.startsWith('```')) {
      if (inCodeBlock) {
        flushCode(`${key}-code`);
      } else {
        flushParagraph(`${key}-paragraph`);
        flushUnorderedList(`${key}-ul`);
        flushOrderedList(`${key}-ol`);
        flushQuote(`${key}-quote`);
        flushTable(`${key}-table`);
      }
      inCodeBlock = !inCodeBlock;
      return;
    }

    if (inCodeBlock) {
      codeLines.push(rawLine);
      return;
    }

    if (!trimmed) {
      flushAll(key);
      return;
    }

    if (/^---+$/.test(trimmed) || /^___+$/.test(trimmed)) {
      flushAll(key);
      elements.push(<hr key={`${key}-hr`} />);
      return;
    }

    if (trimmed.startsWith('# ')) {
      flushAll(key);
      elements.push(<h1 key={`${key}-h1`}>{renderInline(trimmed.slice(2), `${key}-h1`)}</h1>);
      return;
    }

    if (trimmed.startsWith('## ')) {
      flushAll(key);
      elements.push(<h2 key={`${key}-h2`}>{renderInline(trimmed.slice(3), `${key}-h2`)}</h2>);
      return;
    }

    if (trimmed.startsWith('### ')) {
      flushAll(key);
      elements.push(<h3 key={`${key}-h3`}>{renderInline(trimmed.slice(4), `${key}-h3`)}</h3>);
      return;
    }

    if (trimmed.startsWith('> ')) {
      flushParagraph(`${key}-paragraph`);
      flushUnorderedList(`${key}-ul`);
      flushOrderedList(`${key}-ol`);
      flushTable(`${key}-table`);
      quoteLines.push(trimmed.slice(2));
      return;
    }

    if (/^[-*]\s+/.test(trimmed)) {
      flushParagraph(`${key}-paragraph`);
      flushOrderedList(`${key}-ol`);
      flushQuote(`${key}-quote`);
      flushTable(`${key}-table`);
      unorderedItems.push(trimmed.replace(/^[-*]\s+/, ''));
      return;
    }

    if (/^\d+\.\s+/.test(trimmed)) {
      flushParagraph(`${key}-paragraph`);
      flushUnorderedList(`${key}-ul`);
      flushQuote(`${key}-quote`);
      flushTable(`${key}-table`);
      orderedItems.push(trimmed.replace(/^\d+\.\s+/, ''));
      return;
    }

    if (trimmed.includes('|')) {
      const cells = trimmed
        .replace(/^\|/, '')
        .replace(/\|$/, '')
        .split('|')
        .map((cell) => cell.trim());
      const nextLine = lines[index + 1]?.trim() || '';
      if (!tableHeader && index + 1 < lines.length && isTableSeparator(nextLine)) {
        flushAll(`${key}-before-table`);
        tableHeader = cells;
        return;
      }
      if (tableHeader) {
        if (!isTableSeparator(trimmed)) {
          tableRows.push(cells);
        }
        return;
      }
    }

    paragraph.push(trimmed);
  });

  flushAll('final');

  return <div className={['markdown-body', className].filter(Boolean).join(' ')}>{elements}</div>;
};

export default MarkdownArticle;
