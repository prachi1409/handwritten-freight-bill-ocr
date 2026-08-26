import React, { useState, useEffect } from 'react';
import { Upload, RefreshCw, FolderSearch, FileText, CheckCircle2, Clock, AlertTriangle, Eye } from 'lucide-react';
import StatusBadge from './StatusBadge';
import UploadModal from './UploadModal';
import { fetchDocuments, scanDocuments } from '../api';

export default function DocumentsList({ onSelectDocument }) {
  const [documents, setDocuments] = useState([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isScanning, setIsScanning] = useState(false);
  const [error, setError] = useState(null);
  const [isUploadOpen, setIsUploadOpen] = useState(false);
  const [bannerMessage, setBannerMessage] = useState(null);

  const loadDocuments = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const data = await fetchDocuments();
      setDocuments(data);
      setIsLoading(false);
    } catch (err) {
      setIsLoading(false);
      setError(err.message || 'Failed to fetch documents from server.');
    }
  };

  useEffect(() => {
    loadDocuments();
  }, []);

  const handleScanDirectory = async () => {
    setIsScanning(true);
    setError(null);
    try {
      const result = await scanDocuments();
      setIsScanning(false);
      setBannerMessage(`Scanned ${result.total_scanned} files. Ingested: ${result.ingested_count}, Duplicates: ${result.duplicate_count}, Invalid: ${result.invalid_count}.`);
      loadDocuments();
    } catch (err) {
      setIsScanning(false);
      setError(err.message || 'Failed to scan input directory.');
    }
  };

  const handleUploadSuccess = (result) => {
    setBannerMessage(`Upload complete: ${result.message}`);
    loadDocuments();
  };

  // Stats calculation
  const totalCount = documents.length;
  const completedCount = documents.filter(d => (d.status || '').toUpperCase() === 'COMPLETED').length;
  const pendingCount = documents.filter(d => (d.status || '').toUpperCase() === 'PENDING').length;
  const failedCount = documents.filter(d => (d.status || '').toUpperCase() === 'FAILED').length;

  const formatDate = (dateStr) => {
    if (!dateStr) return '—';
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

  return (
    <div>
      {/* Page Header */}
      <div className="page-header">
        <div>
          <h1 className="page-title">Freight Bill OCR</h1>
          <p className="page-subtitle">Review scanned freight bills and extracted data</p>
        </div>

        <div className="header-actions">
          <button 
            className="btn btn-secondary" 
            onClick={loadDocuments} 
            disabled={isLoading || isScanning}
            title="Refresh document list"
          >
            <RefreshCw size={16} className={isLoading ? 'spinner-icon' : ''} />
            <span>Refresh</span>
          </button>

          <button 
            className="btn btn-secondary" 
            onClick={handleScanDirectory} 
            disabled={isScanning || isLoading}
            title="Scan input_doc_location folder"
          >
            {isScanning ? (
              <div className="spinner spinner-dark" />
            ) : (
              <FolderSearch size={16} />
            )}
            <span>Scan Folder</span>
          </button>

          <button 
            className="btn btn-primary" 
            onClick={() => setIsUploadOpen(true)}
          >
            <Upload size={16} />
            <span>Upload PDF</span>
          </button>
        </div>
      </div>

      {/* Banner Notifications */}
      {bannerMessage && (
        <div className="alert alert-success">
          <span>{bannerMessage}</span>
          <button 
            onClick={() => setBannerMessage(null)} 
            style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'inherit' }}
          >
            ✕
          </button>
        </div>
      )}

      {error && (
        <div className="alert alert-error">
          <span>{error}</span>
          <button className="btn btn-secondary" style={{ padding: '0.25rem 0.5rem', fontSize: '0.75rem' }} onClick={loadDocuments}>
            Retry
          </button>
        </div>
      )}

      {/* Summary Cards */}
      <div className="stats-grid">
        <div className="stat-card">
          <div className="stat-icon" style={{ backgroundColor: '#eff6ff', color: '#2563eb' }}>
            <FileText size={20} />
          </div>
          <div>
            <div className="stat-value">{totalCount}</div>
            <div className="stat-label">Total Documents</div>
          </div>
        </div>

        <div className="stat-card">
          <div className="stat-icon" style={{ backgroundColor: '#f0fdf4', color: '#16a34a' }}>
            <CheckCircle2 size={20} />
          </div>
          <div>
            <div className="stat-value">{completedCount}</div>
            <div className="stat-label">Completed</div>
          </div>
        </div>

        <div className="stat-card">
          <div className="stat-icon" style={{ backgroundColor: '#fffbeb', color: '#d97706' }}>
            <Clock size={20} />
          </div>
          <div>
            <div className="stat-value">{pendingCount}</div>
            <div className="stat-label">Pending Processing</div>
          </div>
        </div>

        <div className="stat-card">
          <div className="stat-icon" style={{ backgroundColor: '#fef2f2', color: '#dc2626' }}>
            <AlertTriangle size={20} />
          </div>
          <div>
            <div className="stat-value">{failedCount}</div>
            <div className="stat-label">Failed</div>
          </div>
        </div>
      </div>

      {/* Main Table Card */}
      <div className="card">
        <div className="card-header">
          <h2 className="card-title">Processed Documents</h2>
          <span style={{ fontSize: '0.8125rem', color: '#64748b' }}>
            Showing {documents.length} document{documents.length !== 1 ? 's' : ''}
          </span>
        </div>

        {isLoading ? (
          <div className="state-box">
            <div className="spinner spinner-dark" style={{ width: '2.5rem', height: '2.5rem' }} />
            <p className="state-desc" style={{ marginTop: '0.5rem' }}>Loading documents...</p>
          </div>
        ) : documents.length === 0 ? (
          <div className="state-box">
            <div className="state-icon">
              <FileText size={32} />
            </div>
            <h3 className="state-title">No documents found</h3>
            <p className="state-desc">
              Upload a freight bill PDF or drop files into the input folder to begin ingestion.
            </p>
            <div style={{ display: 'flex', gap: '0.75rem', marginTop: '0.5rem' }}>
              <button className="btn btn-secondary" onClick={handleScanDirectory} disabled={isScanning}>
                <FolderSearch size={16} />
                <span>Scan Input Folder</span>
              </button>
              <button className="btn btn-primary" onClick={() => setIsUploadOpen(true)}>
                <Upload size={16} />
                <span>Upload PDF</span>
              </button>
            </div>
          </div>
        ) : (
          <div className="table-container">
            <table className="data-table">
              <thead>
                <tr>
                  <th>File Name</th>
                  <th>Status</th>
                  <th>Uploaded / Processed Date</th>
                  <th style={{ textAlign: 'right' }}>Action</th>
                </tr>
              </thead>
              <tbody>
                {documents.map((doc) => (
                  <tr key={doc.id}>
                    <td>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
                        <div style={{ padding: '0.5rem', background: '#f1f5f9', borderRadius: '0.375rem', color: '#475569' }}>
                          <FileText size={18} />
                        </div>
                        <div>
                          <div style={{ fontWeight: 600, color: '#0f172a' }}>{doc.filename}</div>
                          <div className="mono" style={{ color: '#94a3b8', fontSize: '0.75rem' }}>
                            ID: {doc.id}
                          </div>
                        </div>
                      </div>
                    </td>
                    <td>
                      <StatusBadge status={doc.status} />
                    </td>
                    <td>
                      <div style={{ color: '#475569', fontSize: '0.875rem' }}>
                        {formatDate(doc.processed_at || doc.created_at)}
                      </div>
                    </td>
                    <td style={{ textAlign: 'right' }}>
                      <button 
                        className="btn btn-outline" 
                        style={{ padding: '0.375rem 0.75rem', fontSize: '0.8125rem' }}
                        onClick={() => onSelectDocument(doc.id)}
                      >
                        <Eye size={14} />
                        <span>View</span>
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Upload Modal */}
      <UploadModal 
        isOpen={isUploadOpen} 
        onClose={() => setIsUploadOpen(false)} 
        onUploadSuccess={handleUploadSuccess}
      />
    </div>
  );
}

