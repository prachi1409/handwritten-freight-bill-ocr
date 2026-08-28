/**
 * API client helper for Handwritten Freight Bill OCR backend.
 */

const API_BASE_URL = 'http://127.0.0.1:8000/api/v1';

/**
 * Handle HTTP response and parse JSON or throw meaningful error.
 */
async function handleResponse(response) {
  if (!response.ok) {
    let errorMsg = `HTTP Error ${response.status}`;
    try {
      const errData = await response.json();
      errorMsg = errData.detail || errData.message || errorMsg;
    } catch {
      // Ignore JSON parse errors for non-JSON response bodies
    }
    throw new Error(errorMsg);
  }
  return response.json();
}

/**
 * Fetch all ingested documents.
 */
export async function fetchDocuments(query = '') {
  const params = new URLSearchParams();
  if (query && query.trim()) {
    params.set('q', query.trim());
  }
  const suffix = params.toString() ? `?${params.toString()}` : '';
  const response = await fetch(`${API_BASE_URL}/documents${suffix}`);
  return handleResponse(response);
}

/**
 * Fetch status count statistics (Total, Completed, Review Needed, Pending, Failed).
 */
export async function fetchDocumentStats() {
  const response = await fetch(`${API_BASE_URL}/documents/stats`);
  return handleResponse(response);
}

/**
 * Fetch single document by ID.
 */
export async function fetchDocumentById(id) {
  const response = await fetch(`${API_BASE_URL}/documents/${id}`);
  return handleResponse(response);
}

/**
 * Upload a freight bill PDF document file.
 */
export async function uploadDocument(file) {
  const formData = new FormData();
  formData.append('file', file);

  let response;
  try {
    response = await fetch(`${API_BASE_URL}/documents/upload`, {
      method: 'POST',
      body: formData,
    });
  } catch (err) {
    throw new Error(
      'Cannot reach the API at http://127.0.0.1:8000. Make sure the backend is running (python -m app.main).'
    );
  }
  return handleResponse(response);
}

/**
 * Trigger directory scan on input_doc_location folder.
 */
export async function scanDocuments() {
  const response = await fetch(`${API_BASE_URL}/documents/scan`, {
    method: 'POST',
  });
  return handleResponse(response);
}

/**
 * Reprocess document by ID.
 */
export async function reprocessDocument(id) {
  const response = await fetch(`${API_BASE_URL}/documents/${id}/reprocess`, {
    method: 'POST',
  });
  return handleResponse(response);
}

/**
 * Submit manual review corrections for a document.
 */
export async function submitDocumentReview(id, extractedData) {
  const response = await fetch(`${API_BASE_URL}/documents/${id}/review`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ extracted_data: extractedData }),
  });
  return handleResponse(response);
}

/**
 * Get direct file URL for viewing PDF.
 */
export function getDocumentFileUrl(id) {
  return `${API_BASE_URL}/documents/${id}/file`;
}
