"""Tests for 'webfocus_extraction.discovery.bundle_scanner'."""

import hashlib

import pytest

from webfocus_extraction.discovery.bundle_scanner import decode_text, scan_bundle


def test_scan_bundle_describes_files_in_sorted_order_and_skips_hidden(tmp_path):
    """Files are numbered in path order with IBFS paths, kinds, roots, and hashes."""
    report = tmp_path / "WFC" / "Repository" / "rpt_a.fex"
    flat_file = tmp_path / "EDA" / "EDASERVE" / "ff_b.txt"
    for path in (report, flat_file):
        path.parent.mkdir(parents=True)
    report.write_bytes(b"TABLE FILE X\r\nEND\r\n")
    flat_file.write_text("1\n2\n")
    (tmp_path / "WFC" / ".DS_Store").write_bytes(b"\x00")

    files = list(scan_bundle(tmp_path))

    assert [(f.file_id, f.ibfs_path, f.source_root, f.file_kind) for f in files] == [
        (1, "IBFS:/EDA/EDASERVE/ff_b.txt", "EDA", "flat_file"),
        (2, "IBFS:/WFC/Repository/rpt_a.fex", "WFC", "procedure"),
    ]
    assert files[1].line_count == 2
    assert files[1].sha256 == hashlib.sha256(b"TABLE FILE X\r\nEND\r\n").hexdigest()


def test_scan_bundle_rejects_missing_root(tmp_path):
    """A missing bundle root raises FileNotFoundError."""
    with pytest.raises(FileNotFoundError):
        list(scan_bundle(tmp_path / "missing"))


def test_decode_text_falls_back_to_cp1252():
    """Bytes that are not UTF-8 decode as cp1252."""
    assert decode_text("caf\u00e9".encode("cp1252")) == ("caf\u00e9", "cp1252")
