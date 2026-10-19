"""The provenance guard compares the backend container against the tag, with LC_ALL=C (N-5)."""

from __future__ import annotations

import os
import shutil
import io
import subprocess
import tarfile
from pathlib import Path

import pytest

REPO = Path(__file__).parents[2]
LIB = REPO / "lab" / "lib_arnes.sh"
TAG = "v5.1-tesis"
HUELLA_C = "981dc0f3fef006afb842c5d9ff38a66af37452547abc66e39ef6ee9578597325"  # Anexo L.1


def _find_bash() -> str | None:
    """Git Bash on Windows, never the WSL launcher in System32."""
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
HAS_TAG = subprocess.run(["git", "-C", str(REPO), "rev-parse", "-q", "--verify", f"refs/tags/{TAG}"],
                         capture_output=True).returncode == 0
pytestmark = pytest.mark.skipif(BASH is None or not HAS_TAG, reason=f"bash and the tag {TAG} are required")


def _bash(script: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([BASH, "-c", script, "_", LIB.as_posix(), REPO.as_posix(), *args],
                          capture_output=True, text=True, timeout=120)


@pytest.fixture
def fake_container(tmp_path: Path) -> Path:
    """backend/app of the tag, extracted where a fake `docker compose exec` will look for /app."""
    data = subprocess.run(["git", "-C", str(REPO), "-c", "core.autocrlf=false", "archive", TAG, "backend/app"],
                          capture_output=True, check=True).stdout
    with tarfile.open(fileobj=io.BytesIO(data)) as tar:
        try:
            tar.extractall(tmp_path, filter="data")
        except TypeError:  # Python without extraction filters
            tar.extractall(tmp_path)
    return tmp_path / "backend"


# DC is replaced by a function that runs the container command against a local copy.
CONTAINER = ('source "$1"; REPO="$2"; APP="$3"; '
             'fake_dc() { shift 3; local s="$3"; sh -c "${s//cd \\/app/cd \\"$APP\\"}"; }; '
             'DC=(fake_dc); huella_backend_contenedor')


def test_tag_fingerprint_uses_c_collation() -> None:
    result = _bash('source "$1"; REPO="$2"; huella_backend_etiqueta "$3"', TAG)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == HUELLA_C


def test_container_built_from_the_tag_matches(fake_container: Path) -> None:
    result = _bash(CONTAINER, fake_container.as_posix())
    assert result.stdout.strip() == HUELLA_C


def test_modified_container_does_not_match(fake_container: Path) -> None:
    with open(fake_container / "app" / "main.py", "a", encoding="utf-8") as fh:
        fh.write("# modified after the tag\n")
    result = _bash(CONTAINER, fake_container.as_posix())
    assert result.stdout.strip() not in ("", HUELLA_C)
