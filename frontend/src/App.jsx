import React, { useState } from 'react';
import Navbar from './components/Navbar';
import DocumentsList from './components/DocumentsList';
import DocumentDetail from './components/DocumentDetail';

export default function App() {
  const [selectedDocumentId, setSelectedDocumentId] = useState(null);

  return (
    <div className="app-container">
      <Navbar onNavigateHome={() => setSelectedDocumentId(null)} />

      <main className={`main-content${selectedDocumentId ? ' wide' : ''}`}>
        {selectedDocumentId ? (
          <DocumentDetail
            documentId={selectedDocumentId}
            onBack={() => setSelectedDocumentId(null)}
            onSelectDocument={(id) => setSelectedDocumentId(id)}
          />
        ) : (
          <DocumentsList 
            onSelectDocument={(id) => setSelectedDocumentId(id)} 
          />
        )}
      </main>
    </div>
  );
}

