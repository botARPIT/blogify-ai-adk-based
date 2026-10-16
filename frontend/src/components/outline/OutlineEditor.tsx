import React from 'react';
import type { OutlineSchema } from '../../lib/api/blogs';

interface OutlineEditorProps { value: OutlineSchema; onChange: (next: OutlineSchema) => void; }
const OutlineEditor: React.FC<OutlineEditorProps> = ({ value, onChange }) => {
  const updateSection = (index: number, field: 'id' | 'heading' | 'goal' | 'target_words', fieldValue: string | number) => {
    const sections = value.sections.map((section, current) => current === index ? { ...section, [field]: fieldValue } : section);
    onChange({ ...value, sections, estimated_total_words: sections.reduce((sum, section) => sum + Number(section.target_words || 0), 0) });
  };
  const updateOrder = (index: number, direction: -1 | 1) => {
    const target = index + direction;
    if (target < 0 || target >= value.sections.length) return;
    const sections = [...value.sections];
    [sections[index], sections[target]] = [sections[target], sections[index]];
    onChange({ ...value, sections });
  };
  const addSection = () => {
    if (value.sections.length >= 7) return;
    const sections = [...value.sections, { id: `section_${value.sections.length + 1}`, heading: '', goal: '', target_words: 150 }];
    onChange({ ...value, sections, estimated_total_words: sections.reduce((sum, section) => sum + section.target_words, 0) });
  };
  const removeSection = (index: number) => {
    if (value.sections.length <= 3) return;
    const sections = value.sections.filter((_, current) => current !== index);
    onChange({ ...value, sections, estimated_total_words: sections.reduce((sum, section) => sum + section.target_words, 0) });
  };

  return <section className="bento-card outline-editor" aria-label="Edit article outline">
    <div className="outline-editor-heading"><div><span className="eyebrow">MAKE THE STORY YOURS</span><h2 className="section-title">Your outline</h2><p>Adjust the shape before the research and writing begin.</p></div><span className="outline-count">{value.sections.length} sections</span></div>
    <div className="field-group"><label htmlFor="outline-title">Working title</label><input id="outline-title" className="field-input outline-title-input" value={value.title} maxLength={500} onChange={(event) => onChange({ ...value, title: event.target.value })}/></div>
    <div className="outline-sections">{value.sections.map((section, index) => {
      const prefix = `outline-${section.id}-${index}`;
      return <article className="outline-section-card" key={`${section.id}-${index}`}>
        <div className="outline-section-top"><div><span className="outline-index">{String(index + 1).padStart(2, '0')}</span><span className="eyebrow">STORY SECTION</span></div><div className="outline-actions">
          <button type="button" className="icon-button outline-order" onClick={() => updateOrder(index, -1)} disabled={index === 0} aria-label={`Move section ${index + 1} up`} title="Move up">↑</button>
          <button type="button" className="icon-button outline-order" onClick={() => updateOrder(index, 1)} disabled={index === value.sections.length - 1} aria-label={`Move section ${index + 1} down`} title="Move down">↓</button>
          <button type="button" className="outline-remove" onClick={() => removeSection(index)} disabled={value.sections.length <= 3}>Remove</button>
        </div></div>
        <div className="field-group"><label htmlFor={`${prefix}-heading`}>Section heading</label><input id={`${prefix}-heading`} className="field-input" value={section.heading} maxLength={255} onChange={(event) => updateSection(index, 'heading', event.target.value)}/></div>
        <div className="field-group"><label htmlFor={`${prefix}-id`}>Section key</label><input id={`${prefix}-id`} className="field-input" value={section.id} maxLength={120} onChange={(event) => updateSection(index, 'id', event.target.value)}/></div>
        <div className="field-group"><label htmlFor={`${prefix}-goal`}>What should this section cover?</label><textarea id={`${prefix}-goal`} className="field-input outline-goal" value={section.goal} rows={3} maxLength={2000} onChange={(event) => updateSection(index, 'goal', event.target.value)}/></div>
        <div className="field-group word-target"><label htmlFor={`${prefix}-words`}>Target words</label><div className="word-input-wrap"><input id={`${prefix}-words`} className="field-input" type="number" min={80} max={300} value={section.target_words} onChange={(event) => updateSection(index, 'target_words', Number(event.target.value))}/><span>words</span></div></div>
      </article>;
    })}</div>
    <div className="outline-editor-footer"><button type="button" className="button button-quiet" onClick={addSection} disabled={value.sections.length >= 7}>+ Add a section</button><span>Estimated length <strong>{value.estimated_total_words.toLocaleString()} words</strong></span></div>
  </section>;
};

export default OutlineEditor;
