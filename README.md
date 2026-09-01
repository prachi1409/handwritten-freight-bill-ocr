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
| `local` | Default. RapidOCR reads the page; **Groq** maps English/Spanish OCR text to JSON. Regex is the fallback if Groq is off. |
| `document_ai` | Needs project ID, processor ID, service-account JSON, **and GCP billing**. |

### Spanish / English bills (Groq)

1. Create a key at https://console.groq.com/keys  
2. In `backend/.env`:

```
ENABLE_GROQ=true
GROQ_API_KEY=gsk_...
GROQ_MODEL=openai/gpt-oss-20b
```

3. Restart the backend and reprocess. Logs should show `Groq + regex/spatial fallback`.

Groq still needs OCR text. If RapidOCR returns empty, Groq cannot fill fields. It helps Spanish/English **labels**; it is not a vision model.

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
