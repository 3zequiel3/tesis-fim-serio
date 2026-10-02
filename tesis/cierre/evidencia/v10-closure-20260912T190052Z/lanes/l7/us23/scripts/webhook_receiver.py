#!/usr/bin/env python3
"""Minimal controlled webhook receiver for the US-23 fallback-cascade lab.

Not a commercial provider: a local, disposable HTTP server that records every
POSTed body as one JSON line to /data/received.jsonl and returns 200 OK. Used
to stand in for the "webhook directo pre-configurado" fallback channel.
"""
from __future__ import annotations

import json
import os
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

OUT_PATH = os.environ.get("RECEIVER_OUT", "/data/received.jsonl")


class Handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802 (stdlib API)
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length) if length else b""
        try:
            payload = json.loads(body.decode("utf-8"))
        except Exception:
            payload = {"_raw": body.decode("utf-8", "replace")}
        record = {"received_at": time.time(), "payload": payload}
        with open(OUT_PATH, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"status":"accepted"}')

    def log_message(self, fmt: str, *args) -> None:  # silence default stderr noise
        return


if __name__ == "__main__":
    server = ThreadingHTTPServer(("0.0.0.0", 9099), Handler)
    server.serve_forever()
