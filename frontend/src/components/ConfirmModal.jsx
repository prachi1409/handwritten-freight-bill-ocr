import React, { useEffect } from 'react';
import { AlertTriangle, X } from 'lucide-react';

export default function ConfirmModal({
  isOpen,
  title,
  description,
  confirmLabel = 'Confirm',
  cancelLabel = 'Cancel',
  busyLabel = 'Working…',
  danger = false,
  isBusy = false,
  onConfirm,
  onCancel,
}) {
  useEffect(() => {
    if (!isOpen) return undefined;
    const onKeyDown = (event) => {
      if (event.key === 'Escape' && !isBusy) onCancel();
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [isOpen, isBusy, onCancel]);

  if (!isOpen) return null;

  return (
    <div
      className="modal-overlay"
      onClick={() => {
        if (!isBusy) onCancel();
      }}
    >
      <div
        className="modal-card modal-card-sm"
        role="dialog"
        aria-modal="true"
        aria-labelledby="confirm-modal-title"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="modal-header">
          <h3 id="confirm-modal-title" className="modal-title">{title}</h3>
          <button
            type="button"
            className="modal-close"
            onClick={onCancel}
            disabled={isBusy}
            aria-label="Close"
          >
            <X size={18} />
          </button>
        </div>

        <div className="modal-body">
          <div className={`confirm-callout ${danger ? 'danger' : ''}`}>
            <AlertTriangle size={18} />
            <p>{description}</p>
          </div>
        </div>

        <div className="modal-footer">
          <button type="button" className="btn btn-secondary" onClick={onCancel} disabled={isBusy}>
            {cancelLabel}
          </button>
          <button
            type="button"
            className={danger ? 'btn btn-danger-solid' : 'btn btn-primary'}
            onClick={onConfirm}
            disabled={isBusy}
          >
            {isBusy ? <div className="spinner" /> : null}
            <span>{isBusy ? busyLabel : confirmLabel}</span>
          </button>
        </div>
      </div>
    </div>
  );
}
