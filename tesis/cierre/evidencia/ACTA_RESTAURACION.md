# Acta de restauración de originales (P-9)

- Fecha: 18 de octubre de 2026.
- Responsable: Nicolás Castro, en un commit firmado posterior a la etiqueta `entrega-tesis`.

## Qué se restauró

| Paquete | Archivos | Commit del sellado | Alteración posterior |
|---|---|---|---|
| `oficial-cap5-20260917T223823Z/` (v1.0-tesis) | Los seis registros de `suites/` (`agente`, `backend` y `frontend`, `.log` y `.xml`) | `82d07af` (19/9/2026) | Sobrescritos por las corridas de v2.0-tesis (`601f717`) y v3.0-tesis (`7518be3`), porque `scripts/correr_suites_candidato.sh` y `lab/suites_candidato.sh` escribían por defecto en ese directorio |
| `v2-eval-20260923T010103Z/` (v2.0-tesis) | `RESULTADOS.md` | `df9ed0d` (23/9/2026) | Reescrito en `1f28c9e` para corregir el diagnóstico de dos fallas de prueba |

## Procedimiento

    git checkout 82d07af -- tesis/cierre/evidencia/oficial-cap5-20260917T223823Z/suites
    git checkout df9ed0d -- tesis/cierre/evidencia/v2-eval-20260923T010103Z/RESULTADOS.md
    (cd <paquete> && sha256sum -c SHA256SUMS)

No se regeneró ningún manifiesto: los originales vuelven a coincidir con el que ya tenía cada paquete. Los dos verifican después de la restauración.

## Lo que se conserva y lo que no cambia

- Los contenidos posteriores siguen en el historial: los registros de suites de v2.0-tesis y v3.0-tesis, en `601f717` y `7518be3`; la versión corregida de `RESULTADOS.md`, en `1f28c9e`. Su diagnóstico sustituye al del original sellado: las dos fallas de `tests.core.test_notification_settings` no se deben a la variable `N8N_WEBHOOK_URL` del laboratorio, sino a que `backend/app/core/config.py` declara `env_file=".env"` con ruta relativa, que se resuelve contra el directorio de trabajo.
- Las trazas de resiliencia de `v2-eval-20260922T175053Z/` no se restauran. Descomprimidas coinciden con el manifiesto, pero son copias de una corrida de diagnóstico anterior (run_id `b3-traza`), y se declaran así en la Tabla 33 de la tesis.
- Los dos paquetes de custodia de v5.1-tesis siguen sin verificar, porque una regla de `.gitignore` excluye por tamaño el bundle y el árbol de la versión.
- Esta acta se guarda fuera de los paquetes para no agregarles archivos que sus manifiestos no listan.
