"""destino_virgen (lab/lib_arnes.sh) refuses to write into a sealed evidence package (P-9)."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

LIB = Path(__file__).parents[2] / "lab" / "lib_arnes.sh"


def _find_bash() -> str | None:
    """Git Bash on Windows, never C:\\Windows\\System32\\bash.exe (the WSL launcher)."""
    if os.environ.get("BASH_FOR_TESTS"):
        return os.environ["BASH_FOR_TESTS"]
    if os.name != "nt":
        return shutil.which("bash")
    git = shutil.which("git")
    if git:
        for root in Path(git).resolve().parents[:3]:
            for candidate in (root / "bin" / "bash.exe", root / "usr" / "bin" / "bash.exe"):
                if candidate.exists():
                    return str(candidate)
    return None


BASH = _find_bash()
pytestmark = pytest.mark.skipif(BASH is None, reason="bash (Git Bash on Windows) is required")


def _run(script: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([BASH, "-c", script, "_", LIB.as_posix(), *args],
                          capture_output=True, text=True, timeout=60)


def destino_virgen(target: Path) -> subprocess.CompletedProcess:
    return _run('source "$1"; destino_virgen "$2"', target.as_posix())


@pytest.fixture
def sealed(tmp_path: Path) -> Path:
    package = tmp_path / "oficial-cap5-20260917T223823Z"
    (package / "suites").mkdir(parents=True)
    (package / "SHA256SUMS").write_text("")
    return package


def test_sealed_package_is_refused(sealed: Path) -> None:
    result = destino_virgen(sealed)
    assert result.returncode == 1
    assert "destino ya sellado" in result.stderr


def test_subdirectory_of_a_sealed_package_is_refused(sealed: Path) -> None:
    # The original defect: suites/ has no manifest of its own; the package does.
    assert destino_virgen(sealed / "suites").returncode == 1


def test_new_directory_is_allowed(tmp_path: Path) -> None:
    assert destino_virgen(tmp_path / "v6-eval-20261101T000000Z" / "suites").returncode == 0


def test_missing_argument_is_refused() -> None:
    result = _run('source "$1"; destino_virgen ""')
    assert result.returncode == 1
