# Respuestas a las marcas [PENDIENTE] de la v22

Numeración idéntica a la del pedido, para trabajarlo de corrido. Cada dato sale de un paquete sellado
o del repositorio publicado, y se indica de dónde.

**Resuelto aquí: 24 de los 28 puntos.** Los cuatro que no se resuelven necesitan una decisión del
equipo o una corrida nueva, y se marcan como tales.

---

## A. Redacción del equipo

**1. Declaración de originalidad y §9.1.2 — NO SE RESUELVE ACÁ.** La redacta el equipo. Lo único que
corresponde aportar es la lista completa de usos, y hay que agregar uno que el pedido ya identificó
bien: **la producción de la propia v22 es uso de IA y debe declararse**, incluidos los párrafos nuevos
del Cap. 5, del Cap. 6 y del Anexo F. También corresponde declarar la atribución de las operaciones
sin evento, que se produjo con un script escrito con asistencia de IA y cuyo resultado se incorporó al
capítulo.

---

## B. Candidato `v4.0-tesis` — paquete `v2-eval-20260923T215624Z/`

**2. Identidad del candidato.**

| Campo | Valor |
|---|---|
| Etiqueta | `v4.0-tesis` |
| Commit | `1f28c9e5b3ae60199cb25463738ecdfa607189b4` |
| Árbol | `dd3012b105134c88bd9746f08f7f3e2e8aedc588` |

**3. Datos de la corrida.**

- Ventana: **2026-09-23, 21:56 a 23:20 UTC**.
- La verificación de procedencia **se repitió y coincide**: el hash agregado de todo `app/**/*.py`
  dentro del contenedor y el del árbol de trabajo dan ambos
  `c17ec8780ac326098a65c391e58c722fd3e66574fe5b7c593b39145f028c4522` (`provenance_match=yes`). El árbol
  del agente también coincide con la etiqueta (`agent_tree_matches=yes`).
- `git_status_clean=no` **y no es un problema**: el directorio de salida de la propia corrida vive
  dentro del repositorio. Ningún archivo de código está modificado. Conviene escribir esa aclaración,
  porque un `no` sin explicar se lee mal en un anexo de custodia.

**4. Condiciones de la corrida — confirmadas todas**, y con tres controles nuevos que la corrida de
`v3.0-tesis` no tenía:

| Condición | Estado |
|---|---|
| mTLS agente ↔ backend | Sí |
| TLS de Valkey con certificado de cliente en 6380 | Sí |
| Agente nativo bajo systemd en el anfitrión monitoreado | Sí |
| n8n activo como canal primario | Sí, con Mailpit como destino SMTP final |
| Semilla registrada en el manifiesto | Sí |
| Batería 5: 3 repeticiones × 3.000 operaciones, corte de 5 min de **Valkey** | Sí |
| Batería 4: tres escenarios de 1.000 eventos | Sí |

Controles que el arnés ejecutó **antes** de medir, y que conviene declarar porque son el respaldo de
todo lo demás:

- **Esquema contra modelo**: toda columna declarada por los modelos existe en la base.
- **Sumidero de notificación**: el backend resuelve `fim-mailpit` y su API responde.
- **Desvío de reloj**: anfitrión **907 µs**, huésped **971 µs**, contra un techo de 5.000 µs.
  Medido con chrony en ambas máquinas (`System time 0,000907024 s fast` y `0,000971223 s slow`).

**5. Tabla 25 — latencia de detección.**

| Métrica | Valor |
|---|---|
| n | 483 |
| Media | 26,923 ms |
| P50 | 26,536 ms |
| P95 | 35,391 ms |
| P99 | 46,274 ms |
| Mínimo | 11,177 ms |
| Máximo | 102,144 ms |
| Muestras negativas | 0 |

**6. Contraste pareado.**

| Celda | Valor |
|---|---|
| a — ambos detectan | 69 |
| b — sólo FIM | 414 |
| c — sólo control | 9 |
| d — ninguno | 8 |
| Total | 500 |

| Estadístico | Valor |
|---|---|
| Proporción detectada, FIM | 0,9660 (483/500) |
| **Proporción detectada, control** | **0,1560 (78/500)** |
| Diferencia pareada | 0,8100 |
| IC 95 % de Newcombe (pareado) | [0,7671; 0,8440] |
| McNemar con corrección, χ²(1) | 385,8534 |
| **Valor p exacto** | **6,61612 × 10⁻⁸⁶** |

**Recomputación independiente**: el cálculo lo produce `scripts/analisis_mcnemar.py`, publicado y sin
dependencias externas, sobre `control/pareado.csv` del paquete. Cualquiera puede reejecutarlo. Los
datos de control salen de `control/bateria7_latencias.csv`, producido por `scripts/analisis_control.py`.

**7. Notificación.**

| Escenario | Nivel | n | Entregadas | Media | P50 | P95 | P99 | Máx |
|---|---|---|---|---|---|---|---|---|
| secuencial | 1 publicación simultánea | 1000 | 1000 | 13.256,856 | 14.043,574 | 21.687,104 | 22.135,756 | 22.211,400 |
| conc50 | 50 simultáneas | 1000 | 1000 | 12.090,537 | 12.939,007 | 20.520,838 | 20.979,580 | 21.006,211 |
| conc100 | 100 simultáneas | 1000 | 1000 | 9.832,914 | 10.406,837 | 17.104,211 | 17.493,441 | 17.534,554 |

Valores en milisegundos. Intervalo medido: `events.received_at` → `alerts.delivered_at`.

**Advertencia sobre este indicador**, que ya está en el documento de estado y conviene repetir: éste
**no es el intervalo que la Tabla 4 define**. La Tabla 4 pide hasta la aceptación del webhook por su
receptor; lo medido llega hasta `alerts.delivered_at`, que además absorbe la espera por un cupo de
entrega. La columna `channel_accepted_at` existe desde este candidato y registra el instante correcto,
pero **su serie todavía no se midió**.

**8. Resiliencia.**

| Repetición | Encolados | Entregados | Descartados | Duplicados | Fuera de orden | Drenaje |
|---|---|---|---|---|---|---|
| run-01 | 2.672 | 2.672 | 0 | 0 | 0 | 34,050 s |
| run-02 | 2.671 | 2.671 | 0 | 0 | 0 | 35,044 s |
| run-03 | 2.672 | 2.672 | 0 | 0 | 0 | 35,257 s |

- **Rango de drenaje**: 34,050 a 35,257 s. Mediana 35,044 s.
- **Encolados sobre 3.000 generadas**: 2.672, 2.671 y 2.672 respectivamente.
- **Trazas causales**: 65.038, 65.465 y 63.886 registros. Las tres tienen hash distinto y cada una
  comienza dentro de la ventana de su propia repetición. Las tres repeticiones arrancaron con la base
  en `events=0`, verificado por el arnés.

**Sobre la preservación en su definición preregistrada**, que hoy figura «Sin determinar»: con
denominador «generadas» el resultado es **2.672 de 3.000** y **no alcanza** el umbral. Con denominador
«encolados» es 2.672 de 2.672, es decir 100 %, y ésa es la medida complementaria. Hay que informar las
dos, con el preregistrado como criterio y el otro como complemento.

**9. Manifiesto y trazas.**

- `sha256sum` del `SHA256SUMS` de `v4.0-tesis`:
  `1524741d820d647703942b6906ecc9f4f1e052a0b729cf64f2eb1b35287fc92c`
- **Las trazas NO requieren `gunzip -k` antes de verificar.** El sello de este paquete cubre los
  archivos tal como están almacenados, con las trazas ya comprimidas: `sha256sum -c SHA256SUMS`
  funciona directo. (El paquete de `v3.0-tesis` sí lo requiere, porque su sello se emitió antes de
  comprimir; su `CUSTODIA_TRAZAS.md` lo explica.)

**10. Atribución de operaciones sin evento.**

- Script: `scripts/atribuir_operaciones_sin_evento.py`
- Resultado: `tesis/cierre/evidencia/v2-eval-20260923T215624Z/latencia/atribucion_sin_evento.csv`
- El paquete de `v3.0-tesis` tiene el suyo en la ruta equivalente.

---

## C. Suites

**11. Artefacto sellado de cada candidato**: `suites/` dentro del paquete de cada uno, con
`procedencia.txt`, `agente.xml`, `backend.xml`, `frontend.xml` y sus `.log`.

- `v3.0-tesis`: `tesis/cierre/evidencia/v2-eval-20260923T010103Z/suites/`
- `v4.0-tesis`: `tesis/cierre/evidencia/v2-eval-20260923T215624Z/suites/`

**12. Las 864 pruebas del backend de `v3.0-tesis` SÍ incluyen las 15 fallidas.** Confirmado en el
JUnit: 864 = 845 aprobadas + 15 fallidas + 4 omitidas. La forma correcta de escribirlo es «864
ejecutadas, de las cuales 845 aprobadas, 15 fallidas y 4 omitidas».

Para `v4.0-tesis`: **887 ejecutadas, 883 aprobadas, 0 fallidas, 4 omitidas.**

**13. P-07.**

- **Cobertura por componente: no existe.** Ninguno de los dos paquetes incluye informe de cobertura.
  Hay que declararlo, como hasta ahora.
- **Las 4 omitidas del backend** son las cuatro de `tests.test_valkey_tls_integration`:
  `test_a_backend_helper_connects_and_streams_work`,
  `test_b_connection_without_client_cert_is_rejected`,
  `test_c_client_cert_from_untrusted_ca_is_rejected` y
  `test_d_hostname_mismatch_is_rejected`. Se omiten porque exigen una instancia de Valkey con TLS y
  certificado de cliente, que la suite no levanta.
- **La omitida del agente** es
  `tests.test_detector_multi_event::test_classify_event_no_fanotify_returns_file_modified`.

---

## D. Ítems A2 del documento de correcciones

**14. P-03 — topología. RESUELTO.** El dato existía; no está en `metadata/entorno.txt` sino en
`env/uname.txt` y `env/fs.txt` de cada paquete.

| | Servidor central | Anfitrión monitoreado |
|---|---|---|
| Nombre | `Eze-Linux` | `fim-host` |
| Sistema operativo | Ubuntu 26.04.1 LTS | Ubuntu 24.04.5 LTS |
| Núcleo | 7.0.0-31-generic | 6.8.0-139-generic |
| Arquitectura | x86_64 | x86_64 |
| Sistema de archivos | ext4 sobre `/dev/nvme0n1p2` | ext4 sobre `/dev/sda1` (`/srv/fim-watch`) |
| Naturaleza | Equipo físico | **Máquina virtual** (multipass), 2 vCPU, 3,8 GiB de memoria, 19,3 GiB de disco |

**Son dos equipos**, no uno. El agente corre en una VM y el servidor central en el anfitrión físico, y
el enlace entre ambos es la red virtual de multipass.

Eso **confirma la sospecha del pedido**: las palabras «anfitrión» y «huésped» del informe de desvío de
reloj sí designan una VM. Ahora se puede afirmar.

Versiones del entorno: Docker 29.7.2, Docker Compose v5.5.0, Python 3.13.15 (backend y agente),
PostgreSQL 18.3, n8n 2.17.8.

**15. P-08 — `sha256sum` del `SHA256SUMS` de `v3.0-tesis`:**
`e61b1a2db2b0c40d9af8cc00e0d802965dfde23f2df1c4ff490d3d2b345ef3f9`

**16. P-13 — SÍ, son del intento sin sumidero.** Las 23 negativas sobre 485 pertenecen a
`evidencia/invalidos/v3-eval-20260922T233242Z-sin-sumidero/`, cuya acta las describe: se concentran en
los primeros 83 segundos de una ventana de 1.796 y ninguna después, patrón de un reloj convergiendo
tras un reinicio del huésped.

Conviene mencionar que existe un **segundo** intento con el mismo síntoma pero causa distinta:
`invalidos/v4-eval-20260923T202713Z-reloj-corrido/`, con 347 negativas sobre 484 por un desvío
sostenido, con ambas máquinas declarándose sincronizadas por NTP. Ese caso motivó reemplazar
`systemd-timesyncd` por chrony y la guarda de desvío del arnés.

**17. Sistema operativo del equipo físico el 19/08 — NO SE RESUELVE ACÁ.** Es dato de los autores. Lo
único verificable es que **hoy** el servidor central corre Ubuntu 26.04.1 LTS. Si el 19/08 ya era esa
versión, corregir la frase; si era 24.04, aclarar que se actualizó después.

**18. Núcleo y sistema de archivos de la batería histórica — NO RECUPERABLE.**
`tesis/resultados/entorno.txt` **existe** en la copia local, pero **no registra ni el núcleo ni el
sistema de archivos**: sólo commit, ventana de ejecución y versiones de Python, pytest, PostgreSQL y
Valkey. Además no está versionado. **Dejar la frase actual.**

**19. Persistencia de Valkey — RESUELTO, y el dato importa.** Consultado sobre el contenedor en
ejecución:

```
CONFIG GET save        -> 3600 1 300 100 60 10000
CONFIG GET appendonly  -> no
```

Es decir: **instantáneas RDB con la política por defecto y AOF desactivado.** No hay registro de
solo-añadido. Vale la pena escribirlo con todas las letras, porque acota la garantía de durabilidad
del broker ante una caída abrupta, y el capítulo de resiliencia se apoya en ese componente.

**20. Recuento 10/20/1 — NO SE RESUELVE ACÁ.** Queda suprimido si no aparece en el historial.

---

## E. Repositorio y documentación

**21. `final-consolidated-*` — LA CONTRADICCIÓN NO EXISTE, y el error era mío.** El `.gitignore` tiene
dos líneas, no una:

```
/tesis/cierre/evidencia/final-consolidated-*/
!/tesis/cierre/evidencia/final-consolidated-v10-20260912T210903Z/
```

La segunda es una **excepción explícita**. Verificado en `main`:

| Paquete | Archivos versionados |
|---|---|
| `final-consolidated-20260911T214511Z/` | 0 |
| `final-consolidated-fixed-20260911T225314Z/` | 0 |
| **`final-consolidated-v10-20260912T210903Z/`** | **133** |

Por lo tanto: la v21, el Anexo I y las rutas de F.1, F.3 y la Tabla 37 **son correctas** y no hay que
tocarlas. Lo que sí corresponde es declarar en el Anexo F que los otros dos paquetes
`final-consolidated-*` se excluyen deliberadamente, y por qué.

Mi documento anterior decía que el glob alcanzaba a todos. Era impreciso y el pedido hizo bien en
señalarlo.

**22. Catálogo de reglas de negocio.**

- Último identificador publicado en `main`: **RN-172**. El D más alto es **D78**.
- **RN-170 sí figura** en el catálogo publicado (corresponde a D76, aislamiento del carril de
  notificación). También figuran RN-171 y RN-172, de la Change 60.
- Total de identificadores RN distintos en el catálogo: **172**.

**23. Historias cerradas por ajuste de criterio.** Son **siete**: US-01, US-05, US-11, US-12, US-23,
US-27 y US-29. La octava, **US-21, se cerró con código**: el agente pasó a publicar la bandera
`queue_pressure_high`, con migración aditiva (D72/RN-166).

La tabla de ajustes está en `tesis/cierre/MATRIZ_TRAZABILIDAD.md`, sección «Ajustes de criterio
declarados», del cierre `2d07cb2` (17/09). El conteo es **31/31**, con **24/31 en conteo estricto**
—historias completas cuyo texto canónico no fue ajustado—. Ambas cifras deben aparecer juntas.

**24. Visor de diferencias — NO SE ENCONTRÓ DEFECTO ABIERTO.** Se revisó
`frontend/src/components/ui/DiffViewer.tsx` completo: implementa detección automática de texto y
binario, reconstrucción de diferencias por bloques, `react-diff-viewer-continued` sin
`dangerouslySetInnerHTML`, y modo binario con comparación de hashes y volcado hexadecimal. El backend
persiste hoy `diff_text`, `hex_dump_before`, `hex_dump_after` y `hash_expected`, de modo que la
limitación histórica de descarte en la ingesta tampoco sigue vigente.

**Recomendación**: retirar el pasaje de §7.6 referido al visor, o reformularlo si describe una
limitación de experiencia de uso y no un defecto. La mitad de cuarentena sí sigue vigente: hay dos
implementaciones divergentes (`agent/decision.py:299` y `agent/commands.py:422`), declarado en
`docs/residuales_declarados.md` §9.

**25. Escenarios de 50 y 100 — SON CONCURRENCIA EFECTIVA, no tasa.** Verificado en el publicador de la
batería: usa `asyncio.Semaphore(CONC)` y un `gather` sobre las 1.000 publicaciones, de modo que el
semáforo acota **publicaciones simultáneas en vuelo**. No hay ninguna temporización por segundo.

Redacción sugerida para la nota de la Tabla 28: «hasta N publicaciones simultáneas en vuelo, acotadas
por semáforo; no es una tasa por segundo».

**Atención**: eso vuelve incorrecta la afirmación de §5.3 y de `INFORME_CIERRE_TECNICO.md:110` sobre
«tasas de 1, 50 y 100 operaciones/s», al menos para esta batería. Y hace correcto el rótulo de
`tesis/dataset_cap5.md` que el ítem D1 del documento de correcciones proponía cambiar. **No aplicar
D1**: corregir en el sentido inverso.

---

## F. Forma

**26. Fecha de consulta de la referencia de AIDE — NO SE RESUELVE ACÁ.** La pone quien consultó la
fuente. APA 7 §9.16 exige fecha de recuperación en obras sin fecha.

**27. Páginas de los índices — tarea de Word.** Regenerar índices de tablas y figuras después de
aceptar los cambios.

---

## Dato ambiguo

**28. «~2,9 ms son trabajo de base medido» — sí, significa base de datos.** La redacción precisa es:

> De los ~14,15 ms que insume cada evento en el carril de ingesta, sólo ~2,9 ms corresponden a trabajo
> de base de datos efectivamente medido —~1,33 ms de la consulta de autenticación del agente y
> ~1,56 ms de la inserción con su confirmación—. Los ~11 ms restantes no están atribuidos.

Conviene mantener «no están atribuidos» y no aventurar la causa: es la razón por la que perfilar viene
antes que partir el proceso en dos.

---

---

## Addendum — motivo de la exclusión de los dos paquetes `final-consolidated` (marca 4 de la segunda ronda)

**RESUELTO. El motivo está documentado y el texto para el Anexo F ya estaba escrito.**

El historial lo registra en dos pasos. El `.gitignore` excluyó la serie el 2026-09-15 (`918b16b`,
«ignore local lab and unconsolidated closure artifacts»), y el 2026-09-19 (`214b93a`) se abrieron
excepciones para los dos paquetes que la tesis sí usa, con esta razón textual:

> El resto de esa serie queda fuera: dos corridas que no completaron, una de ellas abortada con el
> árbol de trabajo sucio, y dos consolidaciones previas que las posteriores superan. Ninguna sustenta
> un resultado del documento. Su exclusión es higiene del repositorio y no una omisión.

El párrafo redactado para el Anexo F está en `tesis/cierre/DATOS_PARA_TESIS_V15.md`. **Se transcribe
acá actualizado**, porque su última oración quedó desactualizada: dos de las tres familias que
declaraba excluidas hoy están versionadas.

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

**Cambio respecto del texto original**: la versión de `DATOS_PARA_TESIS_V15.md` declaraba también
excluidos los paquetes `us02-us20-us31-*` y `us03-us16-us17-us25-isolated-*`. Eso ya no es cierto:
están versionados, con 59 y 24 archivos respectivamente. Verificado en `main`:

| Familia | Estado en `main` |
|---|---|
| `a4-vps-*` | Excluida (0 archivos) |
| `us02-us20-us31-*` | **Versionada (59 archivos)** |
| `us03-us16-us17-us25-*` | **Versionada (24 archivos)** |
| Los cuatro `final-consolidated` sin excepción | Excluidos (0 archivos) |

---

## Resumen de lo que queda sin resolver

| # | Qué | Quién lo resuelve |
|---|---|---|
| 1 | Declaración de originalidad y §9.1.2 | El equipo |
| 17 | Sistema operativo del equipo físico el 19/08 | Los autores |
| 20 | Commit y fecha del recuento 10/20/1 | Se suprime si no aparece |
| 26 | Fecha de consulta de la referencia de AIDE | Quien consultó la fuente |

El **18** no queda pendiente: está establecido que el dato no se registró, y la frase actual es
correcta.
