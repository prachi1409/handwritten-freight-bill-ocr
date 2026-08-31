"""Script to drop and recreate PostgreSQL database tables with updated Document schema.
Requires RESET_DATABASE=true environment variable to prevent unintended data loss.
"""

import os
import sys
import logging
from sqlalchemy import text
from app.db.database import engine, Base
from app.db.models import Document

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def reset_database(force: bool = False):
    if not force and os.environ.get("RESET_DATABASE", "").lower() not in ("true", "1", "yes"):
        logger.warning("SAFETY CHECK TRIGGERED: Destructive database reset blocked.")
        logger.warning("Set RESET_DATABASE=true environment variable to confirm database reset.")
        sys.exit(1)

    logger.info("Resetting PostgreSQL database schema...")
    with engine.begin() as conn:
        logger.info("Dropping existing 'documents' table...")
        conn.execute(text("DROP TABLE IF EXISTS documents CASCADE;"))

    logger.info("Creating fresh 'documents' table...")
    Base.metadata.create_all(bind=engine)
    logger.info("Database schema reset successfully!")


if __name__ == "__main__":
    reset_database(force=False)
