# Handwritten Freight Bill OCR

Python + React + PostgreSQL app that reads freight bills (PDF or scan images), extracts fields as JSON, and lets an operator review them. There is no login.

## What it does

1. Picks files from `input_doc_location` (or upload in the UI).
2. Validates, hashes, and skips duplicates.
3. Preprocesses pages (DPI, deskew, contrast).
4. Runs OCR (local by default; Google Document AI when billing and credentials are set).
5. Classifies the document, reconstructs text-block layout, extracts freight fields, then **COMPLETED** vs **REVIEW**.
6. Stores JSON in Postgres and moves finished PDFs to `processed_documents`.

## Run locally

**Backend** (from `backend/`):

```powershell
copy .env.example .env
# set DATABASE_URL (local Postgres or Supabase: postgresql+psycopg://...?sslmode=require)
python -m pip install -r requirements.txt
python -m app.main
```

API: http://127.0.0.1:8000  
Docs: http://127.0.0.1:8000/docs  
Health: http://127.0.0.1:8000/health

**Frontend** (from `frontend/`):

```powershell
npm install
npm run dev
```

UI: http://127.0.0.1:3000

## OCR providers

| `OCR_PROVIDER` | When to use |
|---|---|
| `local` | Default for development. Text PDFs use the PDF text layer. Messy scans use **PaddleOCR**, then an optional **Ollama** model to map text → JSON. Regex is the fallback if Ollama is down. |
| `document_ai` | Needs project ID, processor ID, service-account JSON, **and GCP billing**. |

### Messy / handwritten scans (local)

```powershell
cd backend
python -m pip install paddleocr numpy
```

Install [Ollama](https://ollama.com), then:

```powershell
ollama pull llama3.1
```

In `backend/.env`:

```
ENABLE_PADDLE_OCR=true
ENABLE_OLLAMA=true
OLLAMA_BASE_URL=http://127.0.0.1:11434
OLLAMA_MODEL=llama3.1
```

Restart the backend. Reprocess a messy PDF. Logs should show `PaddleOCR` and either `ollama + regex fallback` or `regex` if Ollama is not running.

If PaddleOCR text is still empty, a vision model in Ollama (`qwen2-vl`) is the next local step; Document AI is still the strongest option once billing is on.

Document AI credentials path is relative to `backend/`, e.g. `./credentials/your-key.json`.

## Folders

- `INPUT_DOC_LOCATION` — inbox. Drop PDF, JPG, PNG, or TIFF. Click **Scan Folder**.
- `PROCESSED_DOCUMENTS_LOCATION` — files are moved here after OCR.

## Pipeline (foundation)

Ingestion → document intelligence (type / quality) → image preprocessing → OCR → layout blocks → field extraction → validation (PASS / REVIEW) → persist JSON → UI / API.

Side-by-side review and correction is on the document detail page.

## Tests

```powershell
cd backend
python -m pytest -q
```
