import React, { useState, useEffect } from 'react';
import { ArrowLeft, RefreshCw, FileText, CheckCircle2, AlertCircle, Sparkles, Hash, Calendar, FileCode, Play } from 'lucide-react';
import StatusBadge from './StatusBadge';
import { fetchDocumentById, reprocessDocument, getDocumentFileUrl } from '../api';

export default function DocumentDetail({ documentId, onBack }) {
  const [doc, setDoc] = useState(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isReprocessing, setIsReprocessing] = useState(false);
  const [error, setError] = useState(null);
  const [successMessage, setSuccessMessage] = useState(null);

  const loadDocument = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const data = await fetchDocumentById(documentId);
      setDoc(data);
      setIsLoading(false);
    } catch (err) {
      setIsLoading(false);
      setError(err.message || 'Failed to load document details.');
    }
  };

  useEffect(() => {
    if (documentId) {
      loadDocument();
    }
  }, [documentId]);

  const handleReprocess = async () => {
    setIsReprocessing(true);
    setError(null);
    setSuccessMessage(null);
    try {
      const updated = await reprocessDocument(documentId);
      setDoc(updated);
      setIsReprocessing(false);
      setSuccessMessage('Document reprocessed successfully! Extracted data updated.');
    } catch (err) {
      setIsReprocessing(false);
      setError(err.message || 'Failed to reprocess document.');
    }
  };

  const formatDate = (dateStr) => {
    if (!dateStr) return 'N/A';
    try {
      return new Date(dateStr).toLocaleString(undefined, {
        year: 'numeric',
        month: 'short',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit'
      });
    } catch {
      return dateStr;
    }
  };

  // Helper to format JSON field names cleanly (e.g. driver_name -> Driver Name)
  const formatFieldLabel = (key) => {
    return key
      .replace(/_/g, ' ')
      .replace(/([a-z])([A-Z])/g, '$1 $2')
      .replace(/\b\w/g, (char) => char.toUpperCase());
  };

  if (isLoading) {
    return (
      <div>
        <button className="btn btn-secondary" onClick={onBack} style={{ marginBottom: '1.5rem' }}>
          <ArrowLeft size={16} />
          <span>Back to Documents</span>
        </button>
        <div className="card">
          <div className="state-box">
            <div className="spinner spinner-dark" style={{ width: '2.5rem', height: '2.5rem' }} />
            <p className="state-desc" style={{ marginTop: '0.5rem' }}>Loading document details...</p>
          </div>
        </div>
      </div>
    );
  }

  if (error && !doc) {
    return (
      <div>
        <button className="btn btn-secondary" onClick={onBack} style={{ marginBottom: '1.5rem' }}>
          <ArrowLeft size={16} />
          <span>Back to Documents</span>
        </button>
        <div className="alert alert-error">
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <AlertCircle size={16} />
            <span>{error}</span>
          </div>
          <button className="btn btn-secondary" style={{ padding: '0.25rem 0.5rem' }} onClick={loadDocument}>
            Retry
          </button>
        </div>
      </div>
    );
  }

  if (!doc) return null;

  const extractedData = doc.extracted_data;
  const hasExtractedData = extractedData && typeof extractedData === 'object' && Object.keys(extractedData).length > 0;

  return (
    <div>
      {/* Back Button & Top Action */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1.5rem' }}>
        <button className="btn btn-secondary" onClick={onBack}>
          <ArrowLeft size={16} />
          <span>Back to Documents</span>
        </button>

        <button 
          className="btn btn-primary" 
          onClick={handleReprocess} 
          disabled={isReprocessing}
        >
          {isReprocessing ? (
            <>
              <div className="spinner" />
              <span>Processing OCR...</span>
            </>
          ) : (
            <>
              <RefreshCw size={16} />
              <span>Reprocess Document</span>
            </>
          )}
        </button>
      </div>

      {/* Notifications */}
      {successMessage && (
        <div className="alert alert-success">
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <CheckCircle2 size={16} />
            <span>{successMessage}</span>
          </div>
          <button 
            onClick={() => setSuccessMessage(null)}
            style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'inherit' }}
          >
            ✕
          </button>
        </div>
      )}

      {error && (
        <div className="alert alert-error">
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <AlertCircle size={16} />
            <span>{error}</span>
          </div>
        </div>
      )}

      {/* Overview Info Header Card */}
      <div className="card" style={{ marginBottom: '1.5rem' }}>
        <div className="card-header" style={{ backgroundColor: '#f8fafc' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
            <div style={{ padding: '0.625rem', backgroundColor: '#eff6ff', borderRadius: '0.5rem', color: '#2563eb' }}>
              <FileText size={24} />
            </div>
            <div>
              <h2 className="card-title" style={{ fontSize: '1.25rem' }}>{doc.filename}</h2>
              <div className="mono" style={{ fontSize: '0.8125rem', color: '#64748b', marginTop: '0.125rem' }}>
                ID: {doc.id}
              </div>
            </div>
          </div>

          <StatusBadge status={doc.status} />
        </div>

        {/* Key Information Strip */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', padding: '1.25rem 1.5rem', gap: '1.25rem', borderBottom: '1px solid #e2e8f0' }}>
          <div>
            <div style={{ fontSize: '0.75rem', fontWeight: 600, color: '#64748b', textTransform: 'uppercase', marginBottom: '0.25rem' }}>
              File Hash (SHA-256)
            </div>
            <div className="mono" style={{ fontSize: '0.8125rem', color: '#0f172a', wordBreak: 'break-all' }}>
              {doc.file_hash || 'N/A'}
            </div>
          </div>

          <div>
            <div style={{ fontSize: '0.75rem', fontWeight: 600, color: '#64748b', textTransform: 'uppercase', marginBottom: '0.25rem' }}>
              Created Date
            </div>
            <div style={{ fontSize: '0.875rem', fontWeight: 500, color: '#0f172a' }}>
              {formatDate(doc.created_at)}
            </div>
          </div>

          <div>
            <div style={{ fontSize: '0.75rem', fontWeight: 600, color: '#64748b', textTransform: 'uppercase', marginBottom: '0.25rem' }}>
              Processed Date
            </div>
            <div style={{ fontSize: '0.875rem', fontWeight: 500, color: '#0f172a' }}>
              {formatDate(doc.processed_at)}
            </div>
          </div>

          <div>
            <div style={{ fontSize: '0.75rem', fontWeight: 600, color: '#64748b', textTransform: 'uppercase', marginBottom: '0.25rem' }}>
              OCR Confidence
            </div>
            <div style={{ fontSize: '0.875rem', fontWeight: 600, color: doc.confidence ? '#16a34a' : '#64748b' }}>
              {doc.confidence ? `${(doc.confidence * 100).toFixed(1)}%` : 'N/A'}
            </div>
          </div>
        </div>
      </div>

      {/* Document Detail Split Layout (Future Phase Review Ready) */}
      <div className="detail-layout">
        
        {/* Extracted Data Section */}
        <div className="card">
          <div className="card-header">
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
              <Sparkles size={18} color="#2563eb" />
              <h3 className="card-title">Extracted Data</h3>
            </div>

            {hasExtractedData && (
              <span className="badge badge-completed">
                {Object.keys(extractedData).length} Fields Extracted
              </span>
            )}
          </div>

          {!hasExtractedData ? (
            <div className="state-box">
              <div className="state-icon">
                <FileCode size={28} />
              </div>
              <h3 className="state-title">Document has not been processed yet.</h3>
              <p className="state-desc">
                Click the Reprocess button below to run Google Document AI extraction and extract structured freight bill fields.
              </p>
              <button 
                className="btn btn-primary" 
                onClick={handleReprocess} 
                disabled={isReprocessing}
                style={{ marginTop: '0.5rem' }}
              >
                {isReprocessing ? (
                  <>
                    <div className="spinner" />
                    <span>Extracting Fields...</span>
                  </>
                ) : (
                  <>
                    <Play size={16} />
                    <span>Run Extraction Now</span>
                  </>
                )}
              </button>
            </div>
          ) : (
            <div>
              {/* Dynamic Name -> Value Grid */}
              <div className="kv-grid">
                {Object.entries(extractedData).map(([key, val]) => (
                  <div key={key} className="kv-card">
                    <div className="kv-label">{formatFieldLabel(key)}</div>
                    <div className="kv-value">
                      {val !== null && val !== undefined ? String(val) : '—'}
                    </div>
                  </div>
                ))}
              </div>

              {/* Raw JSON Accordion / View Option */}
              <div style={{ padding: '1rem 1.5rem', borderTop: '1px solid #e2e8f0', backgroundColor: '#f8fafc' }}>
                <details>
                  <summary style={{ cursor: 'pointer', fontSize: '0.8125rem', fontWeight: 600, color: '#64748b' }}>
                    View Raw Extracted JSON
                  </summary>
                  <pre className="mono" style={{ backgroundColor: '#0f172a', color: '#f8fafc', padding: '1rem', borderRadius: '0.5rem', marginTop: '0.75rem', overflowX: 'auto', fontSize: '0.75rem' }}>
                    {JSON.stringify(extractedData, null, 2)}
                  </pre>
                </details>
              </div>
            </div>
          )}
        </div>

      </div>
    </div>
  );
}

