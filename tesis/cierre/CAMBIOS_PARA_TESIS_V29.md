# Cambios para la tesis — V29 (frente de laboratorio cerrado en código)

> Handoff del frente de laboratorio al frente de redacción, según el último apartado de la guía de
> laboratorio v29. Lista qué cambió en el producto y en el repositorio y qué tiene que cambiar en el
> texto. **No contiene resultados del Capítulo 5**: los valores salen de las baterías B-0…B-7 sobre
> `v5.0-tesis`, que todavía no se corrieron. No reemplaza la redacción del equipo; en particular, la
> declaración sobre el uso de IA la escribe el equipo (ver §4).

## 0. Estado

| Ítem | Estado |
|---|---|
| Changes 61–69 (L-2…L-9) | Aplicadas, verificadas y archivadas el 2026-10-02 en `devel` |
| Decisiones | D79–D88 / RN-173–RN-182 en los appendices de `docs/arquitectura_stack.md` y `docs/reglas_de_negocio.md` |
| L-10 | Descartado: se ratifica RN-94 (D88/RN-182) |
| Arnés (L-11…L-14) | Versionado en `lab/` y actualizado; análisis A-1…A-3 en `scripts/` |
| Candidato `v5.0-tesis` | **No etiquetado todavía** (falta la migración AOF en los volúmenes reales y la puesta en marcha de B-0) |

## 1. Defectos corregidos (para §4 y §7.6)

| Guía | Change | Qué se corrigió | Decisión |
|---|---|---|---|
| L-2 | 61 `agent-publisher-fifo-reconnect` | El publicador entrega en FIFO estricto tras la reconexión: cola separada de nunca transmitidos, la pasada se corta ante el primer error, sondeo de 0,5 s con atraso, el replay de `rehydrate` va detrás del backlog. Explica los 359 eventos fuera de orden de `v4.0-tesis` run-03. | D79/RN-173 |
| L-3 | 62 `agent-offline-reconcile-on-start` | **Hallazgo nuevo de seguridad**: el agente reconcilia la línea base contra el disco al arrancar y reporta lo modificado, borrado o creado con el agente detenido (`detected_offline: true`). | D80/RN-174 |
| L-4 | 63 `agent-restore-verify-from-disk` | La verificación posterior a la restauración relee el disco en **ambos** caminos (automático y del operador); antes comparaba el buffer consigo mismo. Retirado el residual §1. | D81/RN-175 |
| L-5 a,b,d | 64 `quarantine-baseline-preservation` | La cuarentena conserva la versión aprobada (estado de línea base `quarantined`), suprime su propio eco y tiene una sola implementación. Retirado el residual §9. | D82/RN-176 |
| L-5 c | 65 `quarantine-release-command` | Comando firmado de liberación: `restore_original` (= aprobar), `restore_baseline`, `discard`; endpoint auditado y botón en el detalle. | D83/RN-177 |
| L-6 | 66 `backend-schema-migrations-registry` | Registro `schema_migrations`, `scripts/migrar.py` y aborto del arranque ante migraciones pendientes. | D84/RN-178 |
| L-7 | 67 `ingest-token-bucket-rate-limit` | Límite de ingesta como token bucket por agente: 100 ev/min sostenidos, ráfaga de 3.000 (cubre el replay de 2.672 eventos de la batería 5). Las baterías corren con los valores del producto. | D85/RN-179 |
| L-8 | 68 `agent-secret-wrap-at-rest` | Secretos HMAC por agente cifrados en reposo (AES-GCM, clave fuera de la base). | D86/RN-180 |
| L-9 | 69 `ingest-drain-resilience-and-throughput` | Timeouts del cliente Valkey, recuperación de `NOGROUP` (eventos y `command_ack`), AOF, caché de autenticación y ACK por lote. INSERT agrupado **no implementado** por decisión (§2). | D87/RN-181 |

**Decisiones de producto tomadas por el equipo** (para la redacción de §4 y la Tabla 8):

- La máquina de estados de eventos **no cambia**: un rechazo con cuarentena sigue en `rejected`; la
  cuarentena se expone como `quarantine_state` derivado (`none | quarantined | released | discarded`).
  Esto reemplaza la alternativa de la guía L-5(d) de mover el rechazo a `quarantined`.
- Liberar con `restore_original` **equivale a aprobar** el contenido cuarentenado.

**Límites declarados que siguen en pie** (van como límite definitivo, no como pendiente): sin rotación
de la clave de envoltura; pérdida de la clave ⇒ re-bootstrap de todos los agentes; sin vuelta atrás del
agente sin limpiar las entradas `quarantined`; artefactos de cuarentena anteriores a la Change 64 no
liberables; ventana entre la reconciliación y la instalación de las marcas de fanotify; archivos de
más de 10 MiB sin modificación aprobada se re-reportan en cada reinicio; un archivo recreado con el
contenido aprobado pero con otros permisos no se reporta (el detector compara hashes).

## 2. Resultados de desarrollo y decisiones de medición

- **Caudal de ingesta (banco en proceso, no laboratorio).** 100,9 ev/s base → 155,7 con caché →
  191,5 con caché + ACK por lote (`openspec/changes/archive/2026-10-02-ingest-drain-resilience-and-throughput/mediciones.md`).
  Estos números **no** son resultados de la tesis; el valor válido sale de B-4. Con el factor
  laboratorio/banco observado (~0,75) se estiman ~145 ev/s, por eso no se implementó el INSERT agrupado.
- **Tramo sin consumo de L-9a.** Causa probable identificada en el **arnés**: `lab/bateria5.sh`
  restauraba con `up -d valkey backend` usando un conjunto de archivos compose distinto del que levantó
  el backend, lo que recreaba el backend en medio del corte. Corregido (`--no-recreate valkey`, conjunto
  único, Id del contenedor antes y después; la repetición se invalida si cambia). B-4 lo confirma o lo
  descarta: hay que informar en §5.5 cuál de las dos.
- **AOF de Valkey.** Activar AOF sobre un volumen con sólo `dump.rdb` en Valkey 9.0.3 **no carga el
  snapshot** (se pierden stream y grupo). Migración segura documentada en el design de la Change 69.
- **Definición de «fuera de orden» (A-2).** Un evento cuenta si su `detected_at` es menor que el máximo
  ya recibido; con esa definición `scripts/fuera_de_orden.py` reproduce 359 en `v4.0-tesis` run-03. Si
  la tesis la define distinto, alinear el texto a esta.
- **Réplica del control (L-12).** Semillas 20261001/02/03 y fase del control derivada de la semilla
  (243, 164 y 28 s); ya no es una réplica determinista.
- **Retención (L-10).** `audit_log` no se depura nunca (RN-94); `rejected_events_audit` sí, a los 90
  días (`backend/app/modules/events/service.py:540`). **Corregir las Tablas 24 y 25 y §4.2**: la Tabla
  24 dice que no se encontró depuración automática de `rejected_events_audit`, y eso es falso.

## 3. Texto nuevo que hace falta

1. **L-3 en §2.6 o §4.3 (diseño) y en §5 (resultado de B-5b).** Responde a la pregunta obvia del
   tribunal: ¿qué pasa si alguien detiene el agente, modifica y lo reinicia? Antes: nada. Ahora: el
   arranque lo reporta con `detected_offline: true`.
2. **Fila STRIDE para la Tabla 3** (secreto HMAC por agente): texto listo en
   `openspec/changes/archive/2026-10-02-agent-secret-wrap-at-rest/stride-handoff.md`.
3. **B-5 caso D (§1.7 y §2.6).** La ventana de evasión por `mmap` pasa de limitación potencial a cota
   medida en función de la demora d (0…500 ms), cuando corra B-5.
4. **§3.6.** Declarar que el bootstrap del P99 con n = 500 es aproximado (depende de ~5 observaciones
   extremas) y que por eso se informan también las tres repeticiones por separado.

## 4. Anexo F y rutas (L-1)

- **Registro de uso de IA.** No existe `tesis/cierre/REGISTRO_USO_IA.md` y **no se crea**: el
  inventario de hechos es `tesis/cierre/INSUMO_REGISTRO_USO_IA.md`, y la declaración la redacta el
  equipo. El Anexo F debe citar el INSUMO.
- **`VERIFICACION_CITAS.md`.** No existe en ninguna rama ni hay un documento equivalente. **Retirar la
  mención** del Anexo F.
- **Paquetes citados que estaban fuera del repositorio** (`v10-closure-*/{backlog,lanes,m8,m9}`,
  `us02-us20-us31-*`, `us03-us16-us17-us25-isolated-*`): ahora versionados (`1eb8681`).
- **`tesis/resultados/`** sigue fuera del repositorio a propósito (se archiva con las planillas del
  Anexo F). Toda cita como ruta del repositorio (por ejemplo `tesis/resultados/entorno.txt`) debe
  pasar a citar la planilla.
- **Rutas de `~/fim-lab`.** El arnés está en `lab/`: reemplazar toda mención a `~/fim-lab` por `lab/`.
- **Falsos positivos del verificador** contra la v26 (`docs/18`, `docs/concepts/tracing-policy/selectors`,
  `agent/baseline`): son fragmentos de URLs o de texto, no rutas. Revisarlos al pasar
  `scripts/verificar_rutas_tesis.py` sobre la versión final; también falta `scripts/verify_experiments.py`,
  que no existe en el repositorio: retirar esa cita o reemplazarla por el script vigente.
- El Anexo F cita **sólo** la etiqueta `entrega-tesis`, que se crea al final, después de fusionar `devel`
  en `main`. Hecho cuando `verificar_rutas_tesis.py Tesis_vNN.docx entrega-tesis` da cero faltantes.
