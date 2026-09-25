# Respuestas a los comentarios 2 y 9 de la v24

Los dos datos que el equipo de redacción pidió se pueden responder desde el repositorio. El segundo
contradice el supuesto del pedido.

---

## Comentario 2 — nombre del equipo en el registro del arranque

**Pregunta**: ¿el registro del sistema de ese arranque muestra el nombre del equipo (`Eze-Linux`)?

**Sí, y está ya transcripto en el repositorio.** La línea del registro del núcleo del arranque del 18
de agosto de 2026 es:

```
ago 18 10:55:48 Eze-Linux kernel: Linux version 7.0.0-29-generic (buildd@lcy02-amd64-113)
```

Consta en `tesis/cierre/DATOS_PARA_DECISIONES_V22.md`. El nombre del equipo aparece en la propia línea
del registro, entre la marca temporal y `kernel:`, que es donde `journalctl` consigna el nombre del
anfitrión.

Además, `tesis/cierre/RESPUESTAS_PENDIENTES_V22.md` ya consigna la topología de las dos máquinas:

| | Servidor central | Anfitrión monitoreado |
|---|---|---|
| Nombre | `Eze-Linux` | `fim-host` |
| Sistema operativo | Ubuntu 26.04.1 LTS | Ubuntu 24.04.5 LTS |

**Conclusión para la redacción**: **no hace falta escribir «según los autores»**. El dato tiene
respaldo documental en una línea del registro del sistema, que es una fuente más fuerte que una
declaración de los autores. Conviene citarla textualmente.

---

## Comentario 9 — qué significan las letras C y W del Anexo G

**El pedido dice que «el repositorio no lo dice en ningún lado». Eso es inexacto: los códigos están
en el repositorio, completos y con su contenido.**

Viven en **`docs/arquitectura_stack.md`**, bajo el apartado
**«Appendix: Decisiones de auditoría — Abril 2026»** (a partir de la línea 1770). El apartado declara
su propio origen y su prelación:

> «Las siguientes decisiones resultan de la auditoría de consistencia, lifecycle, seguridad y
> resiliencia realizada el 2026-04-22. En caso de conflicto con secciones previas del documento,
> prevalece lo especificado en este appendix.»

**Inventario real, contado sobre el archivo:**

- **C1 a C11** — once códigos, sin huecos.
- **W1 a W20** — veinte números asignados, pero **`W19` no existe**. Son diecinueve códigos.

Cada uno tiene la misma estructura: **Decisión**, **Motivación** y, en la mayoría, **Aplicación**.

**Cómo se reparten, observado sobre el archivo** (esto es descripción, no definición):

| Prefijo | Apartados en que aparecen |
|---|---|
| **C** | Léxico y nomenclatura, Modelo de eventos y lifecycle, Arquitectura del sistema, Seguridad y criptografía |
| **W** | Seguridad y criptografía, Resiliencia y degradación, Operaciones, Frontend |

Ejemplos, para que se vea el tipo de contenido: `C1` fija el léxico canónico en minúsculas; `C4` fija
el backend de instancia única; `W3` fija la cola offline con límite y política; `W13` fija los
timestamps dobles con anti-replay.

### El límite honesto de esta respuesta

**Qué abrevian las letras no está escrito en ninguna parte del repositorio.** Lo busqué: ni el
apartado ni los documentos canónicos ni el historial expanden `C` ni `W`. Por el reparto de apartados
se podría conjeturar, pero una conjetura no es un dato y no corresponde ponerla en una tesis como si
lo fuera.

**Dos opciones para la redacción, ambas defendibles:**

1. **Dejar la remisión y describir lo que sí consta**: que son los códigos de las decisiones de la
   auditoría del 22 de abril de 2026, que están en `docs/arquitectura_stack.md` en el apartado citado,
   que son C1–C11 y W1–W20 sin `W19`, y que el apartado prevalece sobre las secciones previas del
   documento. Eso es verificable línea por línea.
2. **Si el equipo recuerda qué abreviaban**, declararlo como recuerdo de los autores y no como cita
   del repositorio, porque el repositorio no lo respalda.

Lo que **no** conviene es inventar una expansión plausible. Es exactamente el tipo de precisión
aparente que un tribunal puede pedir que se justifique, y no habría con qué.
