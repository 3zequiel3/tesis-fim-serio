## 1. Emisión sobre clave pública

- [ ] 1.1 Agregar en `backend/app/core/pki.py` una variante de emisión que acepte **clave pública + subject** en lugar de un CSR. **No modificar `issue_certificate`**: la usa el bootstrap (C06) y funciona.
- [ ] 1.2 Reutilizar el mismo perfil que emite el bootstrap — extensiones, `KeyUsage`, `_CERT_VALIDITY_DAYS` — para que un certificado renovado sea indistinguible de uno recién emitido salvo por el serial y las fechas.
- [ ] 1.3 Test: la clave pública del certificado emitido es idéntica a la de entrada, y el serial es distinto.

## 2. El endpoint

- [ ] 2.1 `POST /agents/renew` en el router de agents, montado en el **listener mTLS (8443)**. No alcanzable sin certificado cliente.
- [ ] 2.2 Extraer el certificado cliente del handshake y derivar de él la identidad. **El `agent_id` del cuerpo NO es la identidad** — se contrasta contra el CN y un desajuste es `403`. Tratarlo como identidad sería un IDOR: cualquier agente con certificado válido renovaría el de otro.
- [ ] 2.3 Emitir sobre la clave pública presentada (D-2) y responder `{"cert_pem": ..., "ca_cert_pem": ...}`, exactamente la forma que el agente ya consume.
- [ ] 2.4 Verificar que `bootstrap_secret` no sea aceptado por ningún camino.

## 3. Revocación

- [ ] 3.1 Antes de emitir, verificar `Agent.status != revoked` **y** que el serial presentado no esté en `revoked_certificates`. `403` si alguna se cumple.
- [ ] 3.2 Tests de ambos caminos de rechazo. **El handshake mTLS no alcanza**: valida la cadena, no consulta la base; sin esto un certificado robado se renueva para siempre.
- [ ] 3.3 Verificar que la renovación **no escribe** en `revoked_certificates` (D-3): el agente necesita el saliente vigente hasta escribir y recargar el nuevo.

## 4. Auditoría

- [ ] 4.1 Registrar cada renovación exitosa en `audit_log` con `agent_id` y los seriales saliente y entrante.
- [ ] 4.2 Registrar los rechazos con su motivo.

## 5. Contrato agente ↔ backend

- [ ] 5.1 Test que envíe al endpoint el cuerpo **exacto** que construye `_cert_renewal_loop` y afirme que el schema lo acepta.
- [ ] 5.2 Test que afirme que la respuesta contiene las claves que el agente consume, de modo que `data["cert_pem"]` no levante `KeyError`.
- [ ] 5.3 **Caso negativo obligatorio**: una respuesta sin `cert_pem` hace fallar el test. Sin él, vaciar el contrato lo deja en verde verificando nada.
- [ ] 5.4 Verificar el test **en rojo**: cambiar temporalmente el nombre de la clave en la respuesta, confirmar que falla, revertir.

## 6. Verificación end-to-end

- [ ] 6.1 Un agente con certificado a menos de 15 días de vencer obtiene uno nuevo sin intervención y sigue publicando.
- [ ] 6.2 Confirmar que **ningún agente desplegado necesita cambios**: su lado está completo y este change es la contraparte que faltaba.
- [ ] 6.3 Suite completa del backend sin regresiones.

## 7. Preguntas abiertas del design — resolver antes de cerrar

- [ ] 7.1 **Agente apagado meses, certificado ya vencido.** El handshake mTLS falla, así que no puede autenticarse para renovar; y el `bootstrap_secret` es de un solo uso y ya se consumió. **Es un camino sin salida.** Es el escenario real de un agente que estuvo apagado y merece resolverse antes de la defensa.
- [ ] 7.2 ¿La clave privada del agente debería rotar también? Hoy sólo rota el certificado. Cambiarlo exige CSR y toca el contrato de los dos lados.
- [ ] 7.3 Confirmar contra RN-78 que el período de validez del renovado coincide con el del bootstrap.
