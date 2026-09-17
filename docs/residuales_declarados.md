# Residuales declarados

Defectos y deudas **conocidos, acotados y deliberadamente no corregidos**. Cada entrada declara qué
es, dónde vive, por qué no se arregla ahora y qué haría falta para cerrarla.

Un residual declarado no es un pendiente olvidado: es una decisión de alcance tomada con el defecto
a la vista. La alternativa —abrir un change por cada hallazgo mientras se cierra el proyecto— cambia
trabajo acotado por frentes abiertos, y deja la documentación mintiendo sobre el estado real.

Origen: la tarea 15.5 de `agent-deployment-caps` pedía abrir tres changes de follow-up; se optó por
registrarlos acá (2026-09-16). Al mismo tiempo se sumaron los hallazgos de la jornada de
verificación contra el despliegue real del VPS y del host del agente.

---

## 1. La verificación de hash post-restauración es tautológica

**Dónde**: `agent/decision.py:184-186`.

**Qué pasa**: después de restaurar un archivo, el agente calcula el hash del **buffer que tiene en
memoria** y lo compara contra ese mismo buffer, en lugar de releer el archivo del disco. La
comprobación siempre da verdadero por construcción.

**Por qué importa**: es el único punto que afirma "la restauración quedó bien escrita". Una escritura
truncada, un `fsync` que falla silenciosamente o un filesystem lleno producirían un archivo distinto
del baseline y el agente reportaría éxito igual. Es el modo de falla más caro de todos los de esta
lista, porque miente en la dirección peligrosa: dice que el sistema remedió cuando no lo hizo.

**Por qué no se arregla ahora**: releer el archivo tras `os.replace` cambia el camino caliente de la
restauración y exige tests de filesystem nuevos para el caso de escritura parcial, que es
precisamente el que hoy no está cubierto.

**Para cerrarlo**: releer el path restaurado y comparar contra el hash del baseline, con un test que
provoque una escritura truncada real y afirme que la acción reporta fallo.

---

## 2. Los `watch_paths` del host nunca llegan al backend

**Dónde**: `backend/app/modules/agents/service.py:161`, `frontend/src/components/ui/AgentCard.tsx:261`.

**Qué pasa**: `Agent.watch_paths` lo escribe **únicamente** `update_config` desde la consola. Los
paths que `install.sh` configura en el `config.yaml` del host no se reportan nunca. Hasta que un
admin los carga a mano por UI, la tarjeta del agente muestra "Sin paths configurados".

**Por qué importa**: el backend **sí** guarda la clasificación de escritura de cada path
(`watch_path_status`, persistido por el heartbeat en `heartbeat_consumer.py:133-137`), pero la UI
itera sobre `watch_paths` para pintarla. El dato existe y no hay lista sobre la cual mostrarlo: un
agente recién instalado, monitoreando correctamente, se ve en la consola como si no vigilara nada.
Verificado en el VPS el 2026-09-16 con tres agentes registrados, los tres sin paths visibles.

**Por qué no se arregla ahora**: toca el contrato del heartbeat o el del bootstrap, y ambos están
recién estabilizados.

**Para cerrarlo**: que el heartbeat reporte también la lista de paths configurados —con el mismo
criterio tolerante que ya usa para `watch_path_status`—, o que el bootstrap la registre al alta.

---

## 3. nginx cachea la IP del backend y la consola queda en 502

**Dónde**: `frontend/nginx/common-locations.conf` (`proxy_pass http://backend:8000/`).

**Qué pasa**: nginx resuelve el hostname `backend` una sola vez, al arrancar. Cada vez que se recrea
el contenedor del backend, el proxy queda apuntando a una IP que ya no existe y **toda la consola
responde 502** aunque el backend esté sano. Se reproduce sin esfuerzo: pasó dos veces en la misma
jornada de verificación.

**Por qué importa**: pega en la reproducibilidad. Quien siga `docs/REPRODUCIR.md` se topa con un 502
sin explicación y con un backend que responde perfecto en `127.0.0.1:8000`. El diagnóstico es
contraintuitivo y el arreglo temporal —reiniciar el frontend— no es obvio.

**Para cerrarlo**: `resolver 127.0.0.11 valid=30s;` y un upstream por variable en `proxy_pass`, para
que nginx resuelva por request en vez de al arrancar.

---

## 4. El descarte del detector se loguea a nivel `warning`, por evento

**Dónde**: `agent/detector.py` (`detector.out_of_scope_drop`).

**Qué pasa**: cada ruta descartada por estar fuera de scope emite una línea de `warning`. En el host
del agente el contador llegó a **2.748.492** descartes, con el journal inundado.

**Por qué importa**: un FIM cuyo log hay que filtrar para encontrar un evento de integridad tiene un
problema de producto. Además consume disco y puede rotar fuera del journal justamente las líneas que
importan durante un incidente.

**Por qué no se arregla ahora**: toca el agente, y las baterías del Capítulo 5 se miden sobre el
agente. Cualquier cambio ahí obliga a re-medir. **Si se corrige, debe hacerse antes de esa corrida,
nunca después.**

**Para cerrarlo**: bajar el descarte individual a `debug` y conservar el contador agregado, que ya
existe y ya viaja en el heartbeat.

---

## 5. El unit no fija `UMask`

**Dónde**: `agent/deploy/fim-agent.service`.

**Qué pasa**: `systemd-analyze security fim-agent.service` da **6.7 MEDIUM**, y su único ✗ es
`UMask=`: los archivos que el servicio cree sin modo explícito quedan legibles por todos.

**Por qué importa poco hoy**: el agente fija los modos a mano donde importa — 0700 en los directorios
de estado, 0600 en los certificados—, así que la exposición real es acotada. Es defensa en
profundidad, no un agujero abierto.

**Para cerrarlo**: `UMask=0077` en el unit y re-registrar el score.

---

## 6. El detalle del evento no dice que se intentó un `auto_restore`

**Dónde**: `backend/app/modules/events/service.py:188` (`derive_action_type`).

**Qué pasa**: el campo "Tipo de acción" del detalle se deriva **del `status`**, no de la acción que
el agente intentó. Un `auto_restore` fallido deriva a `pending`, y el detalle muestra
`manual_review`.

**Por qué importa**: es correcto por contrato —el campo responde "qué hay que hacer ahora"— pero el
operador ve `manual_review` y tiene que inferir el intento fallido desde el badge de remediación
fallida y su causa. La información está en pantalla; la lectura no es directa.

**Para cerrarlo**: exponer la acción intentada junto a la derivada, sin fusionar los dos conceptos.

---

## 7. `docs/operations.md` afirma que el descarte con contenido es siempre una anomalía

**Dónde**: `docs/operations.md`, sección del directorio de descarte (tarea 17.6 de
`stream-ack-durability`).

**Qué pasa**: la corrida 16.2 del 2026-09-16 encontró un caso benigno. Tras actualizar un agente con
backlog, el directorio de descarte terminó con 11 archivos cuyos `event_id` **estaban los 11
persistidos** en la base: eran copias viejas del stream que recibieron un nack terminal después de
que la copia republicada ya había sido aceptada.

**Para cerrarlo**: matizar la frase con ese caso, para que un operador no lo lea como pérdida de
eventos.

---

## 8. Las etiquetas de estado son el token canónico, sin explicación

**Dónde**: `frontend/src/pages/Dashboard.tsx:153` y la tabla de eventos.

**Qué pasa**: las pantallas rotulan `alert_only`, `auto_restored`, etc. Es **deliberado** (RN-71): el
mismo vocabulario viaja por código, schemas, JSON, logs y UI, de modo que el operador encuentra en
el log exactamente el string que vio en pantalla. Pero a un lector no técnico no le dice nada.

**Para cerrarlo**: agregar descripción o tooltip bajo cada token, **conservando el token como
título**. Renombrarlos exigiría una decisión que modifique RN-71.

---

## 9. Dos implementaciones divergentes de cuarentena

**Dónde**: agente.

**Qué pasa**: la acción de cuarentena está implementada dos veces por caminos distintos.

**Por qué importa**: dos implementaciones del mismo contrato divergen con el tiempo; es la misma
lección de C46 y del contrato agente↔backend que este proyecto ya pagó una vez.

**Para cerrarlo**: unificar en una sola implementación con tests compartidos.

---

## 10. El `cp -r` de `install.sh` no es idempotente

**Dónde**: `agent/install.sh:50`.

**Qué pasa**: una segunda corrida anida el código en `/opt/fim-agent/agent/agent`.

**Por qué importa poco hoy**: el test de integración en contenedor
(`agent/tests/integration/test_install_sh_container.py`) verifica que una segunda corrida deja el
árbol byte-idéntico y reemplaza el código eliminando archivos obsoletos, así que el camino probado
no reproduce el anidamiento. Queda declarado porque la línea sigue siendo frágil.

**Para cerrarlo**: copiar el contenido del directorio en vez del directorio, con un test que corra
`install.sh` tres veces seguidas.
