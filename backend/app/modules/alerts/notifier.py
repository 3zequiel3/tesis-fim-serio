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
from typing import Any

import structlog

log = structlog.get_logger()

_N8N_TIMEOUT = 10.0  # segundos (D-C15-04)
_FALLBACK_TIMEOUT = 10.0


async def send_n8n(payload: dict[str, Any], url: str, timeout: float = _N8N_TIMEOUT) -> bool:
    """POST el payload al webhook de n8n. Retorna True si recibe 2xx."""
    if not url:
        log.debug("notifier.n8n_skipped", reason="url_not_configured")
        return False
    try:
        import httpx

        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
        log.info("notifier.n8n_sent", status_code=response.status_code)
        return True
    except Exception as exc:
        log.warning("notifier.n8n_failed", error=str(exc))
        return False


async def send_smtp(payload: dict[str, Any], cfg: Any) -> bool:
    """
    Envía un email async con aiosmtplib.
    cfg debe tener: smtp_host, smtp_port, smtp_user, smtp_password, smtp_from, smtp_to.
    Retorna True si el envío fue exitoso.
    """
    if not cfg.smtp_host:
        log.debug("notifier.smtp_skipped", reason="smtp_host_not_configured")
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
            start_tls=True,
        )
        log.info("notifier.smtp_sent", to=cfg.smtp_to)
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
        import httpx

        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(url, json=payload)
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
