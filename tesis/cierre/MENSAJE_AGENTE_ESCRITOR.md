# Mensaje para el agente escritor — cierre del laboratorio (v29)

> Mandale este archivo completo al agente escritor. Reúne todo lo que pidió: los resultados de la
> evaluación y los datos de cobertura y custodia (P-8). Todo lo que se menciona está en la rama
> `main` del repositorio.

---

## 1. Qué tiene que leer primero

**`tesis/cierre/HANDOFF_REDACCION_V29.md`**: es el documento principal y hay que leerlo completo
antes de editar la tesis. Contiene:

- todos los valores del Capítulo 5, cada uno con la ruta del archivo de donde sale;
- qué hay que corregir en los capítulos 1, 2, 3, 4 y 7, en las Tablas 3, 24 y 25 y en el Anexo F;
- la fila STRIDE para la Tabla 3, lista para pegar;
- una lista de verificación final para el redactor.

---

## 2. Candidato evaluado

| Dato | Valor |
|---|---|
| Etiqueta del candidato del Capítulo 5 | `v5.1-tesis` |
| Commit del candidato | `404402a9049d6cba63f1cd122279c963bdceaf79` |
| Árbol del candidato | `56d42646e744d61b192ddeda7169e08a42c100d5` |
| Candidato anterior, descartado | `v5.0-tesis`: su drenaje midió 76,6 ev/s, por debajo del mínimo de 95 ev/s |

---

## 3. Cobertura y custodia (P-8): los datos que pidió

### 3.1 Identificación del paquete

| Dato | Valor |
|---|---|
| Nombre del paquete | `tesis/cierre/evidencia/v5.1-tesis-cobertura-custodia-20261005T235409Z` |
| Commit del paquete | `d38ce58` |
| SHA-256 del archivo `SHA256SUMS` | `9582a0346ab2972b3c683020e2f3a23140fd5c51cef1d86067d7163c3326e5a0` |
| Fecha de la corrida (UTC) | 2026-10-05, 23:54:09 |
| Script usado | `lab/cobertura_custodia.sh`, el que mandaste, con dos correcciones (§3.5) |

### 3.2 Contenido de `RESUMEN.txt`

```
agent     lineas  82.09 % (3777/4601)
backend   lineas  94.98 % (4069/4284)
frontend  lines       88.33 % (3778/4277)
frontend  statements  88.33 % (3778/4277)
frontend  functions   77.30 % (235/304)
frontend  branches    84.02 % (831/989)
agente.xml    tests=811 fallas=0 errores=0 omitidos=1
backend.xml   tests=1106 fallas=0 errores=0 omitidos=4
frontend.xml  tests=298 fallas=0 errores=0 omitidos=0
bundle_sha256=2544b515f0438b1332c56cd1bc08aae58fde946f019d62c8f971ddd396cf6242
archivo_sha256=57b0ed50cc5955796f7c10af9fd4270aa1ce8e3ecce4a1a73984e6c17506c68f
```

### 3.3 Los mismos datos, en tabla

**Cobertura por componente**

| Componente | Métrica | Porcentaje | Cubiertas / totales |
|---|---|---|---|
| Agente (sin contar los tests) | Líneas | 82,09 % | 3.777 / 4.601 |
| Backend (`backend/app`) | Líneas | 94,98 % | 4.069 / 4.284 |
| Frontend | Líneas | 88,33 % | 3.778 / 4.277 |
| Frontend | Sentencias | 88,33 % | 3.778 / 4.277 |
| Frontend | Funciones | 77,30 % | 235 / 304 |
| Frontend | Ramas | 84,02 % | 831 / 989 |

**Pruebas ejecutadas**

| Suite | Tests | Fallas | Errores | Omitidos |
|---|---|---|---|---|
| Agente | 811 | 0 | 0 | 1 |
| Backend | 1.106 | 0 | 0 | 4 |
| Frontend | 298 | 0 | 0 | 0 |

### 3.4 Comprobaciones de custodia (`procedencia.txt`)

```
tag=v5.1-tesis
commit=404402a9049d6cba63f1cd122279c963bdceaf79
tree=56d42646e744d61b192ddeda7169e08a42c100d5
generado_utc=20261005T235409Z
recuperacion_desde_bundle=ok
archivo_determinista=ok
```

| Comprobación | Resultado | Qué significa |
|---|---|---|
| Recuentos de pruebas | 811 / 1.106 / 298 ✔ | Coinciden con la corrida unificada; el entorno no cambió |
| `recuperacion_desde_bundle` | ok ✔ | Clonar el bundle recupera exactamente el árbol de la etiqueta |
| `archivo_determinista` | ok ✔ | Generar el `.tar.gz` otra vez produce los mismos bytes |
| Sello del paquete (`sha256sum -c SHA256SUMS`) | Todo OK ✔ | Ningún archivo del paquete cambió después de sellarlo |

### 3.5 Notas que hay que tener en cuenta al redactar

1. **El script se corrigió en dos puntos antes de que funcionara.**
   - El frontend es un proyecto **pnpm**, no npm: tiene `pnpm-lock.yaml` y no tiene
     `package-lock.json`, así que `npm ci` fallaba en el primer segundo. Ahora usa
     `pnpm install --frozen-lockfile`.
   - Al terminar volvía a levantar el backend del laboratorio con otra configuración (`up -d` con un
     juego distinto de archivos compose). Ahora usa `start`, que sólo vuelve a arrancar el mismo
     contenedor.
   - Además, ahora aborta en lugar de sellar si falta la cobertura de algún componente.
2. **Hubo un primer intento inválido.** Falló el frontend por el problema de npm y el script lo selló
   igual. Está en `tesis/cierre/evidencia/invalidos/v5.1-tesis-cobertura-custodia-20261005T234656Z-frontend-npm/`
   con un `LEEME.md` que explica por qué. No se usa como resultado.
3. **Los dos archivos de custodia no están en el repositorio.** `candidate.bundle` pesa 117 MB y
   `candidate-tree.tar.gz` 166 MB, y GitHub no acepta archivos de más de 100 MB. El paquete trae sus
   SHA-256 (en `RESUMEN.txt` y en `SHA256SUMS`) y un `custody/CUSTODIA.md` que lo explica; los
   binarios se guardan fuera del repositorio. Si la tesis menciona el bundle, tiene que aclarar
   esto.
4. **El `.tar.gz` es determinista; el bundle no.** El `.tar.gz` dio el mismo SHA-256
   (`57b0ed50…`) en las dos corridas. El bundle dio hashes distintos (`ce2e1d78…` en el intento
   inválido y `2544b515…` en el válido) porque git no empaqueta siempre en el mismo orden. Por eso
   la custodia del bundle no se prueba con su hash, sino comprobando que recupera el árbol exacto
   (`recuperacion_desde_bundle=ok`).
5. **Cobertura del backend: informar 94,98 %.** El intento inválido había dado 95,03 %; la diferencia
   es de 2 líneas sobre 4.284 y depende del orden en que corren los tests. El valor que va a la
   tesis es el del paquete válido.

---

## 4. Resultados principales de la evaluación (resumen)

El detalle completo, con fuentes y cómo interpretar cada valor, está en
`tesis/cierre/HANDOFF_REDACCION_V29.md`. Lo central:

| Medición | Resultado en `v5.1-tesis` |
|---|---|
| Latencia de detección, P99 combinado (3 repeticiones, 1.494 eventos) | **41,7 ms**, IC95 [40,5; 42,3] ms |
| Latencia, P99 por repetición | 40,6 / 39,5 / 42,2 ms |
| Latencia, mediana combinada | 31,0 ms |
| Grupo de control (escaneo cada 15 min): eventos perdidos | 85,6 % / 80,4 % / 81,2 % |
| Factor de mejora frente al control (medianas) | 17.464× / 15.305× / 15.849× |
| Resiliencia (corte de Valkey de 5 min): caudal de consumo | **117,2 / 125,2 / 117,5 ev/s** (mínimo exigido: 95) |
| Resiliencia: eventos fuera de orden | **0 / 0 / 0** (en `v4.0-tesis` hubo 359) |
| Resiliencia: duplicados y descartados | 0 y 0 |
| Notificación: P99 con 1.000 eventos por escenario | ≈ 29,5 s; es drenaje de cola, no la latencia de una notificación aislada |
| Notificación: tasa de entrega | ≈ 28 notificaciones/s, igual que en `v5.0-tesis` |
| Reconciliación al arrancar (B-5b) | 10/10 repeticiones correctas |
| Escritura por `mmap` (caso D, demoras de 0 a 500 ms) | 70/70 detectadas, sin ventana de evasión |

**Advertencias importantes** (están desarrolladas en el handoff):

- **Resiliencia:** usar el caudal de consumo (117 a 125 ev/s), **no** el `throughput_ev_s` de unos 65
  que aparece en los logs. Ese número incluye el tiempo de espera del arnés.
- **Notificación:** el P99 subió respecto de `v5.0-tesis` pero **no es una regresión**; se comprobó
  midiendo la tasa de entrega con timestamps absolutos en las dos versiones.
- **Latencia:** cada repetición recibe entre 495 y 500 eventos de 500. Los que faltan son archivos
  que volvieron a su contenido aprobado, y el agente los ignora por diseño (RN-112). No son
  detecciones perdidas.
- **`mmap`:** la limitación que la tesis plantea en §1.7 y §2.6 no se reprodujo. Hay que retirarla o
  restringirla al caso de un proceso que no hace `munmap`.

---

## 5. Lo que queda pendiente después de la redacción

Cuando esté el `.docx` final de la tesis:

```bash
python3 scripts/verificar_rutas_tesis.py Tesis_vNN.docx main            # repetir hasta 0 faltantes
git tag -a entrega-tesis -m "Versión entregada de la tesis" main
python3 scripts/verificar_rutas_tesis.py Tesis_vNN.docx entrega-tesis   # tiene que dar 0 faltantes
git push origin entrega-tesis
```

El Anexo F tiene que citar sólo la etiqueta `entrega-tesis`.
