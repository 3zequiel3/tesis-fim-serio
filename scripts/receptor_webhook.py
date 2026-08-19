#!/usr/bin/env python3
"""Receptor de webhooks para la Batería 4 del Cap. 5 (ítems 11-22).

POR QUÉ EXISTE
    La Batería 4 mide el intervalo "recepción del evento por el backend →
    emisión exitosa del webhook", y el plan aclara que **no** incluye la
    entrega en n8n ni en el canal final. Para medir eso alcanza con un
    receptor que acepte el POST y registre cuándo llegó.

    Lo que NO sirve es apuntar `N8N_WEBHOOK_URL` a `/healthz`, que es el
    estado actual del `docker-compose.yml`: ese endpoint responde 200 a
    cualquier cosa, así que toda alerta se marca `delivered` sin que nadie
    reciba nada, y los ítems 11-22 medirían el tiempo de responder un health
    check. Este receptor sí es un webhook: registra qué llegó y cuándo.

QUÉ REGISTRA
    Una línea JSON por request en el archivo de salida, con:
      ts_recepcion_epoch / ts_recepcion_utc  — sello al momento de recibir
      alert_id, event_id, severity, path     — extraídos del payload si vienen
      payload                                — el cuerpo crudo completo

    El cruce con `events.received_at` produce los ítems 11-22.

USO
    python3 scripts/receptor_webhook.py --puerto 9099 --out resultados/bateria4_webhook.jsonl

    Y apuntar el backend al receptor (misma red que el compose):
      N8N_WEBHOOK_URL=http://<host>:9099/webhook docker compose up -d backend

LIMITACIÓN A DECLARAR EN EL CAP. 5
    Este receptor responde 200 siempre. Es lo correcto para la Batería 4, que
    mide explícitamente el camino feliz de primer intento — pero significa que
    esta corrida **no** ejercita la escalera de reintentos ni el DLQ. Esos hay
    que medirlos aparte, con un receptor que falle a propósito.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock

_LOCK = Lock()
_SALIDA: Path | None = None
_RECIBIDOS = 0


class _Handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802 - firma impuesta por BaseHTTPRequestHandler
        global _RECIBIDOS
        # Sellar ANTES de cualquier trabajo: el instante de recepción es el dato.
        ahora = datetime.now(timezone.utc)

        largo = int(self.headers.get("Content-Length", 0) or 0)
        crudo = self.rfile.read(largo).decode("utf-8", errors="replace") if largo else ""

        try:
            payload = json.loads(crudo) if crudo else {}
        except json.JSONDecodeError:
            payload = {"_no_json": crudo}

        registro = {
            "ts_recepcion_epoch": ahora.timestamp(),
            "ts_recepcion_utc": ahora.isoformat(),
            "ruta": self.path,
            "alert_id": payload.get("alert_id") or payload.get("id"),
            "event_id": payload.get("event_id"),
            "severity": payload.get("severity"),
            "path": payload.get("path"),
            "payload": payload,
        }

        with _LOCK:
            _RECIBIDOS += 1
            n = _RECIBIDOS
            if _SALIDA is not None:
                with _SALIDA.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(registro, ensure_ascii=False) + "\n")
                    fh.flush()

        cuerpo = b'{"ok":true}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(cuerpo)))
        self.end_headers()
        self.wfile.write(cuerpo)

        print(
            f"[{n:>5}] {ahora.isoformat()} alert_id={registro['alert_id']} "
            f"event_id={registro['event_id']} severity={registro['severity']}",
            flush=True,
        )

    def do_GET(self) -> None:  # noqa: N802
        # Sonda de vida del propio receptor. No se usa como destino de alertas.
        cuerpo = json.dumps({"ok": True, "recibidos": _RECIBIDOS}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(cuerpo)))
        self.end_headers()
        self.wfile.write(cuerpo)

    def log_message(self, *_args) -> None:
        # Silenciar el log por defecto: ya emitimos una línea por request.
        return


def main() -> int:
    global _SALIDA

    p = argparse.ArgumentParser(description="Receptor de webhooks para la Batería 4 (ítems 11-22).")
    p.add_argument("--puerto", type=int, required=True, help="Puerto de escucha.")
    p.add_argument("--host", default="0.0.0.0", help="Interfaz de escucha (default: todas).")
    p.add_argument("--out", required=True, help="Archivo JSONL de salida (se agrega, no se pisa).")
    args = p.parse_args()

    _SALIDA = Path(args.out)
    _SALIDA.parent.mkdir(parents=True, exist_ok=True)

    servidor = ThreadingHTTPServer((args.host, args.puerto), _Handler)
    print(
        f"receptor escuchando en http://{args.host}:{args.puerto}  ->  {_SALIDA}\n"
        "Ctrl-C para terminar.",
        flush=True,
    )
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        print(f"\nterminado. requests recibidos: {_RECIBIDOS}", flush=True)
    finally:
        servidor.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
