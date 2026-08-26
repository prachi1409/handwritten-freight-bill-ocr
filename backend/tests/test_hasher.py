"""Unit tests for SHA-256 file hashing utility."""

import pytest
from app.ingestion.hasher import calculate_file_hash


def test_hashing_identical_files_produce_same_hash(tmp_path):
    """Verify two files with identical contents yield the same SHA-256 hash."""
    file1 = tmp_path / "bill_001.pdf"
    file2 = tmp_path / "bill_copy.pdf"

    content = b"FREIGHT BILL CONTENT 12345"
    file1.write_bytes(content)
    file2.write_bytes(content)

    hash1 = calculate_file_hash(file1)
    hash2 = calculate_file_hash(file2)

    assert hash1 == hash2
    assert len(hash1) == 64  # SHA-256 hex string length


def test_hashing_different_files_produce_different_hashes(tmp_path):
    """Verify different files yield different SHA-256 hashes."""
    file1 = tmp_path / "bill_001.pdf"
    file2 = tmp_path / "bill_002.pdf"

    file1.write_bytes(b"FREIGHT BILL CONTENT 12345")
    file2.write_bytes(b"FREIGHT BILL CONTENT 99999")

    hash1 = calculate_file_hash(file1)
    hash2 = calculate_file_hash(file2)

    assert hash1 != hash2


def test_chunked_hashing_matches_full_read(tmp_path):
    """Verify chunked reading produces identical result to standard hashlib calculation."""
    import hashlib
    file_path = tmp_path / "large_mock_bill.dat"
    content = b"A" * 100000  # 100 KB mock file content
    file_path.write_bytes(content)

    expected_hash = hashlib.sha256(content).hexdigest()
    calculated_hash = calculate_file_hash(file_path, chunk_size=1024)

    assert calculated_hash == expected_hash


def test_hashing_nonexistent_file_raises_error(tmp_path):
    """Verify FileNotFoundError raised for missing file."""
    missing_file = tmp_path / "does_not_exist.pdf"
    with pytest.raises(FileNotFoundError):
        calculate_file_hash(missing_file)


def test_hashing_directory_raises_error(tmp_path):
    """Verify IsADirectoryError raised when passing a directory."""
    with pytest.raises(IsADirectoryError):
        calculate_file_hash(tmp_path)

