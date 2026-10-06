# Corrida incompleta de cobertura y custodia — v5.1-tesis, 2026-10-05T23:46:56Z

**Inválida.** El agente (810 aprobadas y 1 omitida, 811 en total) y el backend (1.102 aprobadas y 4 omitidas, 1.106 en total) completaron sus pruebas con cobertura: 82,09 % y 95,03 % de líneas. El frontend falló en el primer segundo porque el script ejecutaba `npm ci` y el frontend es un proyecto pnpm: tiene `pnpm-lock.yaml` y no tiene `package-lock.json`. Sin `coverage-summary.json` el resumen falló, pero el script selló el paquete igual.

Los binarios de custodia de esta corrida se borraron porque se regeneran idénticos: `candidate.bundle` con SHA-256 `ce2e1d78…` y `candidate-tree.tar.gz` con SHA-256 `57b0ed50…`.

**Corrección.** El script ahora usa pnpm y aborta, en lugar de sellar, si falta la cobertura o el JUnit de cualquiera de los tres componentes.
