import React from 'react';
import type { OutlineSchema } from '../../lib/api/blogs';

interface OutlineEditorProps {
  value: OutlineSchema;
  onChange: (next: OutlineSchema) => void;
}

const OutlineEditor: React.FC<OutlineEditorProps> = ({ value, onChange }) => {
  const updateSection = (index: number, field: 'id' | 'heading' | 'goal' | 'target_words', fieldValue: string | number) => {
    const nextSections = [...value.sections];
    nextSections[index] = {
      ...nextSections[index],
      [field]: fieldValue,
    };
    onChange({
      ...value,
      sections: nextSections,
      estimated_total_words: nextSections.reduce((sum, section) => sum + Number(section.target_words || 0), 0),
    });
  };

  const moveSection = (index: number, direction: -1 | 1) => {
    const targetIndex = index + direction;
    if (targetIndex < 0 || targetIndex >= value.sections.length) return;
    const nextSections = [...value.sections];
    const [section] = nextSections.splice(index, 1);
    nextSections.splice(targetIndex, 0, section);
    onChange({
      ...value,
      sections: nextSections,
      estimated_total_words: nextSections.reduce((sum, item) => sum + item.target_words, 0),
    });
  };

  const addSection = () => {
    const nextSections = [
      ...value.sections,
      {
        id: `section_${value.sections.length + 1}`,
        heading: 'New section',
        goal: 'Describe what this section should accomplish.',
        target_words: 150,
      },
    ];
    onChange({
      ...value,
      sections: nextSections,
      estimated_total_words: nextSections.reduce((sum, section) => sum + section.target_words, 0),
    });
  };

  const removeSection = (index: number) => {
    const nextSections = value.sections.filter((_, sectionIndex) => sectionIndex !== index);
    onChange({
      ...value,
      sections: nextSections,
      estimated_total_words: nextSections.reduce((sum, section) => sum + section.target_words, 0),
    });
  };

  return (
    <div className="bento-card">
      <label className="brutalist-label">Outline Title</label>
      <input
        className="brutalist-input"
        value={value.title}
        onChange={(event) => onChange({ ...value, title: event.target.value })}
      />

      <div style={{ display: 'grid', gap: 'var(--spacing-md)' }}>
        {value.sections.map((section, index) => (
          <div key={`${section.id}-${index}`} style={{ border: '1px solid var(--border-color)', padding: 'var(--spacing-md)', background: 'var(--surface-color)' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', gap: 'var(--spacing-sm)', marginBottom: 'var(--spacing-sm)' }}>
              <span className="brutalist-label">Section {index + 1}</span>
              <div style={{ display: 'flex', gap: '0.5rem' }}>
                <button type="button" className="brutalist-button secondary" onClick={() => moveSection(index, -1)}>Up</button>
                <button type="button" className="brutalist-button secondary" onClick={() => moveSection(index, 1)}>Down</button>
                <button type="button" className="brutalist-button secondary" onClick={() => removeSection(index)}>Remove</button>
              </div>
            </div>

            <label className="brutalist-label">Section Id</label>
            <input className="brutalist-input" value={section.id} onChange={(event) => updateSection(index, 'id', event.target.value)} />

            <label className="brutalist-label">Heading</label>
            <input className="brutalist-input" value={section.heading} onChange={(event) => updateSection(index, 'heading', event.target.value)} />

            <label className="brutalist-label">Goal</label>
            <textarea
              className="brutalist-input"
              value={section.goal}
              rows={4}
              style={{ fontSize: '1rem' }}
              onChange={(event) => updateSection(index, 'goal', event.target.value)}
            />

            <label className="brutalist-label">Target Words</label>
            <input
              className="brutalist-input"
              type="number"
              min={80}
              max={300}
              value={section.target_words}
              onChange={(event) => updateSection(index, 'target_words', Number(event.target.value))}
            />
          </div>
        ))}
      </div>

      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: 'var(--spacing-md)' }}>
        <button type="button" className="brutalist-button secondary" onClick={addSection}>
          Add Section
        </button>
        <span className="brutalist-label">Estimated Total Words: {value.estimated_total_words}</span>
      </div>
    </div>
  );
};

export default OutlineEditor;
