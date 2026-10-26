import React from 'react';
import { NavLink } from 'react-router-dom';

export interface GradientMenuItem {
  to: string;
  label: string;
  icon: string;
}

interface GradientMenuProps {
  items: GradientMenuItem[];
  orientation?: 'vertical' | 'horizontal';
  label: string;
}

const GradientMenu: React.FC<GradientMenuProps> = ({ items, orientation = 'vertical', label }) => (
  <nav className={`gradient-menu gradient-menu-${orientation}`} aria-label={label}>
    {items.map((item) => (
      <NavLink
        key={item.to}
        to={item.to}
        end={item.to === '/dashboard'}
        aria-label={item.label}
        className={({ isActive }) => `gradient-menu-item ${isActive ? 'is-active' : ''}`}
      >
        <span className="gradient-menu-icon" aria-hidden="true">{item.icon}</span>
        <span>{item.label}</span>
      </NavLink>
    ))}
  </nav>
);

export default GradientMenu;
