import React from 'react';
import { CheckCircle2, Clock, Loader2, AlertTriangle, HelpCircle } from 'lucide-react';

export default function StatusBadge({ status }) {
  const normalized = (status || 'PENDING').toUpperCase();

  switch (normalized) {
    case 'COMPLETED':
      return (
        <span className="badge badge-completed">
          <CheckCircle2 size={12} />
          <span>Completed</span>
        </span>
      );
    case 'PENDING':
      return (
        <span className="badge badge-pending">
          <Clock size={12} />
          <span>Pending</span>
        </span>
      );
    case 'PROCESSING':
      return (
        <span className="badge badge-processing">
          <Loader2 size={12} className="spinner-icon" />
          <span>Processing</span>
        </span>
      );
    case 'FAILED':
      return (
        <span className="badge badge-failed">
          <AlertTriangle size={12} />
          <span>Failed</span>
        </span>
      );
    case 'REVIEW':
      return (
        <span className="badge badge-review">
          <HelpCircle size={12} />
          <span>Review Needed</span>
        </span>
      );
    default:
      return (
        <span className="badge badge-pending">
          <Clock size={12} />
          <span>{status}</span>
        </span>
      );
  }
}

