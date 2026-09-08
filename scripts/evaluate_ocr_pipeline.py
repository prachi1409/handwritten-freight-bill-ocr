"""Run the current OCR pipeline against a labelled gold set. Evaluation only."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from dotenv import load_dotenv

load_dotenv(BACKEND / ".env")

from app.core.config import settings

# Evaluation should use the same production processor, not the pytest Local-only factory.
settings.TESTING = False

from app.ocr.evaluation import main


if __name__ == "__main__":
    raise SystemExit(main())
