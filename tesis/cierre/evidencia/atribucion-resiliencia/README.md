# Atribución de las operaciones no encoladas de la batería de resiliencia

Resultados de `scripts/atribuir_resiliencia.py` sobre los paquetes sellados de los
candidatos v3.0-tesis (`v2-eval-20260923T010103Z`) y v4.0-tesis
(`v2-eval-20260923T215624Z`). Se guardan fuera de los paquetes para no romper sus sellos.

Regenerar:

    python3 scripts/atribuir_resiliencia.py tesis/cierre/evidencia/v2-eval-20260923T215624Z --salida tesis/cierre/evidencia/atribucion-resiliencia/v4.0-tesis
    python3 scripts/atribuir_resiliencia.py tesis/cierre/evidencia/v2-eval-20260923T010103Z --salida tesis/cierre/evidencia/atribucion-resiliencia/v3.0-tesis

Cada carpeta contiene el manifiesto reconstruido por repetición (verificado contra el
registro del generador, operación por operación), la atribución en CSV, la salida del
script de atribución y `RESUMEN.md`.
