import React, { useState } from 'react';
import { Upload, X, FileCheck, AlertCircle } from 'lucide-react';
import { uploadDocument } from '../api';

export default function UploadModal({ isOpen, onClose, onUploadSuccess }) {
  const [selectedFile, setSelectedFile] = useState(null);
  const [isUploading, setIsUploading] = useState(false);
  const [error, setError] = useState(null);

  if (!isOpen) return null;

  const handleFileChange = (e) => {
    if (e.target.files && e.target.files[0]) {
      const file = e.target.files[0];
      if (!file.name.toLowerCase().endsWith('.pdf')) {
        setError('Only PDF files (.pdf) are supported.');
        setSelectedFile(null);
        return;
      }
      setError(null);
      setSelectedFile(file);
    }
  };

  const handleDrop = (e) => {
    e.preventDefault();
    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      const file = e.dataTransfer.files[0];
      if (!file.name.toLowerCase().endsWith('.pdf')) {
        setError('Only PDF files (.pdf) are supported.');
        setSelectedFile(null);
        return;
      }
      setError(null);
      setSelectedFile(file);
    }
  };

  const handleUploadSubmit = async () => {
    if (!selectedFile) return;

    setIsUploading(true);
    setError(null);

    try {
      const result = await uploadDocument(selectedFile);
      setSelectedFile(null);
      setIsUploading(false);
      onUploadSuccess(result);
      onClose();
    } catch (err) {
      setIsUploading(false);
      setError(err.message || 'Failed to upload document.');
    }
  };

  return (
    <div className="modal-overlay">
      <div className="modal-card">
        <div className="modal-header">
          <h3 style={{ fontWeight: 600, fontSize: '1.125rem' }}>Upload Freight Bill PDF</h3>
          <button 
            onClick={onClose} 
            disabled={isUploading}
            style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#64748b' }}
          >
            <X size={20} />
          </button>
        </div>

        <div className="modal-body">
          {error && (
            <div className="alert alert-error" style={{ marginBottom: '1rem' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                <AlertCircle size={16} />
                <span>{error}</span>
              </div>
            </div>
          )}

          <div 
            className="dropzone"
            onDragOver={(e) => e.preventDefault()}
            onDrop={handleDrop}
          >
            <input 
              type="file" 
              accept=".pdf" 
              id="fileInput" 
              style={{ display: 'none' }} 
              onChange={handleFileChange}
            />
            <label htmlFor="fileInput" style={{ cursor: 'pointer', display: 'block' }}>
              <div className="state-icon" style={{ margin: '0 auto 1rem auto' }}>
                <Upload size={24} color="#2563eb" />
              </div>
              <p style={{ fontWeight: 600, marginBottom: '0.25rem' }}>
                {selectedFile ? selectedFile.name : 'Click to select or drag & drop PDF'}
              </p>
              <p style={{ fontSize: '0.8125rem', color: '#64748b' }}>
                {selectedFile 
                  ? `${(selectedFile.size / 1024).toFixed(1)} KB` 
                  : 'Supported formats: PDF documents'}
              </p>
            </label>
          </div>
        </div>

        <div style={{ padding: '1rem 1.5rem', borderTop: '1px solid #e2e8f0', display: 'flex', justifyContent: 'flex-end', gap: '0.75rem', backgroundColor: '#f8fafc' }}>
          <button className="btn btn-secondary" onClick={onClose} disabled={isUploading}>
            Cancel
          </button>
          <button 
            className="btn btn-primary" 
            onClick={handleUploadSubmit} 
            disabled={!selectedFile || isUploading}
          >
            {isUploading ? (
              <>
                <div className="spinner" />
                <span>Uploading...</span>
              </>
            ) : (
              <>
                <FileCheck size={16} />
                <span>Upload Document</span>
              </>
            )}
          </button>
        </div>
      </div>
    </div>
  );
}

