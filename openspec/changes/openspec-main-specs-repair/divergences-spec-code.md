# Divergencias spec ↔ código entre los requisitos recuperados

Los 48 requisitos se restituyeron con **su texto histórico, sin reescritura**. Esa fidelidad
tiene una consecuencia inevitable: un requisito que describía comportamiento que el código
abandonó después vuelve a estar vigente, y como nadie escribió nunca un bloque
`## REMOVED Requirements` en este repositorio, no hay registro de que se lo haya retirado a
propósito.

Este documento lista las divergencias detectadas. **No se corrigió ninguna acá**: editar el
texto recuperado sería inventar contenido, que es exactamente lo que el change prohíbe.
Resolverlas es trabajo aparte y requiere decidir, caso por caso, si manda la spec o el código.

---

## Confirmada — `agent-fanotify-detector`

**Requisito**: `Marcado FAN_MARK_FILESYSTEM sobre watch_paths con exclusión de /var/lib/fim-agent`

El texto restituido dice:

> «El detector SHALL inicializar un grupo fanotify con **`pyfanotify 0.3.0`** […] El detector
> **MUST NOT usar `FAN_REPORT_DFID_NAME` ni `FAN_REPORT_FID`**: la resolución de path se realiza
> vía `ev.path` que pyfanotify resuelve internamente.»

El código embarcado hace lo contrario, en ambos puntos:

| Afirmación del requisito | Estado real |
|---|---|
| Usa `pyfanotify 0.3.0` | **No.** `agent/requirements.txt:6` dice explícitamente «No se depende de pyfanotify» |
| `MUST NOT` usar `FAN_REPORT_DFID_NAME` | **Lo usa.** `agent/_fanotify.py:132` → `flags \|= FAN_REPORT_DFID_NAME` |

Causa: el commit `f1e8681` (*feat(agent): backend fanotify propio (ctypes, modo FID) reemplaza
pyfanotify*) cambió la implementación. El requisito que lo prohibía nunca se actualizó — porque
para entonces ya había sido borrado de la main spec y era invisible.

**Por qué importa más que un desalineamiento normal**: es un `MUST NOT` normativo, en un artefacto
que la tesis puede citar como contrato del agente, afirmando lo contrario de lo que el sistema
hace. Un evaluador que lo lea y mire el código encuentra una contradicción directa.

**Resolución pendiente**: casi con seguridad manda el código y el requisito debe reescribirse para
describir el backend ctypes en modo FID. Eso es un cambio de contenido normativo y merece su propia
change con su propia revisión, no un parche dentro de una reparación estructural.

---

## Candidatos débiles — identificadores citados que no aparecen en el código

Un escaneo automático buscó identificadores entre backticks en los 48 requisitos recuperados y los
contrastó contra `agent/`, `backend/app/` y `frontend/src/`. Encontró tres:

| Capability | Requisito | Identificador |
|---|---|---|
| `agent-core` | Persistent state with atomic writes | `state.json.tmp` |
| `agent-core` | Systemd service unit with capability hardening | `cap_sys_admin` |
| `agent-fanotify-detector` | Deduplicación en memoria por path con encadenamiento parent_event_id | `pending_paths` |

Los tres son señales débiles y probablemente falsos positivos: `state.json.tmp` se construye
dinámicamente concatenando el sufijo, `cap_sys_admin` aparece en mayúsculas en el código, y
`pending_paths` puede ser un nombre interno que cambió sin alterar el comportamiento. Verificar
uno por uno antes de actuar.

---

## Limitación de este análisis — declararla importa

**El escaneo automático NO detectó la divergencia confirmada de arriba.** Falló por dos motivos que
vale la pena dejar escritos, porque acotan cuánta confianza merece:

1. El requisito cita `` `pyfanotify 0.3.0` `` — con la versión adentro del backtick, así que no
   matchea un patrón de identificador.
2. `FAN_REPORT_DFID_NAME` **sí está** en el código; lo que diverge no es su ausencia sino su
   **uso invertido** respecto de lo que el requisito prohíbe. Ninguna búsqueda por presencia
   detecta eso.

O sea: el caso real lo encontró una lectura adversarial del contenido, no una herramienta. **No hay
que tratar esta lista como cobertura.** Pueden existir más divergencias entre los 48 recuperados, y
la única forma de encontrarlas es leerlos contra el código.

Recomendación: una pasada de reconciliación spec↔código sobre las 9 capabilities reparadas,
priorizando `agent-core`, `agent-fanotify-detector` y `agent-baseline`, que son las que más
requisitos recuperaron y las que más tiempo estuvieron invisibles.
