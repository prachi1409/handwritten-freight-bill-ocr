import React, { useState, useEffect } from 'react';
import { ArrowLeft, RefreshCw, FileText, CheckCircle2, AlertCircle, Sparkles, AlignLeft, Edit3, Save, X, Plus, Trash2, ExternalLink, ListFilter, Hash, Calendar, Activity, ChevronDown, ChevronUp, Cpu, Info } from 'lucide-react';
import StatusBadge from './StatusBadge';
import { fetchDocumentById, reprocessDocument, submitDocumentReview, getDocumentFileUrl } from '../api';

export default function DocumentDetail({ documentId, onBack }) {
  const [doc, setDoc] = useState(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isReprocessing, setIsReprocessing] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [isEditing, setIsEditing] = useState(false);
  const [showOcrDebug, setShowOcrDebug] = useState(false);
  const [editFormData, setEditFormData] = useState({});
  const [error, setError] = useState(null);
  const [successMessage, setSuccessMessage] = useState(null);

  const loadDocument = async () => {
    if (!documentId) {
      setError("No document ID specified.");
      setIsLoading(false);
      return;
    }
    setIsLoading(true);
    setError(null);
    try {
      const data = await fetchDocumentById(documentId);
      if (!data) {
        throw new Error(`Document with ID "${documentId}" was not found.`);
      }
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
    } else {
      setIsLoading(false);
      setError("No document ID specified.");
    }
  }, [documentId]);

  const handleStartEditing = () => {
    setEditFormData(JSON.parse(JSON.stringify(doc?.extracted_data || {})));
    setIsEditing(true);
    setError(null);
    setSuccessMessage(null);
  };

  const handleCancelEditing = () => {
    setEditFormData(doc?.extracted_data || {});
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
        setSuccessMessage('Document corrections saved! Status updated to COMPLETED.');
      } else {
        setSuccessMessage('Corrections saved! Document remains in REVIEW for pending required fields.');
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
        setSuccessMessage('OCR extraction completed successfully.');
      } else if (statusUpper === 'REVIEW') {
        setSuccessMessage('Document reprocessed and flagged for manual review.');
      } else if (statusUpper === 'FAILED') {
        setError('Document processing failed.');
      } else {
        setSuccessMessage('Document processing updated.');
      }
    } catch (err) {
      setIsReprocessing(false);
      setError(err.message || 'Document processing failed.');
    }
  };

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

  const formatFieldLabel = (key) => {
    return key
      .replace(/_/g, ' ')
      .replace(/([a-z])([A-Z])/g, '$1 $2')
      .replace(/\b\w/g, (char) => char.toUpperCase());
  };

  const renderConfidenceBadge = (score) => {
    if (score === null || score === undefined || score === 0) return null;
    const pct = Math.round(score * 100);
    let colorClass = '#dc2626'; // Low (red)
    let label = 'Low';
    if (score >= 0.90) {
      colorClass = '#16a34a'; // High (green)
      label = 'High';
    } else if (score >= 0.70) {
      colorClass = '#d97706'; // Medium (amber)
      label = 'Medium';
    }

    return (
      <span style={{ fontSize: '0.6875rem', fontWeight: 700, color: colorClass, marginLeft: '0.5rem', display: 'inline-flex', alignItems: 'center', gap: '0.25rem' }}>
        <span>•</span> {pct}% ({label})
      </span>
    );
  };

  if (isLoading) {
    return (
      <div>
        <button className="btn btn-secondary" onClick={onBack} style={{ marginBottom: '1.25rem' }}>
          <ArrowLeft size={15} />
          <span>Back to Documents</span>
        </button>
        <div className="card">
          <div className="state-box">
            <div className="spinner spinner-dark" style={{ width: '2.5rem', height: '2.5rem' }} />
            <p className="state-desc" style={{ marginTop: '0.5rem' }}>Loading document data...</p>
          </div>
        </div>
      </div>
    );
  }

  if (error || !doc) {
    return (
      <div>
        <button className="btn btn-secondary" onClick={onBack} style={{ marginBottom: '1.25rem' }}>
          <ArrowLeft size={15} />
          <span>Back to Documents</span>
        </button>
        <div className="card">
          <div className="state-box">
            <div className="state-icon" style={{ backgroundColor: '#fef2f2', color: '#dc2626' }}>
              <AlertCircle size={32} />
            </div>
            <h3 className="state-title">Document Not Found or Network Error</h3>
            <p className="state-desc">{error || `Unable to load details for document ID "${documentId}".`}</p>
            <div style={{ display: 'flex', gap: '0.75rem', marginTop: '0.5rem' }}>
              <button className="btn btn-secondary" onClick={loadDocument}>
                Retry
              </button>
              <button className="btn btn-primary" onClick={onBack}>
                Return to Documents
              </button>
            </div>
          </div>
        </div>
      </div>
    );
  }

  const extractedData = doc.extracted_data || {};
  const fieldConfidenceMap = doc.field_confidence || extractedData.field_confidence || {};
  const rawOcr = doc.ocr_metadata || doc.raw_ocr || {};
  const lineItems = Array.isArray(extractedData.line_items) ? extractedData.line_items : [];
  const rawText = doc.raw_ocr_text || extractedData.raw_text || rawOcr.raw_text || '';
  const validationWarnings = doc.validation_warnings || rawOcr.validation_warnings || [];

  const schemaFieldKeys = [
    "bill_number", "bill_date", "carrier", "invoice_number",
    "consignor", "consignee", "origin", "destination",
    "commodity_description", "quantity", "weight",
    "freight_amount", "total_amount", "vehicle_number",
    "driver_name", "pickup_time", "delivery_time",
    "special_instructions", "driver_signature", "consignee_signature", "received_datetime"
  ];

  const editableKeys = schemaFieldKeys.map(key => ({
    key,
    label: formatFieldLabel(key),
    required: ["bill_number", "consignor", "consignee", "origin", "destination", "total_amount"].includes(key),
    type: key.includes("date") ? "date" : "text"
  }));

  const statusUpper = (doc.status || '').toUpperCase();
  const overallConf = doc.overall_confidence ?? doc.confidence;

  return (
    <div>
      {/* Back Button & Action Toolbar */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1.5rem', flexWrap: 'wrap', gap: '0.75rem' }}>
        <button className="btn btn-secondary" onClick={onBack}>
          <ArrowLeft size={16} />
          <span>Back to Documents</span>
        </button>

        <div style={{ display: 'flex', gap: '0.75rem', alignItems: 'center', flexWrap: 'wrap' }}>
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

      {/* Banner Alerts */}
      {successMessage && (
        <div className={statusUpper === 'REVIEW' ? 'alert alert-warning' : 'alert alert-success'}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            {statusUpper === 'REVIEW' ? <AlertCircle size={16} /> : <CheckCircle2 size={16} />}
            <span>{successMessage}</span>
          </div>
          <button 
            onClick={() => setSuccessMessage(null)}
            style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'inherit', fontWeight: 700 }}
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

      {statusUpper === 'REVIEW' && (
        <div className="alert alert-warning">
          <div style={{ display: 'flex', alignItems: 'flex-start', gap: '0.75rem' }}>
            <AlertCircle size={20} color="#ea580c" style={{ marginTop: '0.125rem', flexShrink: 0 }} />
            <div>
              <div style={{ fontWeight: 700, fontSize: '0.9375rem', color: '#c2410c' }}>Needs Manual Review</div>
              <div style={{ fontSize: '0.875rem', marginTop: '0.25rem', color: '#c2410c' }}>
                {doc.error_message || (validationWarnings.length > 0 ? validationWarnings.join('; ') : 'Important required fields are missing or extraction confidence is below threshold.')}
              </div>
              {validationWarnings.length > 0 && (
                <ul style={{ marginTop: '0.5rem', paddingLeft: '1.25rem', fontSize: '0.8125rem', color: '#c2410c' }}>
                  {validationWarnings.map((w, idx) => (
                    <li key={idx}>{w}</li>
                  ))}
                </ul>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Top Document Metadata Card */}
      <div className="card" style={{ marginBottom: '1.75rem' }}>
        <div className="card-header" style={{ backgroundColor: '#f8fafc' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.875rem' }}>
            <div style={{ padding: '0.625rem', backgroundColor: '#eff6ff', borderRadius: '0.625rem', color: '#2563eb', flexShrink: 0 }}>
              <FileText size={24} />
            </div>
            <div>
              <h2 className="card-title" style={{ fontSize: '1.25rem', fontWeight: 800 }}>{doc.original_filename || doc.filename}</h2>
              <div className="mono" style={{ fontSize: '0.75rem', color: '#64748b', marginTop: '0.125rem' }}>
                ID: {doc.id}
              </div>
            </div>
          </div>

          <StatusBadge status={doc.status} />
        </div>

        {/* Key Information Metric Pills Strip */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(170px, 1fr))', padding: '1.25rem 1.5rem', gap: '1.25rem', backgroundColor: '#ffffff' }}>
          <div style={{ borderRight: '1px solid #f1f5f9', paddingRight: '1rem' }}>
            <div style={{ fontSize: '0.6875rem', fontWeight: 700, color: '#64748b', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: '0.25rem', display: 'flex', alignItems: 'center', gap: '0.375rem' }}>
              <Hash size={12} color="#64748b" />
              <span>SHA-256 Hash</span>
            </div>
            <div className="mono" style={{ fontSize: '0.75rem', color: '#0f172a', fontWeight: 600, wordBreak: 'break-all' }}>
              {doc.file_hash ? `${doc.file_hash.substring(0, 16)}...` : '—'}
            </div>
          </div>

          <div style={{ borderRight: '1px solid #f1f5f9', paddingRight: '1rem' }}>
            <div style={{ fontSize: '0.6875rem', fontWeight: 700, color: '#64748b', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: '0.25rem', display: 'flex', alignItems: 'center', gap: '0.375rem' }}>
              <Calendar size={12} color="#64748b" />
              <span>Uploaded Date</span>
            </div>
            <div style={{ fontSize: '0.875rem', fontWeight: 700, color: '#0f172a' }}>
              {formatDate(doc.created_at)}
            </div>
          </div>

          <div style={{ borderRight: '1px solid #f1f5f9', paddingRight: '1rem' }}>
            <div style={{ fontSize: '0.6875rem', fontWeight: 700, color: '#64748b', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: '0.25rem', display: 'flex', alignItems: 'center', gap: '0.375rem' }}>
              <Activity size={12} color="#64748b" />
              <span>Processed Date</span>
            </div>
            <div style={{ fontSize: '0.875rem', fontWeight: 700, color: '#0f172a' }}>
              {formatDate(doc.processed_at)}
            </div>
          </div>

          <div>
            <div style={{ fontSize: '0.6875rem', fontWeight: 700, color: '#64748b', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: '0.25rem', display: 'flex', alignItems: 'center', gap: '0.375rem' }}>
              <Activity size={12} color="#64748b" />
              <span>Overall Confidence</span>
            </div>
            <div style={{ fontSize: '0.9375rem', fontWeight: 800, color: (overallConf >= 0.70) ? '#16a34a' : '#ea580c' }}>
              {overallConf !== null && overallConf !== undefined ? `${(overallConf * 100).toFixed(1)}%` : '—'}
            </div>
          </div>
        </div>
      </div>

      {/* Side-by-Side Responsive Split View */}
      <div className="detail-split-grid">
        
        {/* LEFT COLUMN: Original PDF Document Preview Panel */}
        <div className="card" style={{ height: '780px', display: 'flex', flexDirection: 'column', marginBottom: 0 }}>
          <div className="card-header" style={{ backgroundColor: '#f8fafc' }}>
            <div className="card-title">
              <FileText size={18} color="#2563eb" />
              <span>Original Document Preview</span>
            </div>
            <a 
              href={getDocumentFileUrl(doc.id)} 
              target="_blank" 
              rel="noreferrer" 
              className="btn btn-secondary"
              style={{ padding: '0.3125rem 0.75rem', fontSize: '0.75rem' }}
            >
              <ExternalLink size={13} />
              <span>Open PDF</span>
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
        <div className="card" style={{ height: '780px', display: 'flex', flexDirection: 'column', marginBottom: 0 }}>
          <div className="card-header" style={{ backgroundColor: isEditing ? '#eff6ff' : '#ffffff' }}>
            <div className="card-title">
              <Sparkles size={18} color="#2563eb" />
              <span>{isEditing ? 'Review & Correct Fields' : 'Structured Extracted Data'}</span>
            </div>

            {isEditing ? (
              <span className="badge badge-processing">Editing Mode</span>
            ) : (
              (doc.manual_corrections || extractedData.manually_corrected) && (
                <span className="badge badge-completed">Manually Verified</span>
              )
            )}
          </div>

          <div style={{ flex: 1, overflowY: 'auto' }}>
            {/* READ-ONLY VIEW MODE */}
            {!isEditing ? (
              <div>
                {/* 2-Column Compact Key-Value Grid */}
                <div className="kv-grid-compact">
                  {schemaFieldKeys.map((key) => {
                    const val = extractedData[key];
                    const confScore = fieldConfidenceMap[key];
                    const isValPresent = val !== null && val !== undefined && String(val).trim() !== '' && String(val).trim() !== '—';

                    return (
                      <div key={key} className={`kv-card-item ${!isValPresent ? 'missing' : ''}`}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                          <div className="kv-label-text">{formatFieldLabel(key)}</div>
                          {isValPresent && renderConfidenceBadge(confScore)}
                        </div>
                        <div className={`kv-value-text ${!isValPresent ? 'empty' : ''}`}>
                          {isValPresent ? String(val) : 'Not detected'}
                        </div>
                      </div>
                    );
                  })}
                </div>

                {/* Cargo Line Items Table */}
                {lineItems.length > 0 && (
                  <div style={{ borderTop: '1px solid #e2e8f0', marginTop: '0.5rem' }}>
                    <div style={{ padding: '1rem 1.5rem', backgroundColor: '#f8fafc', borderBottom: '1px solid #e2e8f0', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                      <ListFilter size={16} color="#2563eb" />
                      <h4 style={{ fontWeight: 700, fontSize: '0.9375rem', color: '#0f172a' }}>Cargo Line Items ({lineItems.length})</h4>
                    </div>
                    <div className="table-container">
                      <table className="data-table">
                        <thead>
                          <tr>
                            <th>Item</th>
                            <th>Description</th>
                            <th>Qty</th>
                            <th>Rate</th>
                            <th style={{ textAlign: 'right' }}>Amount</th>
                          </tr>
                        </thead>
                        <tbody>
                          {lineItems.map((item, idx) => (
                            <tr key={idx}>
                              <td style={{ fontWeight: 700 }}>{item.item_no || idx + 1}</td>
                              <td style={{ fontWeight: 600 }}>{item.description || '—'}</td>
                              <td>{item.quantity || '—'}</td>
                              <td>{item.rate || '—'}</td>
                              <td style={{ textAlign: 'right', fontWeight: 700 }}>{item.amount || '—'}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </div>
                )}

                {/* Collapsible OCR Details Debug Section */}
                <div style={{ padding: '1.25rem 1.5rem', borderTop: '1px solid #e2e8f0', backgroundColor: '#f8fafc' }}>
                  <button 
                    onClick={() => setShowOcrDebug(!showOcrDebug)}
                    style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: '0.875rem', fontWeight: 700, color: '#2563eb', display: 'flex', alignItems: 'center', gap: '0.5rem', padding: 0 }}
                  >
                    <Cpu size={16} />
                    <span>OCR Details & Debug Inspection</span>
                    {showOcrDebug ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
                  </button>

                  {showOcrDebug && (
                    <div style={{ marginTop: '1rem', backgroundColor: '#ffffff', border: '1px solid #e2e8f0', borderRadius: '0.5rem', padding: '1rem' }}>
                      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: '1rem', marginBottom: '1rem', fontSize: '0.8125rem' }}>
                        <div>
                          <span style={{ color: '#64748b', fontWeight: 600 }}>OCR Provider: </span>
                          <span style={{ fontWeight: 700 }}>{rawOcr.processor || "local-ocr-processor"}</span>
                        </div>
                        <div>
                          <span style={{ color: '#64748b', fontWeight: 600 }}>Page Count: </span>
                          <span style={{ fontWeight: 700 }}>{doc.page_count || 1}</span>
                        </div>
                        <div>
                          <span style={{ color: '#64748b', fontWeight: 600 }}>Extraction Confidence: </span>
                          <span style={{ fontWeight: 700 }}>{overallConf !== null ? `${(overallConf * 100).toFixed(1)}%` : '—'}</span>
                        </div>
                      </div>

                      {validationWarnings.length > 0 && (
                        <div style={{ marginBottom: '1rem', padding: '0.75rem', backgroundColor: '#fff7ed', borderRadius: '0.375rem', border: '1px solid #ffedd5' }}>
                          <div style={{ fontWeight: 700, fontSize: '0.75rem', color: '#c2410c', textTransform: 'uppercase', marginBottom: '0.25rem' }}>Validation Warnings</div>
                          <ul style={{ paddingLeft: '1.25rem', fontSize: '0.75rem', color: '#c2410c' }}>
                            {validationWarnings.map((w, idx) => (
                              <li key={idx}>{w}</li>
                            ))}
                          </ul>
                        </div>
                      )}

                      {rawText && (
                        <div>
                          <div style={{ fontSize: '0.75rem', fontWeight: 700, color: '#64748b', textTransform: 'uppercase', marginBottom: '0.375rem' }}>Raw OCR Text</div>
                          <pre className="mono" style={{ backgroundColor: '#0f172a', color: '#f8fafc', padding: '1rem', borderRadius: '0.5rem', maxHeight: '200px', overflowY: 'auto', fontSize: '0.75rem', whiteSpace: 'pre-wrap', lineHeight: 1.5 }}>
                            {rawText}
                          </pre>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              </div>
            ) : (
              /* EDITABLE REVIEW FORM MODE */
              <div style={{ padding: '1.5rem' }}>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '1.25rem', marginBottom: '1.5rem' }}>
                  {editableKeys.map(({ key, label, required, type }) => (
                    <div key={key}>
                      <label style={{ display: 'block', fontSize: '0.6875rem', fontWeight: 700, color: '#475569', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: '0.375rem' }}>
                        {label} {required && <span style={{ color: '#dc2626' }}>*</span>}
                      </label>
                      <input 
                        type={type || 'text'}
                        className="form-control"
                        value={editFormData[key] || ''}
                        onChange={(e) => handleFieldChange(key, e.target.value)}
                        placeholder={`Enter ${label}`}
                      />
                    </div>
                  ))}
                </div>

                {/* Editable Cargo Line Items */}
                <div style={{ borderTop: '1px solid #e2e8f0', paddingTop: '1.25rem', marginTop: '1.25rem' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
                    <h4 style={{ fontWeight: 700, fontSize: '0.9375rem', color: '#0f172a' }}>Cargo Line Items</h4>
                    <button className="btn btn-secondary" style={{ padding: '0.25rem 0.625rem', fontSize: '0.75rem' }} onClick={handleAddLineItem}>
                      <Plus size={14} />
                      <span>Add Item</span>
                    </button>
                  </div>

                  {(editFormData.line_items || []).map((item, idx) => (
                    <div key={idx} style={{ display: 'grid', gridTemplateColumns: '2fr 1fr 1fr 1fr 36px', gap: '0.5rem', alignItems: 'center', marginBottom: '0.75rem', padding: '0.75rem', backgroundColor: '#f8fafc', borderRadius: '0.5rem', border: '1px solid #e2e8f0' }}>
                      <input 
                        type="text" 
                        className="form-control"
                        placeholder="Description"
                        value={item.description || ''}
                        onChange={(e) => handleLineItemChange(idx, 'description', e.target.value)}
                        style={{ fontSize: '0.8125rem' }}
                      />
                      <input 
                        type="text" 
                        className="form-control"
                        placeholder="Qty"
                        value={item.quantity || ''}
                        onChange={(e) => handleLineItemChange(idx, 'quantity', e.target.value)}
                        style={{ fontSize: '0.8125rem' }}
                      />
                      <input 
                        type="text" 
                        className="form-control"
                        placeholder="Rate"
                        value={item.rate || ''}
                        onChange={(e) => handleLineItemChange(idx, 'rate', e.target.value)}
                        style={{ fontSize: '0.8125rem' }}
                      />
                      <input 
                        type="text" 
                        className="form-control"
                        placeholder="Amount"
                        value={item.amount || ''}
                        onChange={(e) => handleLineItemChange(idx, 'amount', e.target.value)}
                        style={{ fontSize: '0.8125rem' }}
                      />
                      <button 
                        onClick={() => handleRemoveLineItem(idx)}
                        style={{ background: 'none', border: 'none', color: '#dc2626', cursor: 'pointer', padding: '0.25rem', display: 'flex', alignItems: 'center', justifyContent: 'center' }}
                      >
                        <Trash2 size={16} />
                      </button>
                    </div>
                  ))}
                </div>

                {/* Form Action Footer */}
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
    </div>
  );
}
