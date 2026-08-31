"""Targeted cleanup script to safely remove ONLY persist_test_* documents from DB and storage."""

import sys
from pathlib import Path

BACKEND_DIR = Path(r"c:\Users\Prachi\OneDrive\Desktop\bill-ocr\backend")
sys.path.insert(0, str(BACKEND_DIR))

from dotenv import load_dotenv
load_dotenv(BACKEND_DIR / ".env")

import logging
from sqlalchemy import func
from app.db.database import SessionLocal
from app.db.models import Document

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("cleanup_persist_test")


def cleanup_persist_test_documents():
    db = SessionLocal()
    try:
        total_before = db.query(func.count(Document.id)).scalar()
        logger.info(f"Total documents in database BEFORE cleanup: {total_before}")

        # Query ONLY documents whose filename starts with 'persist_test_'
        persist_docs = db.query(Document).filter(
            (Document.original_filename.like("persist_test_%")) |
            (Document.stored_filename.like("persist_test_%"))
        ).all()

        logger.info(f"Found {len(persist_docs)} 'persist_test_*' document(s) targeted for deletion.")

        deleted_details = []

        for doc in persist_docs:
            doc_id = doc.id
            filename = doc.original_filename
            stored_path = doc.stored_path

            # Delete physical PDF file if present
            physical_deleted = False
            if stored_path:
                abs_path = BACKEND_DIR / stored_path
                if not abs_path.exists():
                    abs_path = BACKEND_DIR / "storage" / "documents" / Path(stored_path).name

                if abs_path.exists():
                    try:
                        abs_path.unlink()
                        physical_deleted = True
                    except Exception as e:
                        logger.warning(f"Could not delete physical file '{abs_path}': {e}")

            # Delete document database row
            db.delete(doc)

            deleted_details.append({
                "id": str(doc_id),
                "filename": filename,
                "stored_path": stored_path,
                "physical_deleted": physical_deleted
            })

        db.commit()

        total_after = db.query(func.count(Document.id)).scalar()
        logger.info(f"Total documents in database AFTER cleanup: {total_after}")

        # Verification check: Ensure 0 persist_test_% documents remain
        remaining_persist = db.query(func.count(Document.id)).filter(
            (Document.original_filename.like("persist_test_%")) |
            (Document.stored_filename.like("persist_test_%"))
        ).scalar()

        print("\n==========================================================================")
        print("           TARGETED PERSISTENCE TEST DOCUMENT CLEANUP REPORT             ")
        print("==========================================================================")
        print(f"Total Documents Before Cleanup: {total_before}")
        print(f"Total 'persist_test_*' Documents Deleted: {len(deleted_details)}")
        print(f"Total Documents Remaining in Database: {total_after}")
        print(f"Remaining 'persist_test_*' Documents in DB: {remaining_persist} (Must be 0)")
        print("-" * 74)
        print("EXACT LIST OF DELETED 'persist_test_*' DOCUMENTS:")
        for idx, item in enumerate(deleted_details, start=1):
            phys_str = "File Deleted" if item['physical_deleted'] else "No Physical File"
            print(f"  {idx:2d}. ID: {item['id']} | Filename: {item['filename']:<30} | {phys_str}")
        print("==========================================================================\n")

        return deleted_details, total_before, total_after

    finally:
        db.close()


if __name__ == "__main__":
    cleanup_persist_test_documents()

