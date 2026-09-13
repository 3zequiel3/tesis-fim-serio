"""Tests de agent/preflight.py (D36/RN-130, D-3/D-4/D-12 del design).

Puros, sin root ni filesystem real: los tres probes (statvfs_fn, access_fn,
exists_fn) van inyectados, así que ningún test toca el filesystem de verdad.
Cubre los cuatro estados del vocabulario cerrado (RN-71), la precedencia
normativa read_only_mount > permission_denied, y PreflightRegistry como
estado explícito (no variable de módulo).
"""
from __future__ import annotations

import os
from types import SimpleNamespace

from agent.preflight import (
    MISSING,
    PERMISSION_DENIED,
    READ_ONLY_MOUNT,
    WRITABLE,
    PreflightRegistry,
    classify_path_writability,
    run_preflight,
)


def _statvfs(read_only: bool):
    flag = os.ST_RDONLY if read_only else 0
    return lambda path: SimpleNamespace(f_flag=flag)


# ── classify_path_writability: los cuatro estados ────────────────────────────


def test_writable_path() -> None:
    result = classify_path_writability(
        "/fake/etc",
        statvfs_fn=_statvfs(read_only=False),
        access_fn=lambda p, mode: True,
        exists_fn=lambda p: True,
    )
    assert result == WRITABLE


def test_read_only_mount() -> None:
    result = classify_path_writability(
        "/fake/usr/bin",
        statvfs_fn=_statvfs(read_only=True),
        access_fn=lambda p, mode: False,
        exists_fn=lambda p: True,
    )
    assert result == READ_ONLY_MOUNT


def test_permission_denied() -> None:
    result = classify_path_writability(
        "/fake/etc",
        statvfs_fn=_statvfs(read_only=False),
        access_fn=lambda p, mode: False,
        exists_fn=lambda p: True,
    )
    assert result == PERMISSION_DENIED


def test_missing_path() -> None:
    result = classify_path_writability(
        "/fake/does/not/exist",
        statvfs_fn=_statvfs(read_only=False),
        access_fn=lambda p, mode: True,
        exists_fn=lambda p: False,
    )
    assert result == MISSING


# ── precedencia normativa (D-3): read_only_mount antes que permission_denied ─


def test_read_only_mount_takes_precedence_over_permission_denied() -> None:
    """Un mount de solo lectura también hace fallar access(W_OK); la causa
    útil para el operador es la del mount, no la de permisos (D-3)."""
    result = classify_path_writability(
        "/fake/usr/bin",
        statvfs_fn=_statvfs(read_only=True),
        access_fn=lambda p, mode: False,  # también falla, pero no debe ganar
        exists_fn=lambda p: True,
    )
    assert result == READ_ONLY_MOUNT


# ── watch_path que nombra un archivo: se evalúa el directorio padre ──────────


def test_file_path_evaluates_parent_directory(tmp_path) -> None:
    target = tmp_path / "watched_file.conf"
    target.write_text("content")

    seen_paths: list[str] = []

    def _access(path: str, mode: int) -> bool:
        seen_paths.append(path)
        return True

    result = classify_path_writability(
        str(target),
        statvfs_fn=_statvfs(read_only=False),
        access_fn=_access,
        exists_fn=os.path.exists,
    )
    assert result == WRITABLE
    assert seen_paths == [str(tmp_path)]


# ── probe por defecto: ids efectivos (capabilities del servicio) ─────────────


def test_default_access_probe_uses_effective_ids(monkeypatch) -> None:
    """Sin access_fn inyectado, el chequeo DAC debe usar AT_EACCESS: el servicio
    corre como fim-agent con CAP_DAC_OVERRIDE ambiental, y access(2) con ids
    reales descarta esa capability para un uid distinto de root."""
    calls: list[tuple[str, int, dict]] = []

    def _fake_access(path: str, mode: int, **kwargs) -> bool:
        calls.append((path, mode, kwargs))
        return kwargs.get("effective_ids") is True

    monkeypatch.setattr("agent.preflight.os.access", _fake_access)

    result = classify_path_writability(
        "/fake/root-owned",
        statvfs_fn=_statvfs(read_only=False),
        exists_fn=lambda p: True,
    )

    assert result == WRITABLE
    assert calls == [("/fake/root-owned", os.W_OK, {"effective_ids": True})]


# ── run_preflight ──────────────────────────────────────────────────────────


def test_run_preflight_maps_each_path() -> None:
    result = run_preflight(
        ["/fake/a", "/fake/b"],
        statvfs_fn=_statvfs(read_only=False),
        access_fn=lambda p, mode: True,
        exists_fn=lambda p: True,
    )
    assert result == {"/fake/a": WRITABLE, "/fake/b": WRITABLE}


# ── PreflightRegistry: estado explícito, no variable de módulo (D-4) ─────────


def test_registry_update_and_snapshot_are_independent_copies() -> None:
    registry = PreflightRegistry()
    assert registry.snapshot() == {}

    mapping = {"/etc": WRITABLE}
    registry.update(mapping)
    snapshot = registry.snapshot()
    assert snapshot == mapping

    # Mutar el mapa original o el snapshot no debe afectar al registry.
    mapping["/etc"] = READ_ONLY_MOUNT
    snapshot["/usr/bin"] = MISSING
    assert registry.snapshot() == {"/etc": WRITABLE}


def test_registry_config_persisted_defaults_to_none() -> None:
    registry = PreflightRegistry()
    assert registry.config_persisted is None
    registry.set_config_persisted(False)
    assert registry.config_persisted is False
    registry.set_config_persisted(True)
    assert registry.config_persisted is True


def test_two_registries_are_independent() -> None:
    """Objeto explícito, no estado global: dos instancias no se pisan entre sí."""
    a = PreflightRegistry()
    b = PreflightRegistry()
    a.update({"/etc": WRITABLE})
    assert b.snapshot() == {}
