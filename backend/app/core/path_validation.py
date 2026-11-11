"""
Pure validation of operator-entered paths (D91/RN-185).

Used by the rules service (``pattern``) and the agent service (``watch_paths``)
BEFORE any write, ``ruleset_version`` increment or command publication. The
module has no FastAPI or database dependency: it raises ``PathValidationError``
and the routers translate it into a ``422`` with ``detail = {code, message}``
(D90/RN-184).

Existence of a watched path is NOT checked here: it belongs to the agent and is
reported through ``watch_path_status`` (D36/RN-130).
"""

MAX_PATH_LENGTH = 1024
MAX_WATCH_PATHS = 64


class PathValidationError(ValueError):
    """A rejected path. ``index`` is the position of the entry in a list, if any."""

    def __init__(self, code: str, message: str, index: int | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.index = index

    def to_detail(self) -> dict[str, str | int]:
        """Body of the ``detail`` field of the HTTP 422 response (D90/RN-184)."""
        detail: dict[str, str | int] = {"code": self.code, "message": self.message}
        if self.index is not None:
            detail["index"] = self.index
        return detail


# Spanish messages keyed by the suffix shared by the ``pattern_*`` and
# ``watch_path_*`` families.
_PATTERN_MESSAGES = {
    "empty": "El patrón no puede estar vacío.",
    "not_absolute": "El patrón debe ser una ruta absoluta (empezar con /).",
    "parent_segment": "El patrón no puede contener un segmento «..».",
    "control_char": "El patrón no puede contener saltos de línea ni otros caracteres de control.",
    "too_long": f"El patrón no puede superar los {MAX_PATH_LENGTH} caracteres.",
}
_PATH_MESSAGES = {
    "empty": "La ruta no puede estar vacía.",
    "not_absolute": "La ruta debe ser absoluta (empezar con /).",
    "parent_segment": "La ruta no puede contener un segmento «..».",
    "control_char": "La ruta no puede contener saltos de línea ni otros caracteres de control.",
    "too_long": f"La ruta no puede superar los {MAX_PATH_LENGTH} caracteres.",
}


def _has_control_char(value: str) -> bool:
    return any(ord(c) < 0x20 or ord(c) == 0x7F for c in value)


def _check_path(value: str, body: str) -> str | None:
    """Return the reason suffix of the first failed check, or None.

    ``value`` is the full input (its length is what is bounded); ``body`` is the
    part that must look like an absolute path (``value`` without a leading ``!``
    for a rule pattern).
    """
    if not body or not body.strip():
        return "empty"
    if not body.startswith("/"):
        return "not_absolute"
    if ".." in body.split("/"):
        return "parent_segment"
    if _has_control_char(value):
        return "control_char"
    if len(value) > MAX_PATH_LENGTH:
        return "too_long"
    return None


def _has_unclosed_class(pattern: str) -> bool:
    """Replicate the class scan of ``fnmatch.translate``.

    ``fnmatch`` treats an unclosed ``[`` as a literal, which is never what the
    operator meant. After ``[`` a leading ``!`` and an immediate ``]`` are part
    of the class, so ``[]abc]`` and ``[!.]`` are well formed.
    """
    i, n = 0, len(pattern)
    while i < n:
        c = pattern[i]
        i += 1
        if c != "[":
            continue
        j = i
        if j < n and pattern[j] == "!":
            j += 1
        if j < n and pattern[j] == "]":
            j += 1
        while j < n and pattern[j] != "]":
            j += 1
        if j >= n:
            return True
        i = j + 1
    return False


def validate_rule_pattern(pattern: str) -> None:
    """Validate a rule ``pattern`` (without the ``!`` prefix for the path checks)."""
    body = pattern[1:] if pattern.startswith("!") else pattern
    reason = _check_path(pattern, body)
    if reason is not None:
        raise PathValidationError(f"pattern_{reason}", _PATTERN_MESSAGES[reason])
    if _has_unclosed_class(body):
        raise PathValidationError(
            "pattern_invalid_glob",
            "El patrón tiene un corchete «[» sin su «]» de cierre.",
        )


def validate_watch_paths(paths: list[str]) -> None:
    """Validate the ``watch_paths`` list of an agent configuration."""
    if not paths:
        raise PathValidationError(
            "watch_paths_empty", "Tiene que haber al menos una ruta vigilada."
        )
    if len(paths) > MAX_WATCH_PATHS:
        raise PathValidationError(
            "watch_paths_too_many",
            f"No se pueden vigilar más de {MAX_WATCH_PATHS} rutas por agente.",
        )
    seen: set[str] = set()
    for index, path in enumerate(paths):
        reason = _check_path(path, path)
        if reason is not None:
            raise PathValidationError(
                f"watch_path_{reason}", _PATH_MESSAGES[reason], index=index
            )
        # "/etc" and "/etc/" are the same fanotify mark in the agent (D-3).
        canonical = path.rstrip("/") or "/"
        if canonical in seen:
            raise PathValidationError(
                "watch_path_duplicate",
                "La ruta está repetida (con o sin la barra final).",
                index=index,
            )
        seen.add(canonical)
