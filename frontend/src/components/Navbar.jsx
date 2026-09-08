import React from 'react';
import { FileText, Database } from 'lucide-react';

export default function Navbar({ onNavigateHome }) {
  return (
    <header className="navbar">
      <a href="#" className="brand" onClick={(e) => { e.preventDefault(); onNavigateHome(); }}>
        <div className="brand-icon">
          <FileText size={18} color="#ffffff" />
        </div>
        <span className="brand-copy">
          <span>Freight Bill OCR</span>
          <span className="brand-kicker">Handwritten bill review</span>
        </span>
      </a>

      <nav className="nav-links">
        <a
          href="#"
          className="nav-link active"
          onClick={(e) => { e.preventDefault(); onNavigateHome(); }}
        >
          <Database size={16} />
          <span>Documents</span>
        </a>
      </nav>
    </header>
  );
}
