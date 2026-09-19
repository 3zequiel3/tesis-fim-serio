# Perfil dirigido del índice de cola

Evaluación nueva y acotada de 3.000 operaciones por etapa sobre la cola durable.
Usa archivos reales y conserva `fsync`/`os.replace`; excluye Valkey y PostgreSQL.

```bash
PYTHONPATH=. backend/.venv/bin/python \
  docs/cierre/evidencia/drenaje-20260910-queue-index-profile/run.py
```

El objetivo es verificar el costo del índice local; no sustituye la repetición
extremo a extremo posterior.

`compare_head.py` ejecuta la misma lista de payloads y operaciones contra la
implementación de `HEAD` y el working tree indexado, en el mismo proceso y
sistema de archivos. Registra el commit base en `comparison.json`.
