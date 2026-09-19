# Protocolo M-1 — repetición de drenaje Run 4

Se reutilizó sin cambios el arnés de Run 4 (`run_profile.py`, SHA-256 idéntico en las cinco corridas). PostgreSQL 18.3 y Valkey 9.0.3 permanecieron activos en contenedores aislados durante toda la serie. Cada corrida reinició la base, Valkey y el directorio de cola, preencoló 3.000 eventos y aplicó idénticos parámetros: timeout 300 s, límite experimental 100.000 eventos/60 s y reloj monotónico `perf_counter_ns`.

El intervalo comienza inmediatamente antes de iniciar el publicador tras la precola y termina cuando PostgreSQL contiene 3.000 eventos y la cola local queda vacía. La construcción de la cola se excluye. Se conservaron todas las cinco corridas válidas; no se seleccionó la mejor.

Limitaciones: anfitrión único, eventos preencolados, tasa experimental distinta del valor productivo y ausencia de una desconexión completa de cinco minutos. La serie permite descripción de variabilidad, no inferencia poblacional.

Nota de metadatos: el campo estático `source_snapshot_head=965dcac...` y el nombre `drenaje-20260910-run4-unit1` provienen del arnés histórico copiado. La identidad dinámica `git_commit=7df4935...`, el árbol del paquete y sus checksums son la autoridad para estas corridas nuevas.
