## 1. Agente — helper de verificación desde disco (D81/RN-175)

- [x] 1.1 Agregar `verify_restored_file(path: str, written: bytes, expected_hash: str) -> str | None` en `agent/decision.py`, junto a `action_error_from_oserror` (design D-1): abre con `os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC`, hashea por bloques con `hashlib.sha256`, cierra el descriptor en `finally` (D-2)
- [x] 1.2 En el helper, comparar contra `expected_hash` si no está vacío y, si lo está, contra `_hash_bytes(written)`; la verificación nunca se omite (D-3)
- [x] 1.3 En el helper, capturar `OSError` en apertura y lectura y devolver `"verify_failed"` sin pasar por `action_error_from_oserror`; loguear `restore.verify_failed` con `errno` y `path` como campos estructurados (D-4)
- [x] 1.4 En el helper, devolver `"hash_mismatch_after_restore"` ante discrepancia y loguear `restore.verify_mismatch` con el hash esperado y el leído, sin contenido
- [x] 1.5 Docstring del helper citando D81/RN-175 y explicando por qué la relectura no usa el mapeo de errores de escritura

## 2. Agente — ambos caminos usan el helper

- [x] 2.1 En `DecisionEngine._auto_restore`, reemplazar `agent/decision.py:295-297` por la llamada al helper y `raise _ActionFailed(err)` si devuelve un literal; actualizar el docstring (`:227-232`), que hoy dice «Verifica SHA-256 igual que antes»
- [x] 2.2 En `handle_restore_file`, importar el helper junto a `action_error_from_oserror` y `parse_baseline_mode` (`agent/commands.py:348`) y reemplazar `:400-402` por la llamada al helper con `raise ValueError(err)`
- [x] 2.3 Actualizar el comentario de duplicación de `agent/commands.py:340-343` para dejar explícito que la escritura sigue duplicada y la verificación es compartida
- [x] 2.4 Verificar que no queda ningún `hashlib.sha256(content)` ni `_hash_bytes(content)` usado como hash del archivo restaurado en `agent/` (`rg -n "restored_hash" agent/` sin resultados)

## 3. Tests — helper

- [x] 3.1 Archivo idéntico al contenido y hash esperado correcto → `None`
- [x] 3.2 Contenido en disco distinto del esperado → `"hash_mismatch_after_restore"`
- [x] 3.3 `expected_hash=""` con disco igual a `written` → `None`; con disco distinto → `"hash_mismatch_after_restore"`
- [x] 3.4 Path inexistente → `"verify_failed"`
- [x] 3.5 Path que es un symlink a un archivo con el contenido correcto → `"verify_failed"` (O_NOFOLLOW)
- [x] 3.6 Archivo mayor que el tamaño de bloque → hash correcto (cubre la lectura por bloques)

## 4. Tests — camino automático (`_auto_restore`)

- [x] 4.1 **Obligatorio:** monkeypatch de `os.write` que escribe la mitad de los bytes sólo cuando `data` es el contenido del baseline y delega en el original en otro caso (design D-7) → `_auto_restore` lanza `_ActionFailed("hash_mismatch_after_restore")`; vía `evaluate_and_act`, el payload trae `action_failed: True` y `action_error == "hash_mismatch_after_restore"` y el journal queda `failed` con esa causa
- [x] 4.2 Envoltura de `os.replace` que, tras el reemplazo real, sobrescribe el path con otros bytes → `hash_mismatch_after_restore`
- [x] 4.3 Envoltura de `os.replace` que, tras el reemplazo real, sustituye el path por un symlink a un archivo con el contenido correcto → `verify_failed`
- [x] 4.4 Envoltura de `os.open` que levanta `OSError(errno.EIO)` sólo en la apertura de verificación (flags con `O_NOFOLLOW` y sin `O_WRONLY`) → `verify_failed`
- [x] 4.5 Mismo caso con `errno.EACCES` → `verify_failed`, no `permission_denied`
- [x] 4.6 Entry con `hash=None` y escritura truncada → `hash_mismatch_after_restore` (la verificación no se omite)
- [x] 4.7 Confirmar que `test_decision_auto_restore_hash_mismatch` (`agent/tests/test_decision.py:140`) y los tests de restauración exitosa existentes pasan sin cambios
- [x] 4.8 Rehidratación: una entrada `pending` con `auto_restore` y escritura truncada se publica con `action_failed: True` y `action_error == "hash_mismatch_after_restore"`, y el journal queda `failed`

## 5. Tests — camino del operador (`handle_restore_file`)

- [x] 5.1 Escritura truncada (mismo monkeypatch de 4.1) → `event_ack` con `status="error"` y `error="hash_mismatch_after_restore"`; journal `failed` con esa razón
- [x] 5.2 `OSError` en la apertura de verificación (envoltura de 4.4) → `event_ack` con `error="verify_failed"`; journal `failed` con esa razón
- [x] 5.3 Confirmar que `test_restore_handler_success_publishes_ack` y `test_restore_handler_no_baseline_publishes_error_ack` (`agent/tests/test_commands.py:626`, `:675`) y el test de no auto-detección del restore del operador pasan sin cambios

## 6. Documentación y cierre

- [x] 6.1 Eliminar la sección «## 1. La verificación de hash post-restauración es tautológica» de `docs/residuales_declarados.md` (`:16-35`, con su separador), **sin renumerar** las entradas restantes; agregar en la introducción una línea que diga que las entradas retiradas se eliminan sin renumerar (design D-6)
- [x] 6.2 Verificar que ningún documento fuera de `docs/residuales_declarados.md` cite el residual §1 como abierto (`rg -n "residuales_declarados.md\` §1" docs/ README.md`); las citas en `CHANGES.md` y en D81/RN-175 describen el retiro y no se tocan
- [x] 6.3 Correr la suite completa del agente (`pytest agent/tests`) y confirmar cero fallas nuevas
- [x] 6.4 Correr `python3 scripts/check_spec_integrity.py` y `openspec validate agent-restore-verify-from-disk --strict`
- [ ] 6.5 Marcar la Change 63 en `CHANGES.md` al cerrar el apply (el orquestador decide el momento; no se edita durante el propose)
