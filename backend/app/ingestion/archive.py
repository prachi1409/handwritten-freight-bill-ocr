"""Move processed inbox PDFs into the configured processed_documents folder."""

import logging
import shutil
from pathlib import Path
from typing import Optional

from app.core.config import settings

logger = logging.getLogger(__name__)


def _is_under(path: Path, directory: Path) -> bool:
    """Return True if path is the directory itself or a file inside it."""
    try:
        path.resolve().relative_to(directory.resolve())
        return True
    except ValueError:
        return False


def archive_inbox_file(source: Path, dest_name: Optional[str] = None) -> Optional[Path]:
    """Move a PDF out of input_doc_location into processed_documents.

    Files that are not in the configured inbox are left in place (e.g. unit-test temp dirs).
    Returns the destination path, the original path if already archived, or None if missing.
    """
    source = Path(source)
    if not source.exists() or not source.is_file():
        logger.warning("Cannot archive missing file: '%s'", source)
        return None

    input_dir = settings.input_path
    processed_dir = settings.processed_path
    processed_dir.mkdir(parents=True, exist_ok=True)

    if _is_under(source, processed_dir):
        return source

    if not _is_under(source, input_dir):
        return source

    dest = processed_dir / (dest_name or source.name)
    if dest.exists():
        dest = processed_dir / f"{source.stem}_{source.stat().st_size}{source.suffix}"
        if dest.exists():
            dest = processed_dir / f"{source.stem}_{source.stat().st_mtime_ns}{source.suffix}"

    shutil.move(str(source), str(dest))
    logger.info("Archived '%s' -> '%s'", source.name, dest)
    return dest
