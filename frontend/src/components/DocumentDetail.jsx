import React, { useState, useEffect } from 'react';
import { ArrowLeft, RefreshCw, FileText, CheckCircle2, AlertCircle, Sparkles, FileCode, Play, List, AlignLeft, HelpCircle, Edit3, Save, X, Plus, Trash2 } from 'lucide-react';
import StatusBadge from './StatusBadge';
import { fetchDocumentById, reprocessDocument, submitDocumentReview, getDocumentFileUrl } from '../api';

export default function DocumentDetail({ documentId, onBack }) {
  const [doc, setDoc] = useState(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isReprocessing, setIsReprocessing] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [isEditing, setIsEditing] = useState(false);
  const [editFormData, setEditFormData] = useState({});
  const [error, setError] = useState(null);
  const [successMessage, setSuccessMessage] = useState(null);

  const loadDocument = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const data = await fetchDocumentById(documentId);
      setDoc(data);
      setEditFormData(data.extracted_data || {});
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

  const handleStartEditing = () => {
    setEditFormData(JSON.parse(JSON.stringify(doc.extracted_data || {})));
    setIsEditing(true);
    setError(null);
    setSuccessMessage(null);
  };

  const handleCancelEditing = () => {
    setEditFormData(doc.extracted_data || {});
    setIsEditing(false);
    setError(null);
  };

  const handleFieldChange = (key, value) => {
    setEditFormData(prev => ({
      ...prev,
      [key]: value
    }));
  };

  const handleLineItemChange = (index, field, value) => {
    setEditFormData(prev => {
      const items = [...(prev.line_items || [])];
      items[index] = {
        ...items[index],
        [field]: value
      };
      return {
        ...prev,
        line_items: items
      };
    });
  };

  const handleAddLineItem = () => {
    setEditFormData(prev => ({
      ...prev,
      line_items: [
        ...(prev.line_items || []),
        { item_no: String((prev.line_items || []).length + 1), description: '', quantity: '', rate: '', amount: '' }
      ]
    }));
  };

  const handleRemoveLineItem = (index) => {
    setEditFormData(prev => ({
      ...prev,
      line_items: (prev.line_items || []).filter((_, idx) => idx !== index)
    }));
  };

  const handleSaveReview = async () => {
    setIsSaving(true);
    setError(null);
    setSuccessMessage(null);
    try {
      const updated = await submitDocumentReview(documentId, editFormData);
      setDoc(updated);
      setEditFormData(updated.extracted_data || {});
      setIsEditing(false);
      setIsSaving(false);

      const statusUpper = (updated.status || '').toUpperCase();
      if (statusUpper === 'COMPLETED') {
        setSuccessMessage('Document corrections saved! Verification passed and status updated to COMPLETED.');
      } else {
        setSuccessMessage('Corrections saved! Some required fields still need review.');
      }
    } catch (err) {
      setIsSaving(false);
      setError(err.message || 'Failed to save document corrections.');
    }
  };

  const handleReprocess = async () => {
    setIsReprocessing(true);
    setError(null);
    setSuccessMessage(null);
    try {
      const updated = await reprocessDocument(documentId);
      setDoc(updated);
      setEditFormData(updated.extracted_data || {});
      setIsReprocessing(false);

      const statusUpper = (updated.status || '').toUpperCase();
      if (statusUpper === 'COMPLETED') {
        setSuccessMessage('Document processed successfully. Extracted data is ready.');
      } else if (statusUpper === 'REVIEW') {
        setSuccessMessage('Document requires manual review because extraction confidence is low or important fields are missing.');
      } else if (statusUpper === 'FAILED') {
        setError('Document processing failed. Please review the error and try again.');
      } else {
        setSuccessMessage('Document is being processed.');
      }
    } catch (err) {
      setIsReprocessing(false);
      setError(err.message || 'Document processing failed. Please review the error and try again.');
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

  const extractedData = doc.extracted_data || {};
  const rawOcr = doc.raw_ocr || {};
  const hasExtractedData = extractedData && typeof extractedData === 'object' && Object.keys(extractedData).length > 0;
  
  const lineItems = Array.isArray(extractedData.line_items) ? extractedData.line_items : [];
  const rawText = extractedData.raw_text || rawOcr.raw_text || '';

  const scalarFields = Object.entries(extractedData).filter(
    ([key]) => key !== 'line_items' && key !== 'raw_text' && key !== 'raw_ocr' && key !== 'reviewed' && key !== 'reviewed_at' && key !== 'manually_corrected'
  );

  const editableKeys = [
    { key: 'bill_number', label: 'Bill Number', required: true },
    { key: 'invoice_number', label: 'Invoice Number', required: false },
    { key: 'bill_date', label: 'Bill Date', required: false, type: 'date' },
    { key: 'consignor', label: 'Consignor (Shipper)', required: true },
    { key: 'consignee', label: 'Consignee (Receiver)', required: true },
    { key: 'origin', label: 'Origin Location', required: true },
    { key: 'destination', label: 'Destination Location', required: true },
    { key: 'vehicle_number', label: 'Vehicle / Truck #', required: false },
    { key: 'weight', label: 'Total Weight', required: false },
    { key: 'quantity', label: 'Total Quantity', required: false },
    { key: 'freight_amount', label: 'Freight Amount', required: false },
    { key: 'total_amount', label: 'Total Amount', required: true }
  ];

  const statusUpper = (doc.status || '').toUpperCase();

  return (
    <div>
      {/* Back Button & Top Actions */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1.5rem', flexWrap: 'wrap', gap: '0.75rem' }}>
        <button className="btn btn-secondary" onClick={onBack}>
          <ArrowLeft size={16} />
          <span>Back to Documents</span>
        </button>

        <div style={{ display: 'flex', gap: '0.75rem', alignItems: 'center' }}>
          {!isEditing ? (
            <button className="btn btn-primary" onClick={handleStartEditing}>
              <Edit3 size={16} />
              <span>Review & Correct</span>
            </button>
          ) : (
            <>
              <button className="btn btn-secondary" onClick={handleCancelEditing} disabled={isSaving}>
                <X size={16} />
                <span>Cancel</span>
              </button>
              <button className="btn btn-primary" onClick={handleSaveReview} disabled={isSaving}>
                {isSaving ? <div className="spinner" /> : <Save size={16} />}
                <span>Save Corrections</span>
              </button>
            </>
          )}

          <button 
            className="btn btn-secondary" 
            onClick={handleReprocess} 
            disabled={isReprocessing || isEditing}
          >
            <RefreshCw size={16} className={isReprocessing ? 'spinner-icon' : ''} />
            <span>Reprocess OCR</span>
          </button>
        </div>
      </div>

      {/* Notifications */}
      {successMessage && (
        <div className={statusUpper === 'REVIEW' ? 'alert alert-warning' : 'alert alert-success'} style={statusUpper === 'REVIEW' ? { backgroundColor: '#fff7ed', border: '1px solid #ffedd5', color: '#c2410c' } : {}}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            {statusUpper === 'REVIEW' ? <HelpCircle size={16} /> : <CheckCircle2 size={16} />}
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

      {doc.status === 'REVIEW' && doc.error_message && (
        <div className="alert alert-warning" style={{ marginBottom: '1.5rem', backgroundColor: '#fff7ed', border: '1px solid #ffedd5', borderRadius: '0.5rem', padding: '1rem 1.25rem', color: '#c2410c' }}>
          <div style={{ display: 'flex', alignItems: 'flex-start', gap: '0.625rem' }}>
            <HelpCircle size={18} color="#c2410c" style={{ marginTop: '0.125rem' }} />
            <div>
              <div style={{ fontWeight: 600, fontSize: '0.9375rem' }}>Needs Manual Review</div>
              <div style={{ fontSize: '0.8125rem', marginTop: '0.25rem' }}>{doc.error_message}</div>
            </div>
          </div>
        </div>
      )}

      {/* Overview Header Info Card */}
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
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', padding: '1.25rem 1.5rem', gap: '1.25rem', borderBottom: '1px solid #e2e8f0' }}>
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
            <div style={{ fontSize: '0.875rem', fontWeight: 600, color: (doc.confidence >= 0.70) ? '#16a34a' : '#c2410c' }}>
              {doc.confidence !== null && doc.confidence !== undefined ? `${(doc.confidence * 100).toFixed(1)}%` : 'N/A'}
            </div>
          </div>
        </div>
      </div>

      {/* Side-by-Side Split View Layout: Left = PDF Preview, Right = Extracted Data / Edit Form */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(450px, 1fr))', gap: '1.5rem', marginBottom: '2rem' }}>
        
        {/* LEFT COLUMN: Original PDF Document Preview Panel */}
        <div className="card" style={{ height: '750px', display: 'flex', flexDirection: 'column' }}>
          <div className="card-header" style={{ backgroundColor: '#f8fafc' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
              <FileText size={18} color="#2563eb" />
              <h3 className="card-title">Original Document Preview</h3>
            </div>
            <a 
              href={getDocumentFileUrl(doc.id)} 
              target="_blank" 
              rel="noreferrer" 
              className="btn btn-secondary"
              style={{ padding: '0.25rem 0.625rem', fontSize: '0.75rem' }}
            >
              Open PDF
            </a>
          </div>

          <div style={{ flex: 1, backgroundColor: '#f1f5f9', overflow: 'hidden' }}>
            <object 
              data={getDocumentFileUrl(doc.id)} 
              type="application/pdf" 
              width="100%" 
              height="100%"
              style={{ border: 'none', display: 'block' }}
            >
              <iframe 
                src={getDocumentFileUrl(doc.id)} 
                title={`Preview ${doc.filename}`}
                style={{ width: '100%', height: '100%', border: 'none' }}
              />
            </object>
          </div>
        </div>

        {/* RIGHT COLUMN: Extracted Data / Review & Correction Form */}
        <div className="card" style={{ height: '750px', overflowY: 'auto' }}>
          <div className="card-header" style={{ backgroundColor: isEditing ? '#eff6ff' : '#ffffff' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
              <Sparkles size={18} color="#2563eb" />
              <h3 className="card-title">{isEditing ? 'Review & Correct Fields' : 'Structured Extracted Data'}</h3>
            </div>

            {isEditing ? (
              <span className="badge badge-processing">Editing Mode</span>
            ) : (
              extractedData.manually_corrected && (
                <span className="badge badge-completed">Manually Reviewed</span>
              )
            )}
          </div>

          {/* READ-ONLY VIEW MODE */}
          {!isEditing ? (
            <div>
              {/* Dynamic Key -> Value Grid */}
              <div className="kv-grid">
                {scalarFields.map(([key, val]) => (
                  <div key={key} className="kv-card">
                    <div className="kv-label">{formatFieldLabel(key)}</div>
                    <div className="kv-value">
                      {val !== null && val !== undefined && String(val).trim() !== '' ? String(val) : '—'}
                    </div>
                  </div>
                ))}
              </div>

              {/* Line Items Table */}
              {lineItems.length > 0 && (
                <div style={{ borderTop: '1px solid #e2e8f0' }}>
                  <div style={{ padding: '1rem 1.5rem', backgroundColor: '#f8fafc', borderBottom: '1px solid #e2e8f0', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                    <List size={16} color="#2563eb" />
                    <h4 style={{ fontWeight: 600, fontSize: '0.9375rem', color: '#0f172a' }}>Line Items ({lineItems.length})</h4>
                  </div>
                  <div className="table-container">
                    <table className="data-table">
                      <thead>
                        <tr>
                          <th>Item</th>
                          <th>Description</th>
                          <th>Quantity</th>
                          <th>Rate</th>
                          <th style={{ textAlign: 'right' }}>Amount</th>
                        </tr>
                      </thead>
                      <tbody>
                        {lineItems.map((item, idx) => (
                          <tr key={idx}>
                            <td>{item.item_no || idx + 1}</td>
                            <td style={{ fontWeight: 500 }}>{item.description || '—'}</td>
                            <td>{item.quantity || '—'}</td>
                            <td>{item.rate || '—'}</td>
                            <td style={{ textAlign: 'right', fontWeight: 600 }}>{item.amount || '—'}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}

              {/* Raw OCR Text Accordion */}
              {rawText && (
                <div style={{ padding: '1rem 1.5rem', borderTop: '1px solid #e2e8f0', backgroundColor: '#f8fafc' }}>
                  <details>
                    <summary style={{ cursor: 'pointer', fontSize: '0.8125rem', fontWeight: 600, color: '#2563eb', display: 'inline-flex', alignItems: 'center', gap: '0.375rem' }}>
                      <AlignLeft size={14} />
                      <span>View Raw Extracted Text</span>
                    </summary>
                    <pre className="mono" style={{ backgroundColor: '#0f172a', color: '#f8fafc', padding: '1rem', borderRadius: '0.5rem', marginTop: '0.75rem', overflowX: 'auto', fontSize: '0.75rem', whiteSpace: 'pre-wrap' }}>
                      {rawText}
                    </pre>
                  </details>
                </div>
              )}
            </div>
          ) : (
            /* EDITABLE REVIEW FORM MODE */
            <div style={{ padding: '1.5rem' }}>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '1.25rem', marginBottom: '1.5rem' }}>
                {editableKeys.map(({ key, label, required, type }) => (
                  <div key={key}>
                    <label style={{ display: 'block', fontSize: '0.75rem', fontWeight: 600, color: '#475569', textTransform: 'uppercase', marginBottom: '0.375rem' }}>
                      {label} {required && <span style={{ color: '#dc2626' }}>*</span>}
                    </label>
                    <input 
                      type={type || 'text'}
                      value={editFormData[key] || ''}
                      onChange={(e) => handleFieldChange(key, e.target.value)}
                      placeholder={`Enter ${label}`}
                      style={{
                        width: '100%',
                        padding: '0.5rem 0.75rem',
                        fontSize: '0.875rem',
                        borderRadius: '0.375rem',
                        border: '1px solid #cbd5e1',
                        backgroundColor: '#ffffff',
                        color: '#0f172a'
                      }}
                    />
                  </div>
                ))}
              </div>

              {/* Editable Line Items Section */}
              <div style={{ borderTop: '1px solid #e2e8f0', paddingTop: '1.25rem', marginTop: '1.25rem' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
                  <h4 style={{ fontWeight: 600, fontSize: '0.9375rem', color: '#0f172a' }}>Line Items</h4>
                  <button className="btn btn-secondary" style={{ padding: '0.25rem 0.625rem', fontSize: '0.75rem' }} onClick={handleAddLineItem}>
                    <Plus size={14} />
                    <span>Add Item</span>
                  </button>
                </div>

                {(editFormData.line_items || []).map((item, idx) => (
                  <div key={idx} style={{ display: 'grid', gridTemplateColumns: '2fr 1fr 1fr 1fr 40px', gap: '0.5rem', alignItems: 'center', marginBottom: '0.75rem', padding: '0.75rem', backgroundColor: '#f8fafc', borderRadius: '0.375rem', border: '1px solid #e2e8f0' }}>
                    <input 
                      type="text" 
                      placeholder="Description"
                      value={item.description || ''}
                      onChange={(e) => handleLineItemChange(idx, 'description', e.target.value)}
                      style={{ padding: '0.375rem', fontSize: '0.8125rem', borderRadius: '0.25rem', border: '1px solid #cbd5e1' }}
                    />
                    <input 
                      type="text" 
                      placeholder="Qty"
                      value={item.quantity || ''}
                      onChange={(e) => handleLineItemChange(idx, 'quantity', e.target.value)}
                      style={{ padding: '0.375rem', fontSize: '0.8125rem', borderRadius: '0.25rem', border: '1px solid #cbd5e1' }}
                    />
                    <input 
                      type="text" 
                      placeholder="Rate"
                      value={item.rate || ''}
                      onChange={(e) => handleLineItemChange(idx, 'rate', e.target.value)}
                      style={{ padding: '0.375rem', fontSize: '0.8125rem', borderRadius: '0.25rem', border: '1px solid #cbd5e1' }}
                    />
                    <input 
                      type="text" 
                      placeholder="Amount"
                      value={item.amount || ''}
                      onChange={(e) => handleLineItemChange(idx, 'amount', e.target.value)}
                      style={{ padding: '0.375rem', fontSize: '0.8125rem', borderRadius: '0.25rem', border: '1px solid #cbd5e1' }}
                    />
                    <button 
                      onClick={() => handleRemoveLineItem(idx)}
                      style={{ background: 'none', border: 'none', color: '#dc2626', cursor: 'pointer', padding: '0.25rem' }}
                    >
                      <Trash2 size={16} />
                    </button>
                  </div>
                ))}
              </div>

              {/* Form Action Buttons */}
              <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '0.75rem', marginTop: '1.5rem', borderTop: '1px solid #e2e8f0', paddingTop: '1.25rem' }}>
                <button className="btn btn-secondary" onClick={handleCancelEditing} disabled={isSaving}>
                  <X size={16} />
                  <span>Cancel</span>
                </button>
                <button className="btn btn-primary" onClick={handleSaveReview} disabled={isSaving}>
                  {isSaving ? <div className="spinner" /> : <Save size={16} />}
                  <span>Save Corrections</span>
                </button>
              </div>
            </div>
          )}
        </div>

      </div>
    </div>
  );
}
