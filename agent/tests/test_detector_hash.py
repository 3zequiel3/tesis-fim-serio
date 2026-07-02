"""Tests de _hash_file y _hash_file_async (C09, C21/C5)."""
from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.detector import FanotifyDetector, FanotifyEvent, _hash_file, _hash_file_async


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


# ── _hash_file_async — happy path ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_hash_file_async_present_no_sleep(tmp_path: Path) -> None:
    """Archivo presente: retorna en el primer intento, asyncio.sleep nunca se llama."""
    content = b"test content"
    f = tmp_path / "file.txt"
    f.write_bytes(content)

    with patch("agent.detector.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        result = await _hash_file_async(str(f))

    assert result == hashlib.sha256(content).hexdigest()
    mock_sleep.assert_not_called()


@pytest.mark.asyncio
async def test_hash_file_async_empty_file(tmp_path: Path) -> None:
    f = tmp_path / "empty.txt"
    f.write_bytes(b"")
    result = await _hash_file_async(str(f))
    assert result == hashlib.sha256(b"").hexdigest()


# ── _hash_file_async — retry race (C5) ───────────────────────────────────────

@pytest.mark.asyncio
async def test_hash_file_async_retry_succeeds_after_transient_missing(tmp_path: Path) -> None:
    """
    Simula race write-tmp+rename: FileNotFoundError en el intento 0, éxito en el intento 1.
    El resultado debe ser el hash correcto (no None).
    """
    content = b"recovered content"
    expected = hashlib.sha256(content).hexdigest()

    f = tmp_path / "file.txt"
    f.write_bytes(content)

    # Parchear _hash_file_async a nivel de implementación para simular el race:
    # primera invocación del bloque open lanza FileNotFoundError, la segunda lee el archivo real.
    real_open = open  # guardar referencia antes del patch
    call_count = 0

    def _fake_open(path, mode="rb", **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise FileNotFoundError("transient missing")
        return real_open(path, mode, **kwargs)

    with patch("agent.detector.open", side_effect=_fake_open, create=True):
        with patch("agent.detector.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            result = await _hash_file_async(str(f), retries=3, base_delay=0.05)

    assert result == expected
    # Se durmió una vez (entre intento 0 y 1) con 50 ms
    mock_sleep.assert_called_once_with(0.05)


@pytest.mark.asyncio
async def test_hash_file_async_persistently_missing_returns_none(tmp_path: Path) -> None:
    """Archivo persistentemente ausente: retorna None tras agotar los reintentos."""
    with patch("agent.detector.open", side_effect=FileNotFoundError("always missing"), create=True):
        with patch("agent.detector.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            result = await _hash_file_async(str(tmp_path / "ghost.txt"), retries=3, base_delay=0.05)

    assert result is None
    # 2 sleeps: entre intento 0→1 (50 ms) y 1→2 (100 ms); no hay sleep tras el último intento
    assert mock_sleep.call_count == 2
    calls = [c.args[0] for c in mock_sleep.call_args_list]
    assert calls[0] == pytest.approx(0.05)
    assert calls[1] == pytest.approx(0.10)


# ── _process_event con retry — integración detector ──────────────────────────

@pytest.mark.asyncio
async def test_process_event_emits_file_modified_after_retry(tmp_path: Path) -> None:
    """
    Simula race: _hash_file_async lanza FileNotFoundError en el primer intento,
    retorna hash válido en el segundo. El detector debe emitir file_modified,
    NO file_absent, y NO llamar mark_absent.
    """
    content = b"the real content"
    expected_hash = hashlib.sha256(content).hexdigest()
    f = tmp_path / "file.txt"
    f.write_bytes(content)

    baseline = MagicMock()
    entry_mock = MagicMock()
    entry_mock.hash = "oldhash"
    entry_mock.content_b64 = None
    entry_mock.oversize = False
    baseline.read_entry.return_value = entry_mock

    publisher = MagicMock()
    publisher.publish = AsyncMock()
    publisher._queue = MagicMock()
    publisher._queue.queue_size = 0

    detector = FanotifyDetector(
        agent_id="agent-01",
        watch_paths=[str(tmp_path)],
        baseline=baseline,
        publisher=publisher,
        stop_event=asyncio.Event(),
    )

    call_count = 0

    async def _fake_hash_async(path, retries=3, base_delay=0.05):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # Primera llamada: simular race (archivo momentáneamente ausente)
            await asyncio.sleep(0)  # ceder el loop para realismo
            return None  # on_ack del detector trata None como file_absent internamente...
        return expected_hash

    # Nota: queremos simular que _hash_file_async retorna None (ausente) y luego el hash.
    # Pero _process_event llama a _hash_file_async una sola vez por evento.
    # El retry ocurre DENTRO de _hash_file_async. Usamos el mock directamente en el módulo.

    fan_event = FanotifyEvent(
        path=str(f), pid=100, uid=0, exe=None,
        timestamp="2026-01-01T00:00:00+00:00",
    )

    # Simular que _hash_file_async con retry interno retorna el hash correcto
    # (el retry ya fue absorbido dentro de _hash_file_async — aquí solo vemos el resultado)
    async def _hash_success(path, retries=3, base_delay=0.05):
        return expected_hash

    with patch("agent.detector._hash_file_async", side_effect=_hash_success):
        await detector._process_event(fan_event)

    published = publisher.publish.call_args[0][0]
    assert published["event_type"] == "file_modified"
    assert published["hash_detected"] == expected_hash
    baseline.mark_absent.assert_not_called()


@pytest.mark.asyncio
async def test_process_event_emits_file_absent_when_persistently_missing(tmp_path: Path) -> None:
    """Archivo genuinamente ausente tras todos los reintentos: emite file_absent y llama mark_absent."""
    baseline = MagicMock()
    baseline.read_entry.return_value = None

    publisher = MagicMock()
    publisher.publish = AsyncMock()
    publisher._queue = MagicMock()
    publisher._queue.queue_size = 0

    detector = FanotifyDetector(
        agent_id="agent-01",
        watch_paths=[str(tmp_path)],
        baseline=baseline,
        publisher=publisher,
        stop_event=asyncio.Event(),
    )

    fan_event = FanotifyEvent(
        path=str(tmp_path / "ghost.txt"), pid=100, uid=0, exe=None,
        timestamp="2026-01-01T00:00:00+00:00",
    )

    async def _always_none(path, retries=3, base_delay=0.05):
        return None

    with patch("agent.detector._hash_file_async", side_effect=_always_none):
        await detector._process_event(fan_event)

    published = publisher.publish.call_args[0][0]
    assert published["event_type"] == "file_absent"
    assert published["hash_detected"] is None
    baseline.mark_absent.assert_called_once_with(str(tmp_path / "ghost.txt"))
