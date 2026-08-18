"""Genera el drop-in systemd que deriva `ReadWritePaths` de los `watch_paths`
configurados (D36/RN-130, D-2 del design). El unit base queda sin editar;
`install.sh` invoca el entrypoint de este módulo con el intérprete del venv.

`config.yaml` no es estático: `handle_update_config` (agent/commands.py) lo
reescribe con `watch_paths` que llegan del backend por el stream de comandos.
Eso convierte a este generador en superficie de inyección de directivas
systemd, así que `render_watchpaths_dropin` trata cada path como no confiable:
rechaza (nunca filtra en silencio) cualquiera que no sea absoluto o que pueda
inyectar una línea adicional en el drop-in.
"""
from __future__ import annotations

import argparse
import os
import sys

# El drop-in siempre incluye /etc/fim-agent, independientemente de los
# watch_paths configurados: update_config persiste ahí y esa escritura no
# puede depender de que el operador haya elegido monitorear /etc.
ALWAYS_INCLUDED_PATH = "/etc/fim-agent"

_HEADER = (
    "# Generado por `python -m agent.deployment` — NO editar a mano.\n"
    "# Regenerar tras cambiar watch_paths: agent/install.sh lo hace en cada corrida.\n"
    "[Service]\n"
)


def read_watch_paths(config_path: str) -> list[str]:
    """Lee la clave `watch_paths` de un config.yaml con el mismo parser (PyYAML)
    que `handle_update_config` usa para escribirlo. Lista vacía si falta la clave."""
    import yaml

    with open(config_path) as f:
        raw = yaml.safe_load(f) or {}
    paths = raw.get("watch_paths") or []
    return list(paths)


def _validate_path(path: str) -> str:
    """Rechaza (excepción, nunca filtro silencioso) cualquier path no seguro
    para una línea `ReadWritePaths=` de systemd. Normaliza con `normpath`,
    NUNCA con `realpath`: no se siguen symlinks (mismo criterio que D33/RN-127)."""
    if not path.startswith("/"):
        raise ValueError(f"watch path must be absolute: {path!r}")
    if "\n" in path or "\r" in path:
        raise ValueError(f"watch path must not contain a newline: {path!r}")
    if '"' in path:
        raise ValueError(f"watch path must not contain a double quote: {path!r}")
    if "\\" in path:
        raise ValueError(f"watch path must not contain a backslash: {path!r}")
    # Chequear ".." ANTES de normalizar: normpath resuelve "/etc/../etc/passwd"
    # a "/etc/passwd" en silencio, que es exactamente lo que no se quiere.
    if ".." in path.split("/"):
        raise ValueError(f"watch path must not contain a '..' component: {path!r}")
    return os.path.normpath(path)


def render_watchpaths_dropin(watch_paths: list[str]) -> str:
    """Renderiza el texto del drop-in `10-watchpaths.conf` (D-2).

    Una línea `ReadWritePaths=` por path, entrecomillada. Aditivo: nunca repite
    /var/lib/fim-agent ni /var/log/fim-agent (ya están en el unit base) y nunca
    emite una línea `ReadWritePaths=` vacía (resetearía la lista del unit base).
    """
    seen: set[str] = set()
    normalized: list[str] = []

    for path in [ALWAYS_INCLUDED_PATH, *watch_paths]:
        normalized_path = _validate_path(path)
        if normalized_path in seen:
            continue
        seen.add(normalized_path)
        normalized.append(normalized_path)

    lines = [_HEADER]
    for path in normalized:
        lines.append(f'ReadWritePaths="{path}"\n')
    return "".join(lines)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Genera el drop-in ReadWritePaths de fim-agent.service a partir de watch_paths."
    )
    parser.add_argument("--config", required=True, metavar="PATH", help="config.yaml del agente")
    parser.add_argument("--output", required=True, metavar="PATH", help="destino del drop-in .conf")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        watch_paths = read_watch_paths(args.config)
        content = render_watchpaths_dropin(watch_paths)
    except (ValueError, OSError) as exc:
        print(f"agent.deployment: {exc}", file=sys.stderr)
        return 1

    output_dir = os.path.dirname(args.output)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
    tmp_output = args.output + ".tmp"
    with open(tmp_output, "w") as f:
        f.write(content)
    os.replace(tmp_output, args.output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
