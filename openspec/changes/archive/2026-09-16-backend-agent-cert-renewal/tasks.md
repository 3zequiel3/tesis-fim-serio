## 1. Emisión sobre clave pública

- [x] 1.1 Agregar en `backend/app/core/pki.py` una variante de emisión que acepte **clave pública + subject** en lugar de un CSR. **No modificar `issue_certificate`**: la usa el bootstrap (C06) y funciona. — Ya implementado: `issue_certificate_for_public_key` en `backend/app/core/pki.py:555`; `issue_certificate` (`pki.py:513`) intacto.
- [x] 1.2 Reutilizar el mismo perfil que emite el bootstrap — extensiones, `KeyUsage`, `_CERT_VALIDITY_DAYS` — para que un certificado renovado sea indistinguible de uno recién emitido salvo por el serial y las fechas. — Ya implementado: `issue_certificate_for_public_key` (`pki.py:555-594`) reusa `_CERT_VALIDITY_DAYS` (`pki.py:29`) y el mismo `KeyUsage`/`ExtendedKeyUsage(CLIENT_AUTH)` que `issue_certificate`.
- [x] 1.3 Test: la clave pública del certificado emitido es idéntica a la de entrada, y el serial es distinto. — Ya implementado: `test_valid_certificate_renews_with_new_serial_and_same_key` en `backend/tests/test_agent_cert_renewal.py`.

## 2. El endpoint

- [x] 2.1 `POST /agents/renew` en el router de agents, montado en el **listener mTLS (8443)**. No alcanzable sin certificado cliente. — Ya implementado: `renew_router` (`backend/app/modules/agents/router.py:54,62`), montado en la app mTLS en `backend/app/main.py:54`. Confirmado por `test_http_app_does_not_mount_credential_renewal_route` y `test_renewal_without_tls_scope_certificate_is_forbidden`.
- [x] 2.2 Extraer el certificado cliente del handshake y derivar de él la identidad. **El `agent_id` del cuerpo NO es la identidad** — se contrasta contra el CN y un desajuste es `403`. — Ya implementado: `router.py:69-84` (lee `PEER_CERT_SCOPE_KEY`, contrasta CN vs `req.agent_id`). Test: `test_identity_and_revocation_fail_closed[mismatch]`.
- [x] 2.3 Emitir sobre la clave pública presentada (D-2) y responder `{"cert_pem": ..., "ca_cert_pem": ...}`. — Ya implementado: `router.py:95-104`.
- [x] 2.4 Verificar que `bootstrap_secret` no sea aceptado por ningún camino. — Ya implementado: `AgentRenewRequest` (`models.py:88-89`) sólo declara `agent_id`; no hay campo `bootstrap_secret` en el schema del endpoint, y el body es validado por pydantic (`extra` no declarado se ignora, nunca se lee).

## 3. Revocación

- [x] 3.1 Antes de emitir, verificar `Agent.status != revoked` **y** que el serial presentado no esté en `revoked_certificates`. `403` si alguna se cumple. — Ya implementado: `router.py:82-86` (`agent.status == AgentStatus.revoked` y `is_revoked(peer_cert.serial_number, session)`, `pki.py:612`).
- [x] 3.2 Tests de ambos caminos de rechazo. — Ya implementado: `test_identity_and_revocation_fail_closed[agent_revoked]` y `[serial_revoked]`.
- [x] 3.3 Verificar que la renovación **no escribe** en `revoked_certificates` (D-3). — Agregado: aserción `session.exec(select(RevokedCertificate)).all() == []` dentro de `test_valid_certificate_renews_with_new_serial_and_same_key` (`backend/tests/test_agent_cert_renewal.py`).

## 4. Auditoría

- [x] 4.1 Registrar cada renovación exitosa en `audit_log` con `agent_id` y los seriales saliente y entrante. — Implementado: `write_audit_log(session, "agent_cert_renewed", None, extra="agent_id=... old_serial=... new_serial=...")` en `router.py`. Requiere D67/RN-161 (`audit_log.user_id` nullable) — migración `018_nullable_audit_log_user_id.sql`. Test: aserción de audit en `test_valid_certificate_renews_with_new_serial_and_same_key`.
- [x] 4.2 Registrar los rechazos con su motivo. — Implementado: `write_audit_log(session, "agent_cert_renewal_rejected", None, extra="... reason=...")` en los tres caminos de rechazo con identidad ya establecida (identity_mismatch, agent_revoked_or_unknown, certificate_revoked) en `router.py`. Test: aserciones de audit en `test_identity_and_revocation_fail_closed` (los 3 casos parametrizados).

## 5. Contrato agente ↔ backend

- [x] 5.1 Test que envíe al endpoint el cuerpo **exacto** que construye `_cert_renewal_loop` y afirme que el schema lo acepta. — Ya implementado: `test_valid_certificate_renews_with_new_serial_and_same_key` envía `json={"agent_id": "agent-renew"}`, idéntico a `agent/__main__.py:101` (`json={"agent_id": cfg.agent_id}`).
- [x] 5.2 Test que afirme que la respuesta contiene las claves que el agente consume, de modo que `data["cert_pem"]` no levante `KeyError`. — Ya implementado en el mismo test (`response.json()["cert_pem"]`).
- [x] 5.3 **Caso negativo obligatorio**: una respuesta sin `cert_pem` hace fallar el test. — Agregado: `test_contract_response_schema_requires_cert_pem` en `backend/tests/test_agent_cert_renewal.py` — `AgentRenewResponse(ca_cert_pem=...)` sin `cert_pem` levanta `pydantic.ValidationError`.
- [x] 5.4 Verificar el test **en rojo**: cambiar temporalmente el nombre de la clave en la respuesta, confirmar que falla, revertir. — Hecho manualmente: renombrado temporal `cert_pem` → `cert_pem_renamed_for_red_check` en `AgentRenewResponse`, `test_valid_certificate_renews_with_new_serial_and_same_key` falló con `pydantic_core.ValidationError: ... cert_pem_renamed_for_red_check Field required`, confirmando que el contrato tiene dientes. Revertido antes de commitear.

## 5.5 Vencimiento fail-closed (D-6)

- [x] 5.5.1 Mantener `CERT_REQUIRED` y TLS 1.3 mínimo en el listener. — Ya implementado: `pki.py:633` (`ssl.TLSVersion.TLSv1_3`), `pki.py:683` (`ssl.CERT_REQUIRED`) en `start_mtls_server`.
- [x] 5.5.2 Test real: certificado ausente, no confiable o vencido falla durante el handshake. — Ya implementado: `test_real_mtls_handshake_and_peer_certificate_scope` en `backend/tests/test_mtls_transport.py` (prueba real de handshake TLS, no mockeada, para `None`, certificado foráneo y certificado vencido).
- [x] 5.5.3 El loop del agente no intenta renovar un certificado ya vencido y registra que requiere recuperación administrativa. — Ya implementado del lado del agente: `agent/__main__.py:75-80` (`if cert.not_valid_after_utc <= now_utc: log.error("cert_renewal.expired_admin_recovery_required", ...); continue`).
- [x] 5.5.4 Documentar que la recuperación administrativa debe preservar el `master_secret` o realizar un re-baseline explícito. — Documentado en `design.md` (D-6) y en `docs/reglas_de_negocio.md` D67/RN-161 (auditoría) y en la sección "Open Questions" §2 de este mismo `design.md` (resuelta por D-6). Sin automatización: es una decisión administrativa deliberada, fuera de alcance de este change.

## 6. Verificación end-to-end

- [x] 6.1 Un agente con certificado a menos de 15 días de vencer obtiene uno nuevo sin intervención y sigue publicando. — Agregado: `backend/tests/test_agent_cert_renewal_e2e.py::test_agent_near_expiry_renews_unattended_and_keeps_authenticating` — listener mTLS real (`start_mtls_server`), certificado a 10 días de vencer, renovación real vía `POST /agents/renew`, verificación con `agent.bootstrap.verify_cert` (misma llamada que hace el agente real), y una **segunda conexión mTLS real** con el certificado renovado + la misma clave privada sin rotar, contra el mismo listener, demostrando continuidad del canal que el agente usa para publicar a Valkey (mismo par de archivos `agent-cert.pem`/`agent-key.pem`, `agent/transport.py`).
- [x] 6.2 Confirmar que **ningún agente desplegado necesita cambios**: su lado está completo y este change es la contraparte que faltaba. — Confirmado por inspección: `agent/__main__.py` y `agent/bootstrap.py` no se tocaron en este change; el contrato que ya implementan (`{"agent_id": ...}` → `{"cert_pem", "ca_cert_pem"}`) es exactamente el que el backend ahora sirve.
- [x] 6.3 Suite completa del backend sin regresiones. — Ejecutada. Ver reporte de la sesión de apply: 826 passed, 4 skipped (antes: 814 passed, 4 skipped; +12 tests nuevos de este change, 0 regresiones).

## 7. Preguntas abiertas del design — resolver antes de cerrar

- [x] 7.1 **Agente apagado, certificado vencido — RESUELTO por D-6.** La renovación posterior al vencimiento se rechaza en el handshake. La recuperación es administrativa y debe preservar el `master_secret` existente o aceptar explícitamente un re-baseline.
- [x] 7.2 ¿La clave privada del agente debería rotar también? Hoy sólo rota el certificado. Cambiarlo exige CSR y toca el contrato de los dos lados. — Resuelto: **no rota en este change.** El handshake mTLS ya prueba posesión de la clave privada existente (`verify_cert(..., private_key=agent_key)`); rotarla exigiría que el agente genere un par nuevo y envíe CSR, reabriendo el problema de confianza del bootstrap (¿cómo confía el backend en una clave nueva sin repetir el `bootstrap_secret` de un solo uso?) y un despliegue coordinado de los dos lados. Queda documentado como riesgo residual: "la clave privada del agente nunca rota, sólo el certificado" (design.md, Risks/Trade-offs).
- [x] 7.3 Confirmar contra RN-78 que el período de validez del renovado coincide con el del bootstrap. — Confirmado: `_CERT_VALIDITY_DAYS = 90` y `_CERT_RENEWAL_THRESHOLD_DAYS = 15` (`backend/app/core/pki.py:29-30`) coinciden con `docs/reglas_de_negocio.md:599-601` (RN-78: vigencia 90 días, renovación en la ventana de los 15 días previos al vencimiento). `issue_certificate_for_public_key` reutiliza la misma constante `_CERT_VALIDITY_DAYS` que `issue_certificate` (bootstrap).
