import React, { useState, useEffect, useRef } from 'react';
import { Upload, RefreshCw, RotateCcw, FolderSearch, FileText, CheckCircle2, Clock, AlertTriangle, AlertCircle, Eye, Search, Trash2 } from 'lucide-react';
import StatusBadge from './StatusBadge';
import UploadModal from './UploadModal';
import ConfirmModal from './ConfirmModal';
import { fetchDocuments, fetchDocumentStats, scanDocuments, deleteDocument, deleteAllDocuments, reprocessAllDocuments } from '../api';

const STAT_FILTERS = [
  { id: 'ALL', label: 'Total documents', key: 'total_documents', icon: FileText, iconBg: '#eff6ff', iconColor: '#2563eb' },
  { id: 'COMPLETED', label: 'Completed', key: 'completed', icon: CheckCircle2, iconBg: '#f0fdf4', iconColor: '#16a34a' },
  { id: 'REVIEW', label: 'Review needed', key: 'review_needed', icon: AlertCircle, iconBg: '#fff7ed', iconColor: '#ea580c' },
  { id: 'PENDING', label: 'Pending', key: 'pending', icon: Clock, iconBg: '#fffbeb', iconColor: '#d97706' },
  { id: 'FAILED', label: 'Failed', key: 'failed', icon: AlertTriangle, iconBg: '#fef2f2', iconColor: '#dc2626' },
];

function confidenceTone(conf) {
  if (conf == null) return 'low';
  if (conf >= 0.7) return 'high';
  if (conf >= 0.4) return 'medium';
  return 'low';
}

function TableHScroll({ children, watch }) {
  const topRef = useRef(null);
  const bottomRef = useRef(null);
  const syncing = useRef(false);
  const [spacerWidth, setSpacerWidth] = useState(0);
  const [overflows, setOverflows] = useState(false);

  useEffect(() => {
    const bottom = bottomRef.current;
    if (!bottom) return undefined;

    const measure = () => {
      const width = bottom.scrollWidth;
      setSpacerWidth(width);
      setOverflows(width > bottom.clientWidth + 1);
    };

    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(bottom);
    const table = bottom.querySelector('table');
    if (table) observer.observe(table);
    window.addEventListener('resize', measure);
    return () => {
      observer.disconnect();
      window.removeEventListener('resize', measure);
    };
  }, [watch]);

  const syncFrom = (source) => () => {
    if (syncing.current) return;
    const top = topRef.current;
    const bottom = bottomRef.current;
    if (!top || !bottom) return;
    syncing.current = true;
    if (source === 'top') bottom.scrollLeft = top.scrollLeft;
    else top.scrollLeft = bottom.scrollLeft;
    syncing.current = false;
  };

  return (
    <div className="table-scroll-dual">
      <div
        className={`table-scroll-top${overflows ? '' : ' is-idle'}`}
        ref={topRef}
        onScroll={syncFrom('top')}
        aria-hidden={!overflows}
      >
        <div className="table-scroll-top-spacer" style={{ width: spacerWidth }} />
      </div>
      <div className="table-container" ref={bottomRef} onScroll={syncFrom('bottom')}>
        {children}
      </div>
    </div>
  );
}

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
  const [searchText, setSearchText] = useState('');
  const [deletingId, setDeletingId] = useState(null);
  const [isDeletingAll, setIsDeletingAll] = useState(false);
  const [pendingDelete, setPendingDelete] = useState(null);
  const [pendingReprocessAll, setPendingReprocessAll] = useState(false);
  const [isReprocessingAll, setIsReprocessingAll] = useState(false);

  const busy = isLoading || isScanning || isDeletingAll || isReprocessingAll || Boolean(deletingId);
  const totalCount = stats.total_documents || documents.length;

  const loadData = async (query) => {
    const searchQuery = query === undefined ? searchText : query;
    setIsLoading(true);
    setError(null);
    try {
      const [docsData, statsData] = await Promise.all([
        fetchDocuments(searchQuery),
        fetchDocumentStats().catch(() => null)
      ]);
      setDocuments(docsData);

      if (statsData) {
        setStats(statsData);
      } else {
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
      setBannerMessage(`Folder scan complete: ${result.total_scanned} files scanned (${result.ingested_count} ingested, ${result.duplicate_count} duplicates).`);
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

  const handleConfirmDelete = async () => {
    if (!pendingDelete) return;

    if (pendingDelete.type === 'one') {
      const doc = pendingDelete.doc;
      const filename = doc.original_filename || doc.filename || 'this document';
      setDeletingId(doc.id);
      setError(null);
      try {
        await deleteDocument(doc.id);
        setBannerMessage(`Deleted "${filename}".`);
        setPendingDelete(null);
        await loadData();
      } catch (err) {
        setError(err.message || 'Failed to delete document.');
      } finally {
        setDeletingId(null);
      }
      return;
    }

    setIsDeletingAll(true);
    setError(null);
    try {
      const result = await deleteAllDocuments();
      const count = result.deleted_count ?? totalCount;
      setBannerMessage(result.message || `Deleted ${count} document${count === 1 ? '' : 's'}.`);
      setPendingDelete(null);
      await loadData();
    } catch (err) {
      setError(err.message || 'Failed to delete all documents.');
    } finally {
      setIsDeletingAll(false);
    }
  };

  const handleConfirmReprocessAll = async () => {
    setIsReprocessingAll(true);
    setError(null);
    try {
      const result = await reprocessAllDocuments();
      setBannerMessage(result.message || `Reprocessed ${result.processed_count ?? totalCount} bills.`);
      setPendingReprocessAll(false);
      await loadData();
    } catch (err) {
      setError(err.message || 'Failed to reprocess all documents.');
    } finally {
      setIsReprocessingAll(false);
    }
  };

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

  const deleteFilename = pendingDelete?.type === 'one'
    ? (pendingDelete.doc.original_filename || pendingDelete.doc.filename || 'this document')
    : '';

  return (
    <div>
      <div className="page-header">
        <div>
          <h1 className="page-title">Documents</h1>
          <p className="page-subtitle">Review extracted freight bills, correct fields, and reprocess OCR when needed.</p>
        </div>

        <div className="header-actions">
          <button
            className="btn btn-primary"
            onClick={() => setIsUploadOpen(true)}
            disabled={isDeletingAll || isReprocessingAll}
          >
            <Upload size={15} />
            <span>Upload bill</span>
          </button>
        </div>
      </div>

      <div className="list-toolbar">
        <div className="input-search-box">
          <Search size={16} color="#94a3b8" />
          <input
            type="search"
            className="input-search"
            value={searchText}
            onChange={(e) => setSearchText(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') loadData(); }}
            placeholder="Search bill # or filename, then press Enter"
            aria-label="Search documents"
          />
        </div>

        <div className="list-toolbar-actions">
          <button
            className="btn btn-secondary btn-icon"
            onClick={loadData}
            disabled={busy}
            title="Refresh document list"
            aria-label="Refresh"
          >
            <RefreshCw size={15} className={isLoading ? 'spinner-icon' : ''} />
          </button>

          <button
            className="btn btn-secondary"
            onClick={handleScanDirectory}
            disabled={busy}
            title="Scan input_doc_location folder"
          >
            {isScanning ? <div className="spinner spinner-dark" /> : <FolderSearch size={15} />}
            <span>Scan folder</span>
          </button>

          <button
            className="btn btn-secondary"
            onClick={() => setPendingReprocessAll(true)}
            disabled={busy || !totalCount}
            title="Reprocess every bill with Groq Vision as the first field layer"
          >
            {isReprocessingAll ? <div className="spinner spinner-dark" /> : <RotateCcw size={15} />}
            <span>{isReprocessingAll ? 'Reprocessing…' : 'Reprocess all'}</span>
          </button>

          <button
            className="btn btn-ghost-danger"
            onClick={() => setPendingDelete({ type: 'all' })}
            disabled={isDeletingAll || isReprocessingAll || isLoading || isScanning || !totalCount}
            title="Delete every freight bill and stored file"
          >
            {isDeletingAll ? <div className="spinner spinner-dark" /> : <Trash2 size={15} />}
            <span>Delete all</span>
          </button>
        </div>
      </div>

      {bannerMessage && (
        <div className="alert alert-success">
          <span>{bannerMessage}</span>
          <button type="button" className="alert-dismiss" onClick={() => setBannerMessage(null)} aria-label="Dismiss">
            ✕
          </button>
        </div>
      )}

      {error && (
        <div className="alert alert-error">
          <span>{error}</span>
          <button className="btn btn-secondary" style={{ padding: '0.25rem 0.625rem', fontSize: '0.75rem' }} onClick={loadData}>
            Retry
          </button>
        </div>
      )}

      <div className="stats-grid">
        {STAT_FILTERS.map((item) => {
          const Icon = item.icon;
          return (
            <button
              key={item.id}
              type="button"
              className={`stat-card ${selectedFilter === item.id ? 'active' : ''}`}
              onClick={() => setSelectedFilter(item.id)}
            >
              <div className="stat-icon" style={{ backgroundColor: item.iconBg, color: item.iconColor }}>
                <Icon size={20} />
              </div>
              <div>
                <div className="stat-value">{stats[item.key]}</div>
                <div className="stat-label">{item.label}</div>
              </div>
            </button>
          );
        })}
      </div>

      <div className="card">
        <div className="card-header" style={{ flexWrap: 'wrap', gap: '1rem' }}>
          <div>
            <div className="card-title">
              <FileText size={18} color="#2563eb" />
              <span>Freight bills</span>
            </div>
            <div className="card-title-meta" style={{ marginTop: '0.2rem' }}>
              {filteredDocuments.length} shown
              {selectedFilter !== 'ALL' ? ` · ${selectedFilter.toLowerCase()}` : ''}
            </div>
          </div>
        </div>

        {isLoading ? (
          <div className="state-box">
            <div className="spinner spinner-dark" style={{ width: '2.5rem', height: '2.5rem' }} />
            <p className="state-desc" style={{ marginTop: '0.5rem' }}>Fetching freight documents...</p>
          </div>
        ) : filteredDocuments.length === 0 ? (
          <div className="state-box">
            <div className="state-icon">
              <FileText size={32} />
            </div>
            <h3 className="state-title">No documents found</h3>
            <p className="state-desc">
              {selectedFilter === 'ALL'
                ? (searchText.trim()
                  ? `No documents match “${searchText.trim()}”.`
                  : 'Upload a freight bill or scan the input folder to begin OCR processing.')
                : `No documents currently match the ${selectedFilter.toLowerCase()} filter.`}
            </p>
            {selectedFilter === 'ALL' && !searchText.trim() ? (
              <div style={{ display: 'flex', gap: '0.75rem', flexWrap: 'wrap', justifyContent: 'center' }}>
                <button className="btn btn-primary" onClick={() => setIsUploadOpen(true)}>
                  <Upload size={15} />
                  <span>Upload bill</span>
                </button>
                <button className="btn btn-secondary" onClick={handleScanDirectory} disabled={isScanning}>
                  <FolderSearch size={15} />
                  <span>Scan folder</span>
                </button>
              </div>
            ) : (
              <button
                className="btn btn-secondary"
                onClick={() => {
                  setSelectedFilter('ALL');
                  setSearchText('');
                  loadData('');
                }}
              >
                Show all documents
              </button>
            )}
          </div>
        ) : (
          <TableHScroll watch={filteredDocuments.length}>
            <table className="data-table">
              <thead>
                <tr>
                  <th>Filename</th>
                  <th>Status</th>
                  <th>Type</th>
                  <th>Confidence</th>
                  <th>Created</th>
                  <th>Processed</th>
                  <th style={{ textAlign: 'right' }}>Actions</th>
                </tr>
              </thead>
              <tbody>
                {filteredDocuments.map((doc) => {
                  const conf = doc.overall_confidence ?? doc.confidence;
                  const tone = confidenceTone(conf);
                  const filename = doc.original_filename || doc.filename;
                  return (
                    <tr
                      key={doc.id}
                      className="clickable"
                      onClick={() => onSelectDocument(doc.id)}
                    >
                      <td>
                        <div className="file-cell">
                          <div className="file-cell-icon">
                            <FileText size={18} />
                          </div>
                          <div style={{ minWidth: 0 }}>
                            <div className="file-cell-name" title={filename}>{filename}</div>
                            <div className="file-cell-meta mono">ID {String(doc.id).slice(0, 8)}</div>
                          </div>
                        </div>
                      </td>
                      <td>
                        <StatusBadge status={doc.status} />
                      </td>
                      <td>
                        <span className="type-pill">
                          {(doc.document_type || 'freight_bill').replace(/_/g, ' ')}
                        </span>
                      </td>
                      <td>
                        {conf !== null && conf !== undefined ? (
                          <div className="conf-meter">
                            <div className="conf-meter-track">
                              <div
                                className={`conf-meter-fill ${tone}`}
                                style={{ width: `${Math.max(4, Math.min(100, conf * 100))}%` }}
                              />
                            </div>
                            <span className="conf-meter-label" style={{ color: tone === 'high' ? '#16a34a' : (tone === 'medium' ? '#ea580c' : '#94a3b8') }}>
                              {(conf * 100).toFixed(0)}%
                            </span>
                          </div>
                        ) : (
                          <span className="conf-meter-label" style={{ color: '#94a3b8' }}>—</span>
                        )}
                      </td>
                      <td>
                        <div className="table-date">{formatDate(doc.created_at)}</div>
                      </td>
                      <td>
                        <div className="table-date">{formatDate(doc.processed_at)}</div>
                      </td>
                      <td style={{ textAlign: 'right' }} onClick={(event) => event.stopPropagation()}>
                        <div className="table-actions">
                          <button
                            className="btn btn-outline"
                            style={{ padding: '0.375rem 0.75rem', fontSize: '0.8125rem' }}
                            onClick={() => onSelectDocument(doc.id)}
                          >
                            <Eye size={14} />
                            <span>Open</span>
                          </button>
                          <button
                            className="btn btn-danger btn-icon"
                            style={{ width: '2.15rem', height: '2.15rem' }}
                            onClick={() => setPendingDelete({ type: 'one', doc })}
                            disabled={deletingId === doc.id || isDeletingAll || isReprocessingAll}
                            title="Delete document"
                            aria-label={`Delete ${filename}`}
                          >
                            {deletingId === doc.id ? (
                              <div className="spinner spinner-dark" />
                            ) : (
                              <Trash2 size={14} />
                            )}
                          </button>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </TableHScroll>
        )}
      </div>

      <UploadModal
        isOpen={isUploadOpen}
        onClose={() => setIsUploadOpen(false)}
        onUploadSuccess={handleUploadSuccess}
      />

      <ConfirmModal
        isOpen={Boolean(pendingDelete)}
        title={pendingDelete?.type === 'all' ? 'Delete all freight bills?' : 'Delete this document?'}
        description={
          pendingDelete?.type === 'all'
            ? `This permanently removes ${totalCount} bill${totalCount === 1 ? '' : 's'} and their stored files. This cannot be undone.`
            : `“${deleteFilename}” will be removed from the list and storage. This cannot be undone.`
        }
        confirmLabel={pendingDelete?.type === 'all' ? 'Delete all' : 'Delete'}
        busyLabel="Deleting…"
        danger
        isBusy={isDeletingAll || Boolean(deletingId)}
        onCancel={() => {
          if (!isDeletingAll && !deletingId) setPendingDelete(null);
        }}
        onConfirm={handleConfirmDelete}
      />

      <ConfirmModal
        isOpen={pendingReprocessAll}
        title="Reprocess all freight bills?"
        description={`This re-runs OCR on ${totalCount} bill${totalCount === 1 ? '' : 's'} using Groq Vision, then snaps fields to the gazetteer. Extracted fields are overwritten — saved review corrections are not kept. This can take several minutes.`}
        confirmLabel="Reprocess all"
        busyLabel="Reprocessing…"
        isBusy={isReprocessingAll}
        onCancel={() => {
          if (!isReprocessingAll) setPendingReprocessAll(false);
        }}
        onConfirm={handleConfirmReprocessAll}
      />
    </div>
  );
}
