"""Tests de _get_exe y _get_uid (C09, task 11.5)."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from agent.detector import _get_exe, _get_uid


def test_get_exe_returns_none_on_oserror() -> None:
    with patch("os.readlink", side_effect=OSError("no such file")):
        result = _get_exe(99999)
    assert result is None


def test_get_exe_returns_path_on_success() -> None:
    with patch("os.readlink", return_value="/usr/bin/python3"):
        result = _get_exe(12345)
    assert result == "/usr/bin/python3"


def test_get_uid_returns_zero_on_oserror() -> None:
    with patch("builtins.open", side_effect=OSError("permission denied")):
        result = _get_uid(99999)
    assert result == 0


def test_get_uid_parses_uid_from_proc_status() -> None:
    fake_status = "Name:\tpython\nUid:\t1000\t1000\t1000\t1000\n"
    from io import StringIO
    with patch("builtins.open", return_value=StringIO(fake_status)):
        result = _get_uid(12345)
    assert result == 1000
