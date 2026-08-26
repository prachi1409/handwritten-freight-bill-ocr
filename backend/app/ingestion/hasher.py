"""File hashing utility using SHA-256 with chunked streaming."""

import hashlib
import logging
from pathlib import Path
from typing import Union

logger = logging.getLogger(__name__)

DEFAULT_CHUNK_SIZE = 65536  # 64 KB chunks


def calculate_file_hash(file_path: Union[str, Path], chunk_size: int = DEFAULT_CHUNK_SIZE) -> str:
    """Calculate the SHA-256 hash of a file by streaming it in chunks.

    Args:
        file_path: Path to the target file.
        chunk_size: Size of read chunks in bytes (default 64KB).

    Returns:
        Hexadecimal SHA-256 hash string.

    Raises:
        FileNotFoundError: If the specified file does not exist.
        IsADirectoryError: If the specified path is a directory.
        IOError: If an error occurs while reading the file.
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"File not found for hashing: {path}")
    if not path.is_file():
        raise IsADirectoryError(f"Path is not a regular file: {path}")

    hasher = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            while chunk := f.read(chunk_size):
                hasher.update(chunk)

        file_hash = hasher.hexdigest()
        logger.debug(f"Calculated SHA-256 hash for '{path.name}': {file_hash}")
        return file_hash
    except Exception as e:
        logger.error(f"Error calculating hash for '{path}': {e}")
        raise

