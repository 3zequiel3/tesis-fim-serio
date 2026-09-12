"""Tests del sanitizador de logs del agente (privacy hardening M4).

sanitize_logs (agent/logging.py) redacta por nombre de key vía regex. Estos
tests verifican que diff_text quede cubierto — el agente encola el payload
completo (incluido diff_text) en texto plano y podría terminar en un log si
un caller lo pasa como kwarg estructurado.
"""

from __future__ import annotations

from agent.logging import sanitize_logs


def test_diff_text_redacted():
    """diff_text a nivel superior debe quedar [REDACTED]."""
    event_dict = {
        "event": "publish_attempt",
        "diff_text": "--- a/etc/shadow\n+++ b/etc/shadow\n@@ -1 +1 @@\n-root:x\n+root:hacked\n",
    }
    result = sanitize_logs(None, "info", event_dict)
    assert result["diff_text"] == "[REDACTED]"
    assert "root:hacked" not in str(result)


def test_non_sensitive_keys_preserved():
    """Keys no sensibles no se ven afectadas por el agregado de diff_text."""
    event_dict = {"event": "x", "event_id": "abc-123", "path": "/etc/passwd"}
    result = sanitize_logs(None, "info", event_dict)
    assert result["event_id"] == "abc-123"
    assert result["path"] == "/etc/passwd"
