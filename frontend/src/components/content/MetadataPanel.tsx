import React from 'react';

interface MetadataItem {
  label: string;
  value: React.ReactNode;
}

interface MetadataPanelProps {
  title: string;
  items: MetadataItem[];
  footer?: React.ReactNode;
}

const MetadataPanel: React.FC<MetadataPanelProps> = ({ title, items, footer }) => (
  <div className="bento-card panel-card">
    <h2 className="card-title">{title}</h2>
    <div className="meta-grid">
      {items.map((item) => (
        <div
          key={item.label}
          className="meta-row"
        >
          <span className="eyebrow-label" style={{ margin: 0 }}>{item.label}</span>
          <span className="meta-value">{item.value}</span>
        </div>
      ))}
    </div>
    {footer ? <div className="panel-footer">{footer}</div> : null}
  </div>
);

export default MetadataPanel;
