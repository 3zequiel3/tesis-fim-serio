# Insumo para el Anexo I — inventario de uso de IA

**Qué es esto y qué no es.** Es el inventario de hechos: qué hizo la IA, sobre qué artefacto, y cómo
se verifica. **No es el texto de la Declaración ni del §9.1.2 ni de la introducción del Anexo I.** Esos
tres los escribe el equipo, y la razón es simple: una declaración sobre el uso de IA redactada por una
IA no se sostiene ante la primera pregunta del tribunal.

Lo que sigue resuelve la parte trabajosa —acordarse de todo y poder probarlo— y deja al equipo la
parte que tiene que ser suya.

**Límite de este inventario**: cubre lo que consta en el repositorio y en la sesión de trabajo del
23–24 de septiembre de 2026. Los usos anteriores se listan según lo que declaran los documentos de
cierre, no por observación directa. El equipo debe completar o corregir esas filas.

---

## Filas propuestas para la Tabla 38

Cuatro columnas, como fija la decisión 5: **apartado o artefacto · versión · qué hizo la IA · qué
verificó el equipo y cómo**.

### A. Redacción del documento

| Apartado o artefacto | Versión | Qué hizo la IA | Cómo se verifica |
|---|---|---|---|
| §6.1, pasajes de discusión | v20, v21 | Redacción de párrafos | Contraste con las cifras de los paquetes sellados citados en cada párrafo |
| §6.4, amenazas 8.ª a 10.ª | v20, v21 | Redacción | Cada amenaza remite a un hecho verificable del repositorio o de un acta |
| §1.6, párrafo de trazabilidad temporal de los criterios | v21 | Redacción, a partir del análisis de fechas de commit | Las fechas se recomputan con `git log` sobre los archivos citados |
| Documento completo | **v22** | **Redacción integral de la versión, a partir de seis documentos de insumo** | Registro de cambios de la v22: apartado, texto anterior, texto nuevo e insumo de origen |
| Cap. 5 y Cap. 6, párrafos nuevos de la v22 | v22 | Redacción | Ídem |
| Anexo F, párrafos nuevos de la v22 | v22 | Redacción | Ídem |

### B. Análisis de datos

| Apartado o artefacto | Versión | Qué hizo la IA | Cómo se verifica |
|---|---|---|---|
| Contraste pareado de McNemar e intervalo de Newcombe | v20 en adelante | Recálculo sobre la tabla pareada | `scripts/analisis_mcnemar.py`, publicado y sin dependencias externas; se reejecuta sobre `control/pareado.csv` de cada paquete |
| Atribución del grupo de control a operaciones del manifiesto | v20 en adelante | Ejecución del análisis | `scripts/analisis_control.py`, publicado |
| Trazabilidad temporal de definiciones de criterio | v21 | Análisis del historial de git para fechar cambios de definición | Los commits citados se inspeccionan con `git show` |
| Atribución de operaciones sin evento persistido | **v22** | **Diseño y escritura del script, y ejecución del análisis** | `scripts/atribuir_operaciones_sin_evento.py`, publicado; produce `latencia/atribucion_sin_evento.csv` en cada paquete y termina con código 1 si alguna operación queda sin atribuir |
| Recuperación del núcleo de la batería histórica | v22 | Consulta del registro del sistema para identificar el arranque que cubre el 19/08 | `journalctl -b <id> -k`; la secuencia de instalación de núcleos lo corrobora de forma independiente |

### C. Código del producto

| Apartado o artefacto | Versión | Qué hizo la IA | Cómo se verifica |
|---|---|---|---|
| Change 59 `notify-isolate-executor-lane` (D76/RN-170) | Candidato `v3.0-tesis` | Diagnóstico, diseño e implementación del aislamiento del carril de notificación | Change archivada en `openspec/changes/archive/2026-09-23-notify-isolate-executor-lane/`; suite del backend y medición unificada sobre el candidato |
| Change 60 `notify-accepted-at-and-test-port-isolation` (D77/RN-171, D78/RN-172) | Candidato `v4.0-tesis` | Diagnóstico, diseño e implementación de `channel_accepted_at` y del desacople del arnés de pruebas | Change archivada; 887 pruebas del backend sin fallas sobre el artefacto sellado |
| Migración `022_add_alert_channel_accepted_at.sql` | `v4.0-tesis` | Escritura | Idempotencia comprobada aplicándola dos veces sobre una base con datos |
| Mensajes de commit del período | — | Redacción | Historial del repositorio |

### D. Instrumentación de laboratorio

| Apartado o artefacto | Versión | Qué hizo la IA | Cómo se verifica |
|---|---|---|---|
| Arnés de evaluación unificada | v22 | Detección y corrección de ocho defectos de instrumentación | Cada defecto tiene acta en `tesis/cierre/evidencia/invalidos/` o en el `MOTIVO.md` del paquete afectado |
| Guardas del arnés: esquema contra modelo, sumidero de notificación, desvío de reloj | v22 | Diseño e implementación | La procedencia de cada paquete registra el resultado de las tres |
| Parametrización del candidato en el arnés de suites | v22 | Corrección | `scripts/correr_suites_candidato.sh`, publicado |

### E. Documentos de insumo del cierre

| Apartado o artefacto | Versión | Qué hizo la IA | Cómo se verifica |
|---|---|---|---|
| `PARA_LA_V22_estado_real.md` | v22 | Redacción integral | Cada cifra remite a un paquete sellado |
| `RESPUESTAS_PENDIENTES_V22.md` | v22 | Redacción integral | Ídem |
| `RESPUESTAS_ULTIMAS_MARCAS_V22.md` | v22 | Redacción integral | Ídem |
| `DATOS_PARA_DECISIONES_V22.md` | v22 | Redacción integral | Ídem |
| `PROMPT_ESCRITOR_V22.md` | v22 | Redacción | — |
| Este inventario | v22 | Redacción | — |

---

## Tres hechos que conviene que la introducción del Anexo I recoja

No son texto para copiar: son los hechos que hacen defendible el registro.

**1. El uso fue extenso y sustantivo, no accesorio.** Abarcó redacción, análisis estadístico,
implementación de código del producto e instrumentación de laboratorio. Declararlo como «asistencia
menor» sería falso y verificable como falso, porque las changes archivadas y los scripts publicados
llevan la marca del trabajo.

**2. Todo dato aportado por IA quedó atado a un artefacto verificable.** No hay ninguna cifra en el
documento cuya única fuente sea la afirmación de un modelo: cada una sale de un paquete sellado, de un
script publicado o de un comando reproducible. Ésa es la propiedad que hace auditable el trabajo, y es
más fuerte que cualquier declaración de buenas intenciones.

**3. La IA se equivocó, y esas equivocaciones están documentadas y corregidas en el repositorio.** Al
menos seis, todas en el registro:

| Error | Dónde quedó corregido |
|---|---|
| Se informaron 6,2 ev/s de drenaje y una varianza de 4× a partir de una repetición contaminada | `v2-eval-20260922T175053Z`, y la corrección en el commit del paquete |
| Se midió un desfasaje de reloj de 150 ms con un instrumento de 300 ms de resolución, y se lo dio por real | Acta de `invalidos/v4-eval-20260923T202713Z-reloj-corrido/` |
| Se informó «860 pruebas, 0 fallas» sin artefacto sellado que lo respaldara | `RESULTADOS.md` de `v2-eval-20260923T010103Z`, con la historia explicada |
| Se diagnosticó mal la causa de dos fallas de prueba: se atribuyó a variables de entorno cuando era una ruta relativa al directorio de trabajo | Change 60 y los mismos documentos |
| Se afirmó que dos familias de paquetes estaban versionadas contando rutas anidadas | `DATOS_PARA_DECISIONES_V22.md`, dato 2 |
| Se recomendó invertir el ítem D1 extendiendo hacia atrás un mecanismo verificado en el presente | `DATOS_PARA_DECISIONES_V22.md`, dato 6 |

Declarar estos errores **suma**. Un registro que sólo enumera aciertos se lee como una lista de
méritos; uno que incluye lo que salió mal y cómo se detectó se lee como lo que es: un procedimiento de
verificación que funciona. Y el mecanismo que los detectó —contrastar toda afirmación contra un
artefacto— es exactamente lo que el capítulo de amenazas a la validez sostiene.

---

## Lo que el equipo tiene que escribir, y por qué no está acá

| Marca | Qué es |
|---|---|
| 1 — Declaración, párr. 2 | El compromiso de originalidad y la remisión al §9.1.2 y al Anexo I |
| 2 — §9.1.2 | La descripción del uso y la remisión al Anexo I |
| 3 — Anexo I, introducción | El encuadre del registro |

Son declaraciones en primera persona sobre la propia conducta académica. Nadie más puede hacerlas, y
menos la herramienta sobre la que se está declarando. Lo que este documento aporta es el material:
qué se usó, dónde, y cómo se comprueba.
