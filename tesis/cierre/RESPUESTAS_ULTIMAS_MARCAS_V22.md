# Últimas marcas [PENDIENTE] de la v22 — respuestas

Cierra las marcas 3 y 4 de la ronda final. Quedan tres, y las tres exigen una decisión humana que
ningún archivo del repositorio puede suplir.

---

## Marca 4 — Anexo F: motivo de la exclusión de los dos paquetes `final-consolidated`

**Resuelto.** El motivo consta en el historial y el párrafo para el Anexo F ya estaba redactado en
`tesis/cierre/DATOS_PARA_TESIS_V15.md`.

El `.gitignore` excluyó la serie el 2026-09-15 (`918b16b`). El 2026-09-19 (`214b93a`) se abrieron
excepciones para los dos paquetes que la tesis sí usa, dejando constancia de la razón: el resto son
**dos corridas que no completaron** —una de ellas abortada al detectarse el árbol de trabajo sucio— y
**dos consolidaciones previas que las posteriores superan**. Ninguna sustenta un resultado del
documento.

### Texto listo para el Anexo F

> Las restantes corridas de esa serie quedan fuera del repositorio por regla explícita: dos intentos
> que no completaron —`final-consolidated-v10-20260912T205729Z-attempt1-failed` y
> `final-consolidated-v10-20260912T210821Z-aborted-dirty-worktree`, este último interrumpido al
> detectarse el árbol de trabajo sucio— y dos consolidaciones previas superadas por las posteriores,
> `final-consolidated-20260911T214511Z` y `final-consolidated-fixed-20260911T225314Z`. Ninguna
> sustenta un resultado del documento. Su exclusión es una decisión de higiene del repositorio y no
> una omisión: se deja constancia de su existencia porque forman parte del registro de cómo se llegó a
> la corrida consolidada, y sus manifiestos quedan disponibles a pedido. Por la misma regla y con el
> mismo criterio permanece excluida la serie `a4-vps-*`.

**Una corrección respecto del texto original de `DATOS_PARA_TESIS_V15.md`**: aquél declaraba excluidas
también las familias `us02-us20-us31-*` y `us03-us16-us17-us25-isolated-*`. Eso ya no es cierto.
Verificado en `main`:

| Familia | Estado en `main` |
|---|---|
| `a4-vps-*` | Excluida (0 archivos) |
| `us02-us20-us31-*` | **Versionada (59 archivos)** |
| `us03-us16-us17-us25-*` | **Versionada (24 archivos)** |
| Los cuatro `final-consolidated` sin excepción | Excluidos (0 archivos) |

---

## Marca 3 — §3.7: sistema operativo del equipo físico el 19/08/2026

**Resuelto, y la frase actual tiene dos errores, no uno.** Hoy dice «Ubuntu Server 24.04 LTS».

### Evidencia

| Comprobación | Resultado |
|---|---|
| Fecha de instalación del sistema | **2026-06-19** (marca de creación de `/lost+found`) |
| Entradas con sufijo `ubuntu0.24.04` en todo el historial de apt, desde 2026-04-23 | **0** |
| Entradas con sufijo `ubuntu0.26.04` en el mismo historial | 22 |
| Ejecuciones de `do-release-upgrade` o `ubuntu-release-upgrader` | **ninguna** |
| Versión declarada en `/etc/os-release` | Ubuntu **26.04.1 LTS** (Resolute Raccoon), `VERSION_ID="26.04"` |
| Metapaquete instalado | `ubuntu-desktop` 1.570.3. **`ubuntu-server` no está instalado** |
| Sesión gráfica | `ubuntu:GNOME` |

### Los dos errores

1. **La versión.** El equipo se instaló en junio de 2026 ya con 26.04 y **nunca se actualizó de
   versión**: no hay una sola traza de 24.04 en el historial de paquetes ni ninguna ejecución del
   actualizador de versión. El 19/08/2026 corría 26.04.
2. **La edición.** No es Ubuntu Server. Es la edición de escritorio, con GNOME, LibreOffice y
   navegadores instalados.

### Texto sugerido para §3.7

> El servidor central ejecuta **Ubuntu 26.04.1 LTS**, edición de escritorio, sobre el núcleo
> 7.0.0-31-generic y un sistema de archivos ext4 en `/dev/nvme0n1p2`.

Esto es coherente con lo que ya informa el paquete de evidencia del candidato vigente
(`v2-eval-20260923T215624Z/env/uname.txt` y `env/fs.txt`) y con la respuesta al punto 14 de
`RESPUESTAS_PENDIENTES_V22.md`. Conviene revisar si la misma afirmación aparece en otros apartados y
alinearla.

### Cómo se reproduce

```bash
rg PRETTY_NAME /etc/os-release
dpkg -l ubuntu-desktop ubuntu-server
zcat -f /var/log/apt/history.log* | rg -c 'ubuntu0\.24\.04'   # -> 0
zcat -f /var/log/apt/history.log* | rg -c 'do-release-upgrade' # -> ninguna
```

---

## Marca 5 — Cap. 11: qué es la fecha de consulta de AIDE

**No se resuelve desde el repositorio**, pero conviene aclarar qué se está pidiendo, porque es una
formalidad bibliográfica y no un dato técnico.

La referencia se cita como **«(s. f.)»**, es decir, sin fecha de publicación. Cuando una fuente en
línea no la tiene, APA 7 §9.16 exige indicar **cuándo se la consultó**, porque su contenido puede
cambiar y el lector necesita saber qué versión se leyó.

Forma final:

> AIDE Project. (s. f.). *AIDE manual* (versión 0.16.2). Recuperado el [día] de [mes] de 2026, de
> [URL]

Sólo lo sabe quien abrió esa página. Si no se recuerda la fecha exacta, es admisible y honesto
consignar aquella en que se verificó la referencia por última vez.

**Observación adicional, de una auditoría previa**: la auditoría V6 ya había señalado que **AIDE está
enlazada mediante un espejo no oficial**. Si se va a tocar esa entrada, conviene aprovechar para
apuntarla al sitio oficial del proyecto.

---

## Lo que queda, y por qué no puede resolverlo el repositorio

| # | Marca | Quién |
|---|---|---|
| 1 | Declaración de originalidad, párr. 2 | Equipo — **bloqueante de entrega** |
| 2 | §9.1.2 | Equipo — **bloqueante de entrega** |
| 5 | Fecha de consulta de AIDE | Quien consultó la fuente |

La marca 6 —la página de la Tabla 30 en el índice— la resuelve Word al regenerar los índices, después
de aceptar los cambios.

Las marcas 1 y 2 **no deben escribirse con asistencia de IA**: una declaración sobre el uso de IA
redactada por una IA es exactamente la clase de cosa que un tribunal detecta y castiga. Lo que sí
corresponde aportar es la lista de usos, que ya está en `RESPUESTAS_PENDIENTES_V22.md`, punto 1, e
incluye la redacción de esta propia versión.
