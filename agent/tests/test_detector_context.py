"""Tests de _get_exe y _get_uid (C09, task 11.5; D49/RN-143, tasks 5.1-5.2)."""
from __future__ import annotations

import os
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


def test_get_uid_returns_none_on_oserror() -> None:
    """D49/RN-143: OSError (proceso ya terminado) es atribución no resuelta, no root."""
    with patch("builtins.open", side_effect=OSError("permission denied")):
        result = _get_uid(99999)
    assert result is None
    assert result != 0  # explícito: None y 0 significan cosas distintas


def test_get_uid_parses_uid_from_proc_status() -> None:
    fake_status = "Name:\tpython\nUid:\t1000\t1000\t1000\t1000\n"
    from io import StringIO
    with patch("builtins.open", return_value=StringIO(fake_status)):
        result = _get_uid(12345)
    assert result == 1000


# ── D49/RN-143 (5.1-5.2): _get_uid contra /proc real, sin mockear open() ────


def test_get_uid_returns_none_for_nonexistent_pid() -> None:
    """5.1: un pid alto sin /proc/<pid> produce None, nunca 0 (D49/RN-143)."""
    candidate = 2**22  # por encima de pid_max típico (usualmente 2**22 en 64 bits)
    while os.path.exists(f"/proc/{candidate}"):
        candidate -= 1
        assert candidate > 0, "no se encontró un pid libre para el test"
    result = _get_uid(candidate)
    assert result is None
    assert result != 0  # aserción negativa explícita: la intención no es "root"


def test_get_uid_returns_real_uid_for_current_process() -> None:
    """5.2: sobre el propio proceso, _get_uid resuelve el uid real — sin esto,
    5.1 pasaría también con una función que siempre retorna None."""
    assert _get_uid(os.getpid()) == os.getuid()
