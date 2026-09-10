#!/usr/bin/env python3
"""Controlled notification receiver for the n8n closure experiment."""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

DB_PATH = Path(os.environ.get("RECEIVER_DB", "/data/receipts.sqlite3"))
STATUS_CODE = int(os.environ.get("RECEIVER_STATUS_CODE", "202"))
MAX_BODY_BYTES = 1_048_576


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH)
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS receipts (
            notification_id TEXT PRIMARY KEY,
            receiver_received_at TEXT NOT NULL,
            payload_json TEXT NOT NULL
        )
        """
    )
    connection.commit()
    return connection


class Receiver(BaseHTTPRequestHandler):
    server_version = "fim-controlled-receiver/1"

    def _json(self, status: int, body: dict[str, Any]) -> None:
        encoded = json.dumps(body, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/healthz":
            self._json(200, {"status": "ok"})
            return
        if self.path == "/receipts":
            with _connect() as connection:
                rows = connection.execute(
                    "SELECT notification_id, receiver_received_at, payload_json "
                    "FROM receipts ORDER BY rowid"
                ).fetchall()
            self._json(
                200,
                {
                    "receipts": [
                        {
                            "notification_id": notification_id,
                            "receiver_received_at": received_at,
                            "payload": json.loads(payload_json),
                        }
                        for notification_id, received_at, payload_json in rows
                    ]
                },
            )
            return
        self._json(404, {"error": "not_found"})

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/fim-alert":
            self._json(404, {"error": "not_found"})
            return
        if STATUS_CODE < 200 or STATUS_CODE >= 300:
            self._json(STATUS_CODE, {"accepted": False, "error": "controlled_failure"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > MAX_BODY_BYTES:
                raise ValueError("invalid_content_length")
            payload = json.loads(self.rfile.read(length))
            notification_id = payload["notification_id"]
            if not isinstance(notification_id, str) or not notification_id:
                raise ValueError("invalid_notification_id")
        except (ValueError, KeyError, json.JSONDecodeError):
            self._json(400, {"accepted": False, "error": "invalid_payload"})
            return

        received_at = _now()
        serialized = json.dumps(payload, separators=(",", ":"), sort_keys=True)
        with _connect() as connection:
            cursor = connection.execute(
                "INSERT OR IGNORE INTO receipts "
                "(notification_id, receiver_received_at, payload_json) VALUES (?, ?, ?)",
                (notification_id, received_at, serialized),
            )
            connection.commit()
            duplicate = cursor.rowcount == 0
            if duplicate:
                received_at = connection.execute(
                    "SELECT receiver_received_at FROM receipts WHERE notification_id = ?",
                    (notification_id,),
                ).fetchone()[0]

        self._json(
            202,
            {
                "accepted": True,
                "duplicate": duplicate,
                "notification_id": notification_id,
                "receiver_received_at": received_at,
            },
        )

    def log_message(self, format: str, *args: Any) -> None:
        print(json.dumps({"at": _now(), "message": format % args}), flush=True)


if __name__ == "__main__":
    with _connect():
        pass
    ThreadingHTTPServer(("0.0.0.0", 8080), Receiver).serve_forever()
