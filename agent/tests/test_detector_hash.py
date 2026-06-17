"""Tests de _hash_file (C09, task 11.1)."""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from agent.detector import _hash_file


def test_hash_file_returns_sha256_hex(tmp_path: Path) -> None:
    content = b"hello world"
    f = tmp_path / "test.txt"
    f.write_bytes(content)
    result = _hash_file(str(f))
    assert result == hashlib.sha256(content).hexdigest()


def test_hash_file_returns_none_when_missing(tmp_path: Path) -> None:
    result = _hash_file(str(tmp_path / "nonexistent.txt"))
    assert result is None


def test_hash_file_empty_file(tmp_path: Path) -> None:
    f = tmp_path / "empty.txt"
    f.write_bytes(b"")
    result = _hash_file(str(f))
    assert result == hashlib.sha256(b"").hexdigest()
