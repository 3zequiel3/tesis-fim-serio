# Hallazgos sobre el documento de tesis (`docs/Tesis.pdf`)

Producto de la tarea 6.2. **No se modifica el PDF** —es el documento compilado— sino que se registra
lo encontrado para que se corrija en la fuente antes de la defensa.

---

## Lo que se temía y NO ocurre

La preocupación registrada era que la tesis citara las specs de `openspec/specs/` como evidencia del
contrato del agente, en cuyo caso las citas habrían apuntado a archivos vaciados durante meses.

**No ocurre.** El PDF tiene **cero menciones** a `openspec`. La inquietud era infundada y conviene
decirlo derecho en lugar de dejarla flotando.

---

## Lo que sí apareció — `pyfanotify` en cuatro lugares del PDF

El agente **no usa** `pyfanotify`: no hay un solo `import`, `agent/requirements.txt` lo excluye
explícitamente, y el commit `f1e8681` lo reemplazó por un backend propio en modo FID (D46/RN-140).

El documento afirma lo contrario en cuatro lugares, y uno es una cita bibliográfica formal:

| Ubicación | Texto |
|---|---|
| **Agradecimientos** | «los mantenedores de los proyectos FastAPI, SQLModel, PostgreSQL, Valkey, **pyfanotify** y n8n, sin cuya existencia la presente tesis no habría sido posible» |
| **Cuerpo (§ detección)** | «adopta fanotify como subsistema primario **mediante el wrapper de Python denominado pyfanotify, en su versión 0.3.0** publicada en julio de 2024 y mantenida activamente, con licencia MIT, con implementación nativa en lenguaje C y documentación vigente. Se descartó el wrapper alternativo…» |
| **Tabla de stack** | «Agente de monitoreo — Python + **pyfanotify** — **3.12** + 0.3.0» |
| **Bibliografía** | «Pyfanotify Contributors. (2024). pyfanotify 0.3.0: Linux fanotify Python wrapper. PyPI. https://pypi.org/project/pyfanotify/» |

El del cuerpo es el más delicado: no sólo nombra la librería sino que **justifica su elección** —
licencia, implementación en C, mantenimiento activo — y menciona haber descartado una alternativa.
Es una decisión de diseño argumentada sobre una premisa que el sistema no cumple.

**Severidad**: un evaluador que lea ese párrafo y después abra `agent/requirements.txt` encuentra una
contradicción directa, con una entrada de bibliografía respaldando la afirmación equivocada.

## Discrepancia adicional — versión de Python

La tabla de stack del PDF dice **Python 3.12**. `agent/Dockerfile` fija `python:3.13-slim` en las dos
etapas, y el stack canónico declara 3.13. Menor comparado con lo anterior, pero está en la misma
tabla.

---

## Qué corregir en la fuente

1. **Cuerpo**: reemplazar la justificación de `pyfanotify` por la del backend propio en modo FID, con
   el argumento técnico que lo hace obligatorio y no preferido — el modo fd clásico no entrega
   `FAN_CREATE`/`FAN_DELETE`/`FAN_MOVED_*` sobre una marca de filesystem, el kernel responde `EINVAL`,
   y el modo FID además permite resolver el path de un archivo ya borrado, que es lo que hace viable
   `file_absent`. El argumento es **más fuerte** que el original, no una excusa.
2. **Tabla de stack**: backend propio, y Python **3.13**.
3. **Bibliografía**: reemplazar la entrada de pyfanotify por `fanotify(7)` de man7.org, que es la
   fuente que el backend propio efectivamente implementa.
4. **Agradecimientos**: es la única mención discutible. Si el proyecto se apoyó en pyfanotify durante
   parte del desarrollo, agradecerlo es legítimo; si nunca se usó, corresponde sacarlo.
5. **Declarar el cambio** de `n8n 2.16.1` a `2.17.8` (D45/RN-139), sin tocar los valores medidos del
   Capítulo 5, que registran contra qué versión se midió.

Todo esto ya está corregido en la documentación del repositorio (D46/RN-140 y las 11 menciones de
`arquitectura_stack.md`). Falta el PDF.
