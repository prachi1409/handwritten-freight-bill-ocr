"""CLI command script to trigger freight bill document ingestion manually."""

import sys
import logging
from app.db.database import SessionLocal, init_db
from app.services.document_service import DocumentService

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def main():
    input_dir = sys.argv[1] if len(sys.argv) > 1 else None

    logger.info("Initializing database tables...")
    try:
        init_db()
    except Exception as e:
        logger.error(f"Database error during CLI execution: {e}")
        sys.exit(1)

    db = SessionLocal()
    try:
        logger.info("Starting ingestion batch...")
        result = DocumentService.ingest_documents(db, input_dir=input_dir)
        print("\n--- INGESTION SUMMARY ---")
        print(f"Total Scanned : {result.total_scanned}")
        print(f"Ingested      : {result.ingested_count}")
        print(f"Duplicates    : {result.duplicate_count}")
        print(f"Invalid       : {result.invalid_count}")
        print(f"Failed        : {result.failed_count}")
        print("-------------------------")
        for item in result.items:
            print(f"[{item.status}] {item.filename} -> {item.message}")
    finally:
        db.close()


if __name__ == "__main__":
    main()

