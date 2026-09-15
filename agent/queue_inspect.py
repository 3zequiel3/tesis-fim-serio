"""Root-only, read-only forensic inspector for the FIM agent's encrypted
offline queue and discard directory (D-9 / D63 / RN-157, RN-108).

Since Change 53 every queue and discard file is encrypted at rest (see
`agent/queue.py`). An operator with root access on the host can still need
to inspect an event for forensic purposes — this CLI does that without
reintroducing plaintext on disk and without exposing the queue key over any
network channel (RN-108/D8: no HTTP server in the agent).

Invocation: ``python -m agent.queue_inspect [--config PATH]
[--dir {queue,discard,both}] [--print FILENAME]``.

- Default (list) mode prints, per file, its name, size on disk and a status
  (``ok``, ``authentication_failed``, ``malformed``, ``legacy_plaintext``)
  without ever decrypting for the purpose of printing content.
- ``--print FILENAME`` decrypts exactly that one file and prints its
  decoded envelope as JSON to stdout.
- The command is read-only in every mode: it never writes, deletes, or
  creates a file, and it never runs the in-place migration pass from D-5 or
  constructs a full ``EventQueue``.

The key is derived from the same agent state the main process uses
(``agent.config.load_config`` + ``agent.baseline.load_master_secret`` +
``cfg.agent_id``) — no new credentials or paths.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from agent.baseline import load_master_secret
from agent.config import load_config
from agent.queue import QueueFileUnreadable, classify_queue_file, derive_queue_key, read_queue_file

EX_USAGE = 64
EX_CONFIG = 78
EX_NOPERM = 77
EX_DATAERR = 65


def _require_root() -> None:
    """Reject a non-root invocation before reading config, secrets or files."""
    if os.geteuid() != 0:
        print("agent.queue_inspect: root privileges are required", file=sys.stderr)
        sys.exit(EX_NOPERM)


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m agent.queue_inspect",
        description="Root-only, read-only forensic inspector for the FIM agent queue/discard files (D-9).",
    )
    parser.add_argument(
        "--config",
        default="/etc/fim-agent/config.yaml",
        help="Path to the agent config file (default: /etc/fim-agent/config.yaml)",
    )
    parser.add_argument(
        "--dir",
        choices=["queue", "discard", "both"],
        default="both",
        help="Which directory to inspect (default: both)",
    )
    parser.add_argument(
        "--print",
        dest="print_file",
        metavar="FILENAME",
        default=None,
        help="Decrypt and print the decoded envelope of one file to stdout",
    )
    return parser


def _list_directory(directory: Path, key: bytes) -> None:
    if not directory.exists():
        return
    for path in sorted(directory.glob("*.json")):
        try:
            size = path.stat().st_size
        except OSError:
            continue
        status = classify_queue_file(path, key)
        print(f"{path.name}\t{size}\t{status}")


def _run_list(cfg, key: bytes, which: str) -> int:
    queue_dir = Path(cfg.storage.queue_dir)
    discard_dir = Path(cfg.storage.discard_dir)
    if which in ("queue", "both"):
        _list_directory(queue_dir, key)
    if which in ("discard", "both"):
        _list_directory(discard_dir, key)
    return 0


def _find_file(cfg, which: str, filename: str) -> Path | None:
    candidates: list[Path] = []
    if which in ("queue", "both"):
        candidates.append(Path(cfg.storage.queue_dir) / filename)
    if which in ("discard", "both"):
        candidates.append(Path(cfg.storage.discard_dir) / filename)
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _run_print(cfg, key: bytes, which: str, filename: str) -> int:
    path = _find_file(cfg, which, filename)
    if path is None:
        print(f"agent.queue_inspect: file not found: {filename}", file=sys.stderr)
        return EX_DATAERR
    try:
        envelope = read_queue_file(path, key)
    except QueueFileUnreadable as exc:
        print(f"agent.queue_inspect: {exc.reason}", file=sys.stderr)
        return EX_DATAERR
    except OSError as exc:
        print(f"agent.queue_inspect: {exc}", file=sys.stderr)
        return EX_DATAERR
    print(json.dumps(envelope, sort_keys=True, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    # Root check MUST run before any config, secret or file read (D-9).
    _require_root()

    parser = _build_arg_parser()
    args = parser.parse_args(argv)

    cfg = load_config(args.config)
    master_secret = load_master_secret(cfg.storage.secrets_dir)
    key = derive_queue_key(master_secret, cfg.agent_id)

    if args.print_file is not None:
        return _run_print(cfg, key, args.dir, args.print_file)
    return _run_list(cfg, key, args.dir)


if __name__ == "__main__":
    sys.exit(main())
