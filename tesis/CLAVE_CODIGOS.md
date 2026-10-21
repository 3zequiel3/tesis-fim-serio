# Clave de los códigos de los mensajes de commit

Este archivo acompaña el párrafo «Códigos de los mensajes de commit» del Anexo F del
documento (hallazgo T-1 de la devolución del 19/10/2026). Para cada commit posterior a
la etiqueta `entrega-tesis` consigna el código que cita su mensaje, el documento del que
procede, la fecha de ese documento y su autor.

**Solo dos familias proceden del tribunal:** N-1 a N-10 (devolución del 09/10/2026) y
T-1 a T-9 (devolución del 19/10/2026). Las demás son documentos de los autores, varios
elaborados con la herramienta declarada en el apartado 9.1.2. Ninguno de ellos es un
documento del tribunal.

Las fechas y los autores de los commits salen de
`git log entrega-tesis..entrega-tesis-v9 --format='%h|%ad|%an|%s'`; los mensajes no se
reescribieron.

## Familias de códigos

| Familia | Documento | Fecha | Autor |
|---|---|---|---|
| P-n | Puntos de reproducibilidad P-1 a P-12 (Anexo F.3 del documento) | — | Autores |
| N-n | Devolución de la primera corrección (hallazgos N-1 a N-10) | 09/10/2026 | Tribunal |
| C-n | Plan de corrección C-1 a C-5, derivado de la devolución del tribunal del 09/10/2026 | 10/10/2026 | Autores, con la herramienta (Claude Opus 5.5, claude.ai) |
| NS-n | Revisión con observaciones NS-1 a NS-3, sobre la versión que no reflejaba los commits del 18/10 | 19/10/2026 | Autores, con la herramienta (Claude Opus 5.5, claude.ai) |
| PC-n | Plan de corrección PC-1 a PC-13, sobre la versión de entrega-tesis-v8 | 19/10/2026 | Autores, con la herramienta (Claude Opus 5.5, claude.ai) |
| T-n | Devolución de la segunda corrección (hallazgos T-1 a T-9) | 19/10/2026 | Tribunal |

## Commits de entrega-tesis a entrega-tesis-v9

| Commit | Fecha | Firma | Código | Documento | Fecha del documento | Autor del documento |
|---|---|---|---|---|---|---|
| b98899d | 18/10/2026 21:44 | Nicolás Castro | — | Sin código (correcciones de octubre; Anexo F.3) | — | — |
| 3461683 | 18/10/2026 21:57 | Nicolás Castro | — | Sin código (correcciones de octubre; Anexo F.3) | — | — |
| 69c937f | 18/10/2026 22:03 | Nicolás Castro | — | Sin código (correcciones de octubre; Anexo F.3) | — | — |
| 15f4c72 | 18/10/2026 22:07 | Nicolás Castro | — | Sin código (correcciones de octubre; Anexo F.3) | — | — |
| 7083d26 | 18/10/2026 22:13 | Nicolás Castro | — | Sin código (correcciones de octubre; Anexo F.3) | — | — |
| 9a6d657 | 18/10/2026 22:25 | Nicolás Castro | P-8 | Puntos de reproducibilidad P-1 a P-12 (Anexo F.3 del documento) | — | Autores |
| dbb4eeb | 18/10/2026 22:31 | Nicolás Castro | P-12 | Puntos de reproducibilidad P-1 a P-12 (Anexo F.3 del documento) | — | Autores |
| 0343980 | 18/10/2026 22:40 | Nicolás Castro | P-9 | Puntos de reproducibilidad P-1 a P-12 (Anexo F.3 del documento) | — | Autores |
| a0edf08 | 18/10/2026 23:25 | Nicolás Castro | P-9 | Puntos de reproducibilidad P-1 a P-12 (Anexo F.3 del documento) | — | Autores |
| d0297f1 | 18/10/2026 23:29 | Nicolás Castro | N-5 | Devolución de la primera corrección (hallazgos N-1 a N-10) | 09/10/2026 | Tribunal |
| 92d096b | 18/10/2026 23:44 | Nicolás Castro | P-10 | Puntos de reproducibilidad P-1 a P-12 (Anexo F.3 del documento) | — | Autores |
| 18cd43a | 19/10/2026 00:46 | Nicolás Castro | C-2 | Plan de corrección C-1 a C-5, derivado de la devolución del tribunal del 09/10/2026 | 10/10/2026 | Autores, con la herramienta (Claude Opus 5.5, claude.ai) |
| f0639c2 | 19/10/2026 01:16 | Nicolás Castro | C-2 | Plan de corrección C-1 a C-5, derivado de la devolución del tribunal del 09/10/2026 | 10/10/2026 | Autores, con la herramienta (Claude Opus 5.5, claude.ai) |
| 38eec74 | 19/10/2026 02:46 | Nicolás Castro | C-2 | Plan de corrección C-1 a C-5, derivado de la devolución del tribunal del 09/10/2026 | 10/10/2026 | Autores, con la herramienta (Claude Opus 5.5, claude.ai) |
| 13c55ee | 19/10/2026 02:46 | Nicolás Castro | C-2 | Plan de corrección C-1 a C-5, derivado de la devolución del tribunal del 09/10/2026 | 10/10/2026 | Autores, con la herramienta (Claude Opus 5.5, claude.ai) |
| 051eed0 | 19/10/2026 03:13 | Nicolás Castro | NS-1 | Revisión con observaciones NS-1 a NS-3, sobre la versión que no reflejaba los commits del 18/10 | 19/10/2026 | Autores, con la herramienta (Claude Opus 5.5, claude.ai) |
| 00a45d0 | 19/10/2026 03:23 | Nicolás Castro | C-3 | Plan de corrección C-1 a C-5, derivado de la devolución del tribunal del 09/10/2026 | 10/10/2026 | Autores, con la herramienta (Claude Opus 5.5, claude.ai) |
| f241e1f | 19/10/2026 03:41 | Nicolás Castro | P-11 | Puntos de reproducibilidad P-1 a P-12 (Anexo F.3 del documento) | — | Autores |
| 6226aaa | 19/10/2026 12:39 | Nicolás Castro | — | Sin código (correcciones de octubre; Anexo F.3) | — | — |
| f1fd574 | 19/10/2026 12:39 | Nicolás Castro | — | Sin código (correcciones de octubre; Anexo F.3) | — | — |
| 57acbf3 | 19/10/2026 13:07 | Nicolás Castro | PC-2 | Plan de corrección PC-1 a PC-13, sobre la versión de entrega-tesis-v8 | 19/10/2026 | Autores, con la herramienta (Claude Opus 5.5, claude.ai) |
| b913b0c | 19/10/2026 13:07 | Nicolás Castro | PC-10 | Plan de corrección PC-1 a PC-13, sobre la versión de entrega-tesis-v8 | 19/10/2026 | Autores, con la herramienta (Claude Opus 5.5, claude.ai) |
| 97614a9 | 19/10/2026 16:41 | Nicolás Castro | PC-4 | Plan de corrección PC-1 a PC-13, sobre la versión de entrega-tesis-v8 | 19/10/2026 | Autores, con la herramienta (Claude Opus 5.5, claude.ai) |

**Nota sobre d0297f1 (N-5).** Su contenido (la guarda de procedencia compara el
contenedor con la etiqueta) corresponde al hallazgo N-5 de la devolución del tribunal del
09/10/2026, de la que se tomó el código, como comprobó el tribunal en la devolución del
19/10/2026.

## Commits de entrega-tesis-v9 a entrega-tesis-v10

| Commit | Fecha | Firma | Código | Documento | Fecha del documento | Autor del documento |
|---|---|---|---|---|---|---|
Se completa en el último commit de la etiqueta, con los commits anteriores a él
(`git log --reverse entrega-tesis-v9..HEAD --date=format:'%d/%m/%Y %H:%M' --format='| %h | %ad | %an |'`).
El último commit, que versiona el documento (P-11), no puede listarse a sí mismo.

| Commit | Fecha | Firma | Código | Documento | Fecha del documento | Autor del documento |
|---|---|---|---|---|---|---|
| [completar] | | | T-1 | Devolución de la segunda corrección | 19/10/2026 | Tribunal |
| [completar] | | | T-5, T-6 | Devolución de la segunda corrección | 19/10/2026 | Tribunal |
| [completar] | | | T-2 | Devolución de la segunda corrección | 19/10/2026 | Tribunal |
