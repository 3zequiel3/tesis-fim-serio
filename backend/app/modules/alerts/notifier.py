"""
Funciones de envío de notificaciones para FIM Platform (C15 — backend-notifications).

Cada función es async y retorna True si el envío fue exitoso, False si falló.
Se mantiene separado de service.py para facilitar mocking en tests (D-C15-07).

Canales disponibles:
  send_n8n             — POST a n8n webhook via httpx async
  send_smtp            — SMTP async via aiosmtplib
  send_webhook_fallback — POST a URL arbitraria via httpx async
  send_log_only        — log crítico estructurado, siempre exitoso (RN-54)
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import httpx
import structlog

from app.core.config import settings

log = structlog.get_logger()

_N8N_TIMEOUT = 10.0  # segundos (D-C15-04)
_FALLBACK_TIMEOUT = 10.0

# ── Long-lived HTTP client of the notification lane ──────────────────────────
#
# Amplification of 2026-10-03 of D87/RN-181 (change `ingest-batched-persistence`,
# phase A, A-1..A-3). A new `httpx.AsyncClient` per delivery rebuilt the SSL
# context (CA bundle load, CPU held in-process) plus the transport and the TCP
# handshake on every delivery; measured in `mediciones.md` section 1, the same
# bench with that cost removed went from 62.0 to 81.4 ev/s. One client for the
# whole process removes the three costs.
#
# TLS verification stays at the httpx default (on, default trust store): the
# SSL context is built once, here, and certificate verification is never
# switched off in production code. The per-channel timeout is passed per request.
#
# `keepalive_expiry` stays under the 5 s `keepAliveTimeout` that Node uses by
# default (n8n 2.17.8 does not override it, checked in the image, task 2.1), so
# the client never reuses a connection that n8n is about to close. A connection
# reset surfaces as an `httpx.TransportError` that the channel functions already
# turn into `False` (durable retry ladder, D42/RN-136); httpx drops the broken
# connection from the pool and the next delivery opens a new one (A-3).
_KEEPALIVE_EXPIRY_S = 4.0
_notify_http_client: httpx.AsyncClient | None = None
# Set by `close_notify_http_client()` (backend shutdown) and cleared by an explicit
# `init_notify_http_client()`: a fire-and-forget delivery that outlives the shutdown must
# fail (and follow the durable retry ladder on the next start) instead of lazily recreating
# a client nobody will ever close.
_notify_http_client_closed = False


def _build_notify_http_client() -> httpx.AsyncClient:
    limit = settings.notify_max_concurrent_deliveries
    return httpx.AsyncClient(
        limits=httpx.Limits(
            max_connections=limit,
            max_keepalive_connections=limit,
            keepalive_expiry=_KEEPALIVE_EXPIRY_S,
        ),
    )


def init_notify_http_client() -> httpx.AsyncClient:
    """Create the shared client (lifespan startup). Idempotent; re-opens a closed lane."""
    global _notify_http_client, _notify_http_client_closed
    _notify_http_client_closed = False
    if _notify_http_client is None or _notify_http_client.is_closed:
        _notify_http_client = _build_notify_http_client()
    return _notify_http_client


def get_notify_http_client() -> httpx.AsyncClient:
    """
    The shared client; lazily created with the same configuration (tests, bench, scripts).
    After `close_notify_http_client()` it refuses to recreate it (RuntimeError, which the
    channel functions turn into a failed delivery).
    """
    if _notify_http_client is not None and not _notify_http_client.is_closed:
        return _notify_http_client
    if _notify_http_client_closed:
        raise RuntimeError("notify http client closed (backend shutting down)")
    return init_notify_http_client()


async def close_notify_http_client() -> None:
    """Close and drop the shared client (lifespan shutdown); later gets refuse to recreate it."""
    global _notify_http_client, _notify_http_client_closed
    _notify_http_client_closed = True
    client, _notify_http_client = _notify_http_client, None
    if client is not None:
        await client.aclose()


def reset_notify_http_client_for_tests() -> None:
    """Drop the client without awaiting it. Test-suite use only (connections are bound to one loop)."""
    global _notify_http_client, _notify_http_client_closed
    _notify_http_client = None
    _notify_http_client_closed = False


async def send_n8n(payload: dict[str, Any], url: str, timeout: float = _N8N_TIMEOUT) -> bool:
    """POST el payload al webhook de n8n. Retorna True si recibe 2xx.

    ``backend_dispatched_at`` is transport evidence, stamped immediately before
    the request without mutating the canonical payload retained by the caller.
    It is intentionally distinct from the event's ``received_at`` timestamp.
    """
    if not url:
        log.debug("notifier.n8n_skipped", reason="url_not_configured")
        return False
    try:
        wire_payload = {
            **payload,
            "backend_dispatched_at": datetime.now(timezone.utc).isoformat(),
        }
        response = await get_notify_http_client().post(url, json=wire_payload, timeout=timeout)
        response.raise_for_status()
        log.info("notifier.n8n_sent", status_code=response.status_code)
        return True
    except Exception as exc:
        log.warning("notifier.n8n_failed", error=str(exc))
        return False


async def send_smtp(payload: dict[str, Any], cfg: Any) -> bool:
    """
    Envía un email async con aiosmtplib.

    cfg debe tener: smtp_host, smtp_port, smtp_user, smtp_password, smtp_from,
    smtp_to, smtp_starttls, smtp_ssl.

    MODO DE CIFRADO (D43/RN-137)
        Hasta C46 esta función pasaba `start_tls=True` sin condición, así que un
        relay en 465 (SMTPS implícito) o uno interno sin STARTTLS fallaba
        SIEMPRE — y el modo de falla era un `except` genérico que sólo logueaba,
        con lo cual el canal de fallback más importante de la cascada estaba
        muerto en silencio para esas topologías.

          smtp_ssl=True                        → TLS implícito (SMTPS, típ. 465)
          smtp_starttls=True y smtp_ssl=False  → STARTTLS (típ. 587) — default
          ambos False                          → sin cifrar (sólo relay interno)

        Los defaults reproducen el comportamiento previo: migración de cero pasos.

    Retorna True si el envío fue exitoso.
    """
    if not cfg.smtp_host:
        log.debug("notifier.smtp_skipped", reason="smtp_host_not_configured")
        return False

    use_ssl = bool(getattr(cfg, "smtp_ssl", False))
    use_starttls = bool(getattr(cfg, "smtp_starttls", True))

    if use_ssl and use_starttls:
        # TLS implícito y STARTTLS son mutuamente excluyentes: la sesión ya está
        # cifrada antes del saludo, así que no hay nada que promover. Se rechaza
        # explícitamente en vez de elegir uno en silencio — una configuración
        # contradictoria es un error del operador y merece decirlo.
        # El mensaje dice QUÉ hacer, no sólo qué está mal: smtp_starttls
        # defaultea a True, así que quien configure sólo SMTP_SSL=true cae acá
        # sin haber pedido nada contradictorio a propósito. Un error que no
        # nombra la salida es la misma clase de defecto que este change corrige
        # en `last_error` de la DLQ.
        log.error(
            "notifier.smtp_config_invalid",
            reason="smtp_starttls and smtp_ssl are mutually exclusive",
            remedy="for implicit TLS (port 465) set SMTP_SSL=true and SMTP_STARTTLS=false; "
                   "for STARTTLS (port 587) set SMTP_SSL=false",
            smtp_starttls=use_starttls,
            smtp_ssl=use_ssl,
        )
        return False

    try:
        import aiosmtplib
        from email.mime.text import MIMEText

        body = json.dumps(payload, indent=2, ensure_ascii=False)
        msg = MIMEText(body, "plain", "utf-8")
        msg["Subject"] = f"[FIM Alert] severity={payload.get('severity', 'unknown')}"
        msg["From"] = cfg.smtp_from or cfg.smtp_user
        msg["To"] = cfg.smtp_to

        await aiosmtplib.send(
            msg,
            hostname=cfg.smtp_host,
            port=cfg.smtp_port,
            username=cfg.smtp_user or None,
            password=cfg.smtp_password or None,
            use_tls=use_ssl,
            start_tls=use_starttls if not use_ssl else False,
        )
        log.info("notifier.smtp_sent", to=cfg.smtp_to, tls="implicit" if use_ssl else ("starttls" if use_starttls else "none"))
        return True
    except Exception as exc:
        log.warning("notifier.smtp_failed", error=str(exc))
        return False


async def send_webhook_fallback(
    payload: dict[str, Any],
    url: str,
    timeout: float = _FALLBACK_TIMEOUT,
) -> bool:
    """POST el payload al webhook de fallback. Retorna True si recibe 2xx."""
    if not url:
        log.debug("notifier.webhook_fallback_skipped", reason="url_not_configured")
        return False
    try:
        response = await get_notify_http_client().post(url, json=payload, timeout=timeout)
        response.raise_for_status()
        log.info("notifier.webhook_fallback_sent", status_code=response.status_code)
        return True
    except Exception as exc:
        log.warning("notifier.webhook_fallback_failed", error=str(exc))
        return False


async def send_log_only(payload: dict[str, Any]) -> bool:
    """
    Canal de último recurso (RN-54): emite log crítico estructurado.
    Siempre retorna True — nunca falla.
    """
    log.critical(
        "notifier.log_only",
        severity=payload.get("severity"),
        event_id=payload.get("event_id"),
        path=payload.get("path"),
        alert_id=payload.get("alert_id"),
    )
    return True
