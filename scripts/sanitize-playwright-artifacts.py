#!/usr/bin/env python3
"""Redact secrets from Playwright traces/reports before evidence is retained."""
from __future__ import annotations

import json
import re
import sys
import tempfile
import urllib.parse
import zipfile
from pathlib import Path

SENSITIVE_KEY = re.compile(r"authorization|cookie|password|secret|token|__playwright_value_", re.I)
JWT = re.compile(r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+")
BEARER = re.compile(r"Bearer\s+[^\s\"']+", re.I)
# E2E login fixtures use a random URL-safe password. Playwright repeats the
# filled value in trace log strings and DOM snapshots under generic keys such
# as `value`, so key-name redaction alone is insufficient. Redacting long
# URL-safe atoms is intentionally conservative for retained evidence.
URLSAFE_SECRET = re.compile(r"(?<![A-Za-z0-9_-])[A-Za-z0-9_-]{24,}(?![A-Za-z0-9_-])")
LAB_USERNAME = re.compile(r"lab-admin-[A-Za-z0-9_-]+", re.I)
HOST_ABSOLUTE_PATH = re.compile(r"(?<![A-Za-z0-9])/(?:home|tmp)/(?:[^\s\"'<>]|\\ )+")
WATCH_FILENAME = re.compile(r"/watch/[A-Za-z0-9_.-]+")
BINARY_VISUAL_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".webm", ".mp4"}
BINARY_VISUAL_MAGIC = (b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff", b"RIFF", b"\x1aE\xdf\xa3")
PLAYWRIGHT_ATTACHMENT = re.compile(r"^.*\[\[ATTACHMENT\|.*\]\].*$", re.I | re.M)
PLAYWRIGHT_ERROR_ATTACHMENT_BLOCK = re.compile(
    r"(?ms)^\s*attachment #\d+: (screenshot|video|trace) \([^\n]+\).*?^\s*─{10,}\s*$"
)
PLAYWRIGHT_ERROR_CONTEXT_PATH = re.compile(r"(?m)^\s*Error Context:\s+.*$")


def redact_string(value: str) -> str:
    # Normalize percent-encoding first so `%2Fhome%2F...`, `%2Ftmp%2F...`
    # and `%2Fwatch%2F...` cannot bypass the same path rules. Two passes cover
    # values encoded once more while remaining bounded and deterministic.
    value = urllib.parse.unquote(urllib.parse.unquote(value))
    value = JWT.sub("[REDACTED-JWT]", value)
    value = BEARER.sub("Bearer [REDACTED]", value)
    value = LAB_USERNAME.sub("[REDACTED-USERNAME]", value)
    value = HOST_ABSOLUTE_PATH.sub("[REDACTED-ABSOLUTE-PATH]", value)
    value = WATCH_FILENAME.sub("/watch/[REDACTED-LAB-FILE]", value)
    return URLSAFE_SECRET.sub("[REDACTED-OPAQUE]", value)


def redact(value, key: str = ""):
    if SENSITIVE_KEY.search(key):
        # Booleans/counts are evidence about presence or status, not secret
        # material. Preserve them while continuing to redact strings and
        # containers under sensitive names.
        if value is None or isinstance(value, (bool, int, float)):
            return value
        return "[REDACTED]"
    if isinstance(value, dict):
        sanitized = {k: redact(v, k) for k, v in value.items()}
        attachments = sanitized.get("attachments")
        if isinstance(attachments, list):
            sanitized["attachments"] = [
                item
                for item in attachments
                if not (
                    isinstance(item, dict)
                    and (
                        str(item.get("name", "")).lower() in {"trace", "screenshot", "video"}
                        or str(item.get("contentType", "")).lower().startswith(("image/", "video/"))
                        or str(item.get("path", "")).lower().endswith(("trace.zip", ".png", ".webm", ".mp4"))
                        or "path" in item
                    )
                )
            ]
        return sanitized
    if isinstance(value, list):
        return [redact(v) for v in value]
    if isinstance(value, str):
        return redact_string(value)
    return value


def sanitize_text(path: Path) -> None:
    text = path.read_text(encoding="utf-8", errors="replace")
    # Preserve JSON structure (and therefore evidence field names) whenever the
    # complete file is valid JSON. Falling straight into line-by-line handling
    # treated pretty-printed key lines as free text and the conservative atom
    # regex replaced long, harmless field names with `[REDACTED-OPAQUE]`.
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        pass
    else:
        path.write_text(
            json.dumps(redact(parsed), ensure_ascii=False, indent=2) + ("\n" if text.endswith("\n") else ""),
            encoding="utf-8",
        )
        return

    text = PLAYWRIGHT_ATTACHMENT.sub("[Attachment reference removed by sanitization]", text)
    text = PLAYWRIGHT_ERROR_ATTACHMENT_BLOCK.sub(
        lambda match: f"\n    [Artifact removed by sanitization: {match.group(1)}]\n",
        text,
    )
    text = PLAYWRIGHT_ERROR_CONTEXT_PATH.sub(
        "    [Error-context path removed by sanitization]",
        text,
    )
    lines = []
    for line in text.splitlines():
        try:
            lines.append(json.dumps(redact(json.loads(line)), ensure_ascii=False))
        except json.JSONDecodeError:
            lines.append(redact_string(line))
    path.write_text("\n".join(lines) + ("\n" if text.endswith("\n") else ""), encoding="utf-8")


def sanitize_zip(path: Path) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        with zipfile.ZipFile(path) as archive:
            archive.extractall(root)
        for candidate in list(root.rglob("*")):
            if not candidate.is_file():
                continue
            data = candidate.read_bytes()
            if candidate.suffix.lower() in BINARY_VISUAL_SUFFIXES or data.startswith(BINARY_VISUAL_MAGIC):
                candidate.unlink()
                continue
            # Trace resource bodies are content-addressed and have no suffix.
            # Sanitize every UTF-8 text resource, not only the named trace logs.
            if b"\0" not in data:
                try:
                    data.decode("utf-8")
                except UnicodeDecodeError:
                    continue
                sanitize_text(candidate)
        replacement = path.with_suffix(".sanitized.zip")
        with zipfile.ZipFile(replacement, "w", zipfile.ZIP_DEFLATED) as archive:
            for candidate in root.rglob("*"):
                if candidate.is_file():
                    archive.write(candidate, candidate.relative_to(root))
        replacement.replace(path)


def main(root: Path) -> None:
    # A trace is itself an executable visual/browser-history container. Even
    # after text redaction it can retain opaque binary DOM/image resources and
    # encoded fixture identifiers in ZIP entry names. Closure packages keep
    # the auditable JUnit/JSON/log evidence instead of a partially sanitized
    # trace that could imply stronger privacy guarantees than we can prove.
    for trace in root.rglob("trace.zip"):
        trace.unlink()
    for candidate in root.rglob("*"):
        if candidate.is_file() and candidate.suffix.lower() in {".json", ".xml", ".log", ".md", ".txt"}:
            sanitize_text(candidate)
    for candidate in list(root.rglob("*")):
        if candidate.is_file() and candidate.suffix.lower() in BINARY_VISUAL_SUFFIXES:
            candidate.unlink()


if __name__ == "__main__":
    main(Path(sys.argv[1]).resolve())
