export interface MarkdownHeading {
  id: string;
  text: string;
  level: 1 | 2 | 3;
  line: number;
}

function headingText(source: string): string {
  return source
    .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')
    .replace(/[`*_~]/g, '')
    .trim();
}

function slugify(value: string): string {
  return value.toLowerCase().normalize('NFKD').replace(/[\u0300-\u036f]/g, '')
    .replace(/[^a-z0-9\s-]/g, '').trim().replace(/\s+/g, '-') || 'section';
}

export function getMarkdownHeadings(markdown: string): MarkdownHeading[] {
  const seen = new Map<string, number>();
  return markdown.split('\n').flatMap((line, index) => {
    const match = line.trim().match(/^(#{1,3})\s+(.+)$/);
    if (!match) return [];
    const text = headingText(match[2]);
    const base = slugify(text);
    const count = seen.get(base) || 0;
    seen.set(base, count + 1);
    return [{ id: count ? `${base}-${count + 1}` : base, text, level: match[1].length as 1 | 2 | 3, line: index }];
  });
}
