import React, { useState, useEffect } from 'react';
import { Upload, RefreshCw, FolderSearch, FileText, CheckCircle2, Clock, AlertTriangle, HelpCircle, Eye } from 'lucide-react';
import StatusBadge from './StatusBadge';
import UploadModal from './UploadModal';
import { fetchDocuments, fetchDocumentStats, scanDocuments } from '../api';

export default function DocumentsList({ onSelectDocument }) {
  const [documents, setDocuments] = useState([]);
  const [stats, setStats] = useState({
    total_documents: 0,
    completed: 0,
    review_needed: 0,
    pending: 0,
    failed: 0
  });
  const [selectedFilter, setSelectedFilter] = useState('ALL');
  const [isLoading, setIsLoading] = useState(true);
  const [isScanning, setIsScanning] = useState(false);
  const [error, setError] = useState(null);
  const [isUploadOpen, setIsUploadOpen] = useState(false);
  const [bannerMessage, setBannerMessage] = useState(null);

  const loadData = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const [docsData, statsData] = await Promise.all([
        fetchDocuments(),
        fetchDocumentStats().catch(() => null)
      ]);
      setDocuments(docsData);

      if (statsData) {
        setStats(statsData);
      } else {
        // Fallback stats calculation if /stats endpoint unavailable
        setStats({
          total_documents: docsData.length,
          completed: docsData.filter(d => (d.status || '').toUpperCase() === 'COMPLETED').length,
          review_needed: docsData.filter(d => (d.status || '').toUpperCase() === 'REVIEW').length,
          pending: docsData.filter(d => ['PENDING', 'PROCESSING'].includes((d.status || '').toUpperCase())).length,
          failed: docsData.filter(d => (d.status || '').toUpperCase() === 'FAILED').length
        });
      }
      setIsLoading(false);
    } catch (err) {
      setIsLoading(false);
      setError(err.message || 'Failed to fetch documents from server.');
    }
  };

  useEffect(() => {
    loadData();
  }, []);

  const handleScanDirectory = async () => {
    setIsScanning(true);
    setError(null);
    try {
      const result = await scanDocuments();
      setIsScanning(false);
      setBannerMessage(`Scanned ${result.total_scanned} files. Ingested: ${result.ingested_count}, Duplicates: ${result.duplicate_count}, Invalid: ${result.invalid_count}.`);
      loadData();
    } catch (err) {
      setIsScanning(false);
      setError(err.message || 'Failed to scan input directory.');
    }
  };

  const handleUploadSuccess = (result) => {
    setBannerMessage(`Upload complete: ${result.message}`);
    loadData();
  };

  // Filter documents based on selected tab
  const filteredDocuments = documents.filter(doc => {
    const status = (doc.status || '').toUpperCase();
    if (selectedFilter === 'ALL') return true;
    if (selectedFilter === 'COMPLETED') return status === 'COMPLETED';
    if (selectedFilter === 'REVIEW') return status === 'REVIEW';
    if (selectedFilter === 'PENDING') return status === 'PENDING' || status === 'PROCESSING';
    if (selectedFilter === 'FAILED') return status === 'FAILED';
    return true;
  });

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
            onClick={loadData} 
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
          <button className="btn btn-secondary" style={{ padding: '0.25rem 0.5rem', fontSize: '0.75rem' }} onClick={loadData}>
            Retry
          </button>
        </div>
      )}

      {/* 5 Top Summary Statistic Cards */}
      <div className="stats-grid" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))' }}>
        <div className="stat-card" style={{ cursor: 'pointer' }} onClick={() => setSelectedFilter('ALL')}>
          <div className="stat-icon" style={{ backgroundColor: '#eff6ff', color: '#2563eb' }}>
            <FileText size={20} />
          </div>
          <div>
            <div className="stat-value">{stats.total_documents}</div>
            <div className="stat-label">Total Documents</div>
          </div>
        </div>

        <div className="stat-card" style={{ cursor: 'pointer' }} onClick={() => setSelectedFilter('COMPLETED')}>
          <div className="stat-icon" style={{ backgroundColor: '#f0fdf4', color: '#16a34a' }}>
            <CheckCircle2 size={20} />
          </div>
          <div>
            <div className="stat-value">{stats.completed}</div>
            <div className="stat-label">Completed</div>
          </div>
        </div>

        <div className="stat-card" style={{ cursor: 'pointer' }} onClick={() => setSelectedFilter('REVIEW')}>
          <div className="stat-icon" style={{ backgroundColor: '#fff7ed', color: '#c2410c' }}>
            <HelpCircle size={20} />
          </div>
          <div>
            <div className="stat-value">{stats.review_needed}</div>
            <div className="stat-label">Review Needed</div>
          </div>
        </div>

        <div className="stat-card" style={{ cursor: 'pointer' }} onClick={() => setSelectedFilter('PENDING')}>
          <div className="stat-icon" style={{ backgroundColor: '#fffbeb', color: '#d97706' }}>
            <Clock size={20} />
          </div>
          <div>
            <div className="stat-value">{stats.pending}</div>
            <div className="stat-label">Pending Processing</div>
          </div>
        </div>

        <div className="stat-card" style={{ cursor: 'pointer' }} onClick={() => setSelectedFilter('FAILED')}>
          <div className="stat-icon" style={{ backgroundColor: '#fef2f2', color: '#dc2626' }}>
            <AlertTriangle size={20} />
          </div>
          <div>
            <div className="stat-value">{stats.failed}</div>
            <div className="stat-label">Failed</div>
          </div>
        </div>
      </div>

      {/* Main Table Card with Filter Tabs */}
      <div className="card">
        <div className="card-header" style={{ flexWrap: 'wrap', gap: '1rem' }}>
          <h2 className="card-title">Processed Documents</h2>
          
          {/* Status Filter Tabs */}
          <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
            {[
              { id: 'ALL', label: `All (${stats.total_documents})` },
              { id: 'COMPLETED', label: `Completed (${stats.completed})` },
              { id: 'REVIEW', label: `Review Needed (${stats.review_needed})` },
              { id: 'PENDING', label: `Pending (${stats.pending})` },
              { id: 'FAILED', label: `Failed (${stats.failed})` },
            ].map(tab => (
              <button
                key={tab.id}
                onClick={() => setSelectedFilter(tab.id)}
                style={{
                  padding: '0.375rem 0.75rem',
                  fontSize: '0.8125rem',
                  fontWeight: 600,
                  borderRadius: '0.375rem',
                  border: '1px solid',
                  borderColor: selectedFilter === tab.id ? '#2563eb' : '#e2e8f0',
                  backgroundColor: selectedFilter === tab.id ? '#2563eb' : '#ffffff',
                  color: selectedFilter === tab.id ? '#ffffff' : '#64748b',
                  cursor: 'pointer',
                  transition: 'all 0.15s ease'
                }}
              >
                {tab.label}
              </button>
            ))}
          </div>
        </div>

        {isLoading ? (
          <div className="state-box">
            <div className="spinner spinner-dark" style={{ width: '2.5rem', height: '2.5rem' }} />
            <p className="state-desc" style={{ marginTop: '0.5rem' }}>Loading documents...</p>
          </div>
        ) : filteredDocuments.length === 0 ? (
          <div className="state-box">
            <div className="state-icon">
              <FileText size={32} />
            </div>
            <h3 className="state-title">No documents match filter</h3>
            <p className="state-desc">
              {selectedFilter === 'ALL'
                ? 'Upload a freight bill PDF or drop files into the input folder to begin ingestion.'
                : `No documents currently in '${selectedFilter}' status.`}
            </p>
            {selectedFilter !== 'ALL' && (
              <button className="btn btn-secondary" onClick={() => setSelectedFilter('ALL')}>
                Show All Documents
              </button>
            )}
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
                {filteredDocuments.map((doc) => (
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
