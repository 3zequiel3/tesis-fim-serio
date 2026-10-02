# Handoff to thesis drafting: STRIDE row for Table 3 (task 8.1, D86/RN-180 amendment 7)

Delivered to the thesis drafting front for inclusion in Table 3. This change does not create a
STRIDE table in `docs/` and does not edit the thesis document. Text in Spanish because it goes
verbatim into the thesis.

| Campo | Contenido |
|---|---|
| **Categoría STRIDE** | Divulgación de información (I) |
| **Activo** | Secreto compartido HMAC de cada agente (`agents.shared_secret_hex`) |
| **Amenaza** | La exfiltración de la base de datos (volcado de `pg_dump`, respaldo, réplica de lectura o volumen `pg_data` extraído) permite a un atacante firmar mensajes como cualquier agente (eventos, heartbeats, ACKs) y firmar comandos hacia cualquier agente (`rule_sync`, `baseline_update`, restauraciones), sin tocar el backend ni la PKI. Antes de D86 el secreto se guardaba en claro y no existía revocación asignable (`AgentStatus.revoked` se consulta pero ningún código lo asigna), de modo que un secreto filtrado no podía invalidarse desde el producto. |
| **Mitigación** | El secreto se persiste cifrado con AES-256-GCM (formato `v1:`, nonce aleatorio de 12 bytes por escritura) con el `agent_id` como dato asociado autenticado, de modo que un valor copiado de la fila de un agente a la de otro no descifra. La clave de envoltura (32 bytes) vive fuera de la base, en el volumen nombrado `backend_secrets`: la genera `certs-init` (único generador, nunca sobrescribe), modo `0400`, dueño del usuario del backend; la montan sólo `certs-init` (escritura) y el backend (sólo lectura). El backend no arranca si la clave falta, es ilegible, no mide 32 bytes o tiene permisos más laxos que `0400`/`0600`. Los secretos existentes se envuelven en el primer arranque, sin intervención manual (D86/RN-180). |
| **Límites declarados** | (1) No protege contra el compromiso del host ni del proceso del backend: quien lee la memoria del backend o el volumen `backend_secrets` obtiene la clave. (2) No protege contra un respaldo conjunto de la base y de la clave: `backend_secrets` debe respaldarse por separado de `pg_data`. (3) Sin rotación de la clave de envoltura (el prefijo `v1:` queda reservado para una versión futura). (4) Sin revocación de agentes: asignar `AgentStatus.revoked` queda fuera de D86. (5) La pérdida de la clave obliga a re-bootstrapear todos los agentes; no hay vuelta atrás a una imagen anterior sin re-bootstrap (no se provee reescritura a texto plano). |
| **Referencias** | D86/RN-180 (`docs/arquitectura_stack.md`, `docs/reglas_de_negocio.md`), change `agent-secret-wrap-at-rest` (Change 68), procedimiento operativo en `docs/despliegue_servidor_remoto.md` §12 |
