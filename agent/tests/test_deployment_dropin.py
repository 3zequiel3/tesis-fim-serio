"""Tests de agent/deployment.py (D36/RN-130, D-2/D-12 del design).

Puros, sin root ni systemd: read_watch_paths se ejercita sobre un YAML real
en tmp_path (PyYAML no necesita privilegios) y render_watchpaths_dropin es
una función pura sobre listas de strings. Cubre la forma del texto renderizado
y, sobre todo, el rechazo — nunca el filtrado silencioso — de paths que
podrían inyectar una directiva systemd adicional.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from agent.deployment import (
    ALWAYS_INCLUDED_PATH,
    read_watch_paths,
    render_watchpaths_dropin,
)

# ── render_watchpaths_dropin: forma del texto ─────────────────────────────────


def test_dropin_always_includes_etc_fim_agent() -> None:
    content = render_watchpaths_dropin([])
    assert f'ReadWritePaths="{ALWAYS_INCLUDED_PATH}"' in content


def test_dropin_one_quoted_line_per_path() -> None:
    content = render_watchpaths_dropin(["/etc", "/bin", "/usr/bin"])
    assert 'ReadWritePaths="/etc"' in content
    assert 'ReadWritePaths="/bin"' in content
    assert 'ReadWritePaths="/usr/bin"' in content
    # Una línea por path, no una sola línea espacio-separada.
    lines = [ln for ln in content.splitlines() if ln.startswith("ReadWritePaths=")]
    assert len(lines) == 4  # los tres + /etc/fim-agent


def test_dropin_has_service_section_header() -> None:
    content = render_watchpaths_dropin(["/etc"])
    assert "[Service]" in content


def test_dropin_does_not_repeat_agent_owned_dirs_by_default() -> None:
    content = render_watchpaths_dropin(["/etc", "/bin"])
    assert "/var/lib/fim-agent" not in content
    assert "/var/log/fim-agent" not in content


def test_dropin_never_emits_empty_readwritepaths_reset() -> None:
    content = render_watchpaths_dropin([])
    for line in content.splitlines():
        assert line.strip() != "ReadWritePaths="


def test_dropin_deduplicates_paths() -> None:
    content = render_watchpaths_dropin(["/etc", "/etc"])
    lines = [ln for ln in content.splitlines() if ln.startswith("ReadWritePaths=")]
    assert lines.count('ReadWritePaths="/etc"') == 1


# ── render_watchpaths_dropin: rechazo, nunca filtro silencioso ───────────────


def test_relative_path_is_rejected() -> None:
    with pytest.raises(ValueError, match="absolute"):
        render_watchpaths_dropin(["etc/passwd"])


def test_dotdot_component_is_rejected() -> None:
    with pytest.raises(ValueError, match=r"\.\."):
        render_watchpaths_dropin(["/etc/../root"])


def test_newline_is_rejected() -> None:
    with pytest.raises(ValueError, match="newline"):
        render_watchpaths_dropin(["/etc\nCapabilityBoundingSet="])


def test_double_quote_is_rejected() -> None:
    with pytest.raises(ValueError, match="double quote"):
        render_watchpaths_dropin(['/etc/"weird'])


def test_backslash_is_rejected() -> None:
    with pytest.raises(ValueError, match="backslash"):
        render_watchpaths_dropin(["/etc/\\weird"])


def test_rejection_names_offending_path() -> None:
    with pytest.raises(ValueError, match="attacker/path"):
        render_watchpaths_dropin(["attacker/path"])


# ── normpath, no realpath (D33/RN-127): no se siguen symlinks ────────────────


def test_symlinked_watch_path_is_not_dereferenced(tmp_path: Path) -> None:
    real_target = tmp_path / "real_dir"
    real_target.mkdir()
    link = tmp_path / "link_dir"
    link.symlink_to(real_target)

    content = render_watchpaths_dropin([str(link)])
    assert f'ReadWritePaths="{link}"' in content
    assert str(real_target) not in content


def test_normpath_collapses_redundant_segments_without_dotdot() -> None:
    content = render_watchpaths_dropin(["/etc//fim-agent/./watched"])
    assert 'ReadWritePaths="/etc/fim-agent/watched"' in content


# ── read_watch_paths ──────────────────────────────────────────────────────────


def test_read_watch_paths_from_real_yaml(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.dump({"watch_paths": ["/etc", "/usr/bin"]}))
    assert read_watch_paths(str(config_path)) == ["/etc", "/usr/bin"]


def test_read_watch_paths_missing_key_returns_empty(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.dump({"agent_id": "test"}))
    assert read_watch_paths(str(config_path)) == []
