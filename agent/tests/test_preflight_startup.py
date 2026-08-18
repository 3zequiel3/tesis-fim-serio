"""D36/RN-130 (D-4, D-12 task 11.7): el preflight de arranque NUNCA llama a
sys.exit, cualquiera sea la clasificación — la detección es la función
primaria, la remediación es una capacidad adicional que puede faltar sin
invalidar el servicio.

`main()` no es fácilmente testeable end-to-end sin mockear bootstrap,
Valkey, fanotify y las señales del proceso (ningún test de la suite lo
invoca completo — ver agent/tests/test_resilience_fixes.py:173 para el
mismo patrón de verificación estructural con `ast` que se usa acá). Esta
verificación estructural confirma, sobre el AST real de `agent/__main__.py`,
que el bloque de preflight (entre su instanciación y `engine.init_scan`) no
contiene ningún `sys.exit`, y que run_preflight/PreflightRegistry corren
antes del scan inicial. El comportamiento del cuerpo (clasificación,
logging) ya está cubierto sin mocks en agent/tests/test_preflight.py.
"""
from __future__ import annotations

import ast
from pathlib import Path


def _parse_main() -> ast.AsyncFunctionDef:
    src = (Path(__file__).parent.parent / "__main__.py").read_text()
    tree = ast.parse(src)
    return next(
        n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef) and n.name == "main"
    )


def _line_of_call(main_fn: ast.AsyncFunctionDef, *, contains: str) -> int:
    src_lines = (Path(__file__).parent.parent / "__main__.py").read_text().splitlines()
    for node in ast.walk(main_fn):
        if isinstance(node, ast.Call):
            try:
                segment = ast.get_source_segment(
                    "\n".join(src_lines), node
                ) or ""
            except Exception:
                segment = ""
            if contains in segment:
                return node.lineno
    raise AssertionError(f"no call containing {contains!r} found in main()")


def test_preflight_block_contains_no_sys_exit() -> None:
    main_fn = _parse_main()

    registry_line = _line_of_call(main_fn, contains="PreflightRegistry()")
    init_scan_line = _line_of_call(main_fn, contains="engine.init_scan(")
    assert registry_line < init_scan_line, (
        "PreflightRegistry() debe instanciarse ANTES de engine.init_scan (D36/RN-130)"
    )

    sys_exit_lines = [
        node.lineno
        for node in ast.walk(main_fn)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "exit"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "sys"
    ]

    exits_inside_preflight_block = [
        ln for ln in sys_exit_lines if registry_line <= ln <= init_scan_line
    ]
    assert exits_inside_preflight_block == [], (
        "El preflight NUNCA debe llamar a sys.exit — un path no escribible "
        "no puede detener al agente ni interrumpir el monitoreo (D36/RN-130)."
    )


def test_preflight_runs_before_initial_baseline_scan() -> None:
    """El primer heartbeat ya debe poder llevar el resultado del preflight —
    por eso corre antes del scan inicial, no después."""
    main_fn = _parse_main()
    run_preflight_line = _line_of_call(main_fn, contains="run_preflight(")
    init_scan_line = _line_of_call(main_fn, contains="engine.init_scan(")
    assert run_preflight_line < init_scan_line


def test_run_preflight_source_contains_no_sys_exit() -> None:
    """Garantía estructural directa sobre agent/preflight.py: el módulo entero
    no importa ni llama sys.exit — no hay forma de que run_preflight aborte
    el proceso."""
    src = (Path(__file__).parent.parent / "preflight.py").read_text()
    assert "sys.exit" not in src
    assert "os._exit" not in src
