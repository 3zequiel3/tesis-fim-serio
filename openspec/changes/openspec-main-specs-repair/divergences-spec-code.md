# Divergencias spec ↔ código

Los 48 requisitos se restituyeron con su texto histórico. Esa fidelidad revivió requisitos que
describían comportamiento que el código abandonó después, sin que nadie hubiera escrito nunca un
bloque `## REMOVED Requirements`.

Este documento registra el barrido completo y la resolución de cada divergencia.

**Estado**: barrido completo de los **244 requisitos** de las 43 specs. Tres divergencias de
documentación **corregidas**, y **una funcional escalada** como change 50 — no se corrige editando
texto porque falta código, no falta redacción.

`scripts/check_spec_integrity.py` en verde, `openspec validate --specs` en 43/43, y ninguna
prohibición técnica de las specs es violada por el código.

---

## Método del barrido

Se revisaron los **60 requisitos** de las 9 capabilities del agente, extrayendo de cada uno las
afirmaciones verificables:

| Clase | Encontradas | Divergentes |
|---|---:|---:|
| Prohibiciones (`MUST NOT` / `SHALL NOT`) | 14 | **1** |
| Librerías y versiones citadas | 6 citas | **4 requisitos** |
| Módulos `agent/*.py` referenciados | 9 | 0 |
| Paths absolutos citados | 28 | 0 |

Los paths que un escaneo ingenuo marcó como ausentes resultaron falsos positivos: unos son ejemplos
de escenario (`/etc/deleted_file`, `/var/log/app.log`), otros se construyen desde
`AgentConfig` (`baseline_dir`, `queue_dir`, `journal_dir`) o están literalmente en `agent/config.py`
(`secrets_dir`, `certs_dir`).

---

## Divergencia resuelta — el clúster fanotify

Cuatro requisitos afirmaban que el detector usa `pyfanotify 0.3.0` y **prohibían** el reporte FID.
El código hace exactamente lo contrario desde `f1e8681`.

### El hallazgo que definió la resolución

El requisito viejo no estaba meramente desactualizado: **era irrealizable desde su redacción**.

Exigía las máscaras `FAN_CREATE | FAN_DELETE | FAN_MOVED_FROM | FAN_MOVED_TO` sobre una marca de
filesystem, **y** prohibía `FAN_REPORT_DFID_NAME`. Pero el modo fd clásico (`FAN_CLASS_NOTIF` sin
FID) **no admite** esos eventos sobre una marca de filesystem: el kernel responde `EINVAL`. Pedía
eventos que su propio mecanismo no puede entregar.

Por eso **manda el código**, y no por antigüedad: la spec pedía algo imposible.

El modo FID además habilita algo que el requisito necesitaba y no podía tener — reconstruir el path
de un archivo **ya borrado**, vía el handle del directorio padre más el nombre. Con un fd del objeto
es imposible, porque para entonces el objeto no existe. Eso es lo que hace viable `file_absent`.

### Qué se corrigió

**Decisión de appendix** — `D46/RN-140` en `docs/reglas_de_negocio.md`, que documenta el backend
propio, el argumento del kernel y la capability adicional que arrastra.

**Reglas canónicas:**

| Ubicación | Antes | Ahora |
|---|---|---|
| RN-01 | «mediante `pyfanotify`» | backend propio `agent/_fanotify.py`, ctypes, modo FID |
| RN-110 §Resolución de path | «No se usa `FAN_REPORT_DFID_NAME`… pyfanotify resuelve vía `/proc/self/fd`» | modo FID con `open_by_handle_at(2)`, más el motivo del `EINVAL` |
| `arquitectura_stack.md` §Stack | `Python + pyfanotify \| 0.3.0` | backend propio, sin versión de librería |
| `CLAUDE.md`, `openspec/config.yaml` | `pyfanotify 0.3.0`, `CAP_SYS_ADMIN` | backend propio, `CAP_SYS_ADMIN` + `CAP_DAC_READ_SEARCH` |

**Requisitos normativos:**

| Capability | Requisito | Corrección |
|---|---|---|
| `agent-fanotify-detector` | Marcado `FAN_MARK_FILESYSTEM` | Modo FID **obligatorio**, con el argumento del `EINVAL`. Se eliminó el `MUST NOT` |
| `agent-fanotify-detector` | Eventos con path nulo | «pyfanotify entrega» → el backend; el escenario habla de resolución vía `open_by_handle_at(2)` |
| `agent-core` | Install script | El escenario afirmaba `pip show pyfanotify` → `0.3.0`. Ahora afirma que **NO** está instalado |
| `agent-core` | Systemd capability hardening | Declaraba sólo `CAP_SYS_ADMIN`. El unit real declara cinco; `CAP_DAC_READ_SEARCH` la exige `open_by_handle_at(2)` |

### Verificación

```
spec: `FAN_CLASS_NOTIF | FAN_REPORT_DFID_NAME` — modo FID
code: agent/_fanotify.py:132  flags |= FAN_REPORT_DFID_NAME          ✓

spec: AmbientCapabilities=CAP_SYS_ADMIN CAP_DAC_READ_SEARCH CAP_DAC_OVERRIDE CAP_FOWNER CAP_CHOWN
unit: agent/deploy/fim-agent.service:32  (idéntico)                  ✓

prohibiciones técnicas violadas por el código: NINGUNA               ✓
```

---

## Por qué el desalineamiento existió tanto tiempo

Vale registrarlo, porque es la parte instructiva.

El reemplazo de `pyfanotify` **sí se documentó** cuando ocurrió — en `docs/operations.md` y en
`docs/valores_planillas_cap5.md`, que describen el backend propio con precisión. Lo que no se
actualizó fueron las reglas de negocio, el stack de arquitectura y las specs.

Y las specs del agente llevaban meses **vaciadas** por archives defectuosos: el requisito que
contradecía al código era literalmente **invisible** para `validate`, `list` y `archive`. Nadie podía
tropezárselo. Sólo apareció al recuperarlas.

O sea: el daño estructural de las specs no sólo escondía requisitos — escondía **contradicciones**
entre lo especificado y lo construido. Esa es la razón por la que la guarda de `D47/RN-141` importa
más que la prolijidad del formato.

---

## Candidatos débiles descartados

Tres identificadores que un escaneo automático marcó como ausentes del código, verificados uno por
uno y descartados:

| Capability | Identificador | Veredicto |
|---|---|---|
| `agent-core` | `state.json.tmp` | Falso positivo: se construye concatenando el sufijo `.tmp` |
| `agent-core` | `cap_sys_admin` | Falso positivo: aparece en mayúsculas; el escenario cita la salida de `capsh --decode`, que es minúscula |
| `agent-fanotify-detector` | `pending_paths` | Falso positivo: nombre interno de la estructura de deduplicación |

## Limitación del escaneo automático — sigue vigente

**El escaneo automático no detectó la divergencia real.** Falló por dos motivos que acotan cuánta
confianza merece cualquier herramienta parecida:

1. El requisito citaba `` `pyfanotify 0.3.0` `` — con la versión adentro del backtick, así que no
   matchea un patrón de identificador.
2. `FAN_REPORT_DFID_NAME` **sí estaba** en el código; lo que divergía no era su ausencia sino su
   **uso invertido** respecto de lo que el requisito prohibía. Ninguna búsqueda por presencia
   detecta eso.

Lo que sí funcionó fue extraer las **prohibiciones** (`MUST NOT` / `SHALL NOT`) y contrastar su
polaridad contra el código. Esa técnica está ahora aplicada a las 14 prohibiciones de las specs del
agente y es la que conviene repetir ante futuras recuperaciones.


---

# Segunda pasada — los 98 requisitos que estuvieron invisibles

La primera pasada cubrió los 60 requisitos de las 9 capabilities del agente que **recuperaron
contenido**. Quedaban 98 requisitos en 22 specs que estuvieron **truncados** por el daño estructural:
nadie pudo contrastarlos contra el código durante meses porque el parser no los veía. Misma condición
que produjo el caso fanotify, así que merecían el mismo barrido.

| Clase de afirmación | Revisadas | Divergentes |
|---|---:|---:|
| Prohibiciones (`MUST NOT` / `SHALL NOT`) | 5 | 0 |
| Endpoints HTTP citados | 33 | **1** |
| Identificadores en backticks | 9 sospechosos | **2** |

## Divergencia FUNCIONAL — escalada como change 50

**`POST /agents/renew` no existe en el backend, y el agente lo llama.**

`agent/__main__.py:82` arma un cliente mTLS y hace `POST {backend_url}/agents/renew` cuando el
certificado vence en ≤ 15 días. El router de agents no expone esa ruta, y una búsqueda literal de
`renew` en `backend/` no devuelve una sola ocurrencia real. El agente recibe 404, loguea
`cert_renewal.backend_error` y sigue el loop: **los certificados nunca se renuevan.**

No se resuelve editando la spec. **La spec tiene razón y falta el código** — implementarlo es emitir
certificados mTLS contra la CA propia, que es trabajo sensible y merece su propia change con su
propio diseño. Registrada como **change 50 `backend-agent-cert-renewal`**.

## Divergencias de documentación — corregidas

| Capability | Decía | Es |
|---|---|---|
| `backend-approve-reject` | `_upsert_baseline_entry` | `upsert_baseline_entry` — la función dejó de ser privada |
| `backend-agents` | «sin actualizar `last_seen`» | el campo es `last_heartbeat` |

## Falsos positivos verificados uno por uno

Vale registrarlos, porque tres son **prohibiciones correctamente satisfechas** — la ausencia del
identificador *es* el cumplimiento del requisito, y un escaneo ingenuo las reporta al revés:

| Identificador | Por qué está ausente |
|---|---|
| `dangerouslySetInnerHTML` | El requisito es «DiffViewer seguro **sin** dangerouslySetInnerHTML» |
| `localStorage`, `sessionStorage` | El requisito exige el token **en memoria**, no en storage |
| `failed_notifications` | Tabla **eliminada** por D6/RN-107 en favor de `alerts` |
| `NoSuchTableError` | El escenario afirma que `create_all()` **no** la lanza |
| `stream_id` | Prosa genérica; el campo real, `last_stream_command_id`, existe con su default `"0-0"` |
| `Dockerfile` | `frontend/Dockerfile` existe; mi corpus no incluía archivos sin extensión |
| `GET /health/components` | Declarado con `@app.get` en `main.py:125`, no vía `@router` |
| `POST /register` | Abreviatura en prosa de `/agents/register`, que existe |

## Cobertura final

| Conjunto | Requisitos | Estado |
|---|---:|---|
| Recuperados (9 capabilities del agente) | 60 | Barridos — 1 divergencia, resuelta |
| Invisibles por truncamiento (22 specs) | 98 | Barridos — 3 divergencias, 2 resueltas + 1 escalada |
| Visibles todo el tiempo | 86 | **No barridos** — riesgo menor: un `validate` los estuvo mirando |
| **Total** | **244** | |
