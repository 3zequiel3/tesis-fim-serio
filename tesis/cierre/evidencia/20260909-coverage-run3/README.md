# Backend coverage Run 3

Nueva evaluación ejecutada el 2026-09-09 sobre el snapshot descrito por `source-manifest.sha256`.

- 572 tests: 570 passed, 2 skipped, 0 failures/errors.
- 2484/2780 statements = 89.3525%; 296 missing; 3 excluded; branch coverage disabled.
- Los dos skips requieren Valkey real y son opt-in.
- El listener mTLS se deshabilitó sólo para este harness; estos archivos no acreditan mTLS.
- El snapshot tenía HEAD `c806d1c` más cambios locales manifestados. No representa HEAD posterior.

`junit.xml` es una copia sanitizada: la ruta absoluta del repositorio se reemplazó por `SANITIZED_REPO` y el hostname por `SANITIZED_HOST`. El JUnit temporal original tenía SHA-256 `3a9dcdb0a6533f7891c2372dcf3374fa2f512746e89faba2b9d29dce741c10cd`; la copia sanitizada tiene un hash distinto y preserva conteos/resultados.
