## 0. Precondiciones

- [x] 0.1 Confirmar con `git log -1` que la rama es `devel` y desciende de `v5.1-tesis` (`git merge-base --is-ancestor v5.1-tesis HEAD`); no etiquetar ni mover `v5.1-tesis`.
- [x] 0.2 Correr la suite de backend y registrar la línea base (esperado: 1.106 tests, 1.102 pasan y 4 se omiten). Correr `python3 scripts/check_spec_integrity.py` y registrar que pasa.
- [x] 0.3 Releer D89/RN-183, D90/RN-184, D91/RN-185 y D92/RN-186 en `docs/reglas_de_negocio.md` y sus filas en `docs/arquitectura_stack.md`; cualquier suposición nueva se cierra ahí antes de seguir.

## 1. Validación de rutas (D91/RN-185)

- [x] 1.1 Escribir primero `backend/tests/test_path_validation.py` con los casos de los specs `backend-rules` y `backend-agent-management`: relativo, `!` + relativo, `..` como segmento y `a..b` válido, `\n`/`\t`/`\x00`/`\x7f`, 1.024 vs 1.025 caracteres, `/etc/[` inválido y `[abc]`, `[!.]`, `[]a]` válidos, lista vacía, 64 vs 65 rutas, duplicado `/etc` + `/etc/` con `index == 1`, `/` sola válida. Verificar que fallan (módulo inexistente).
- [x] 1.2 Crear `backend/app/core/path_validation.py` (design D-1, D-2, D-3) con `PathValidationError(code, message, index)`, `MAX_PATH_LENGTH`, `MAX_WATCH_PATHS`, `validate_rule_pattern` y `validate_watch_paths`; mensajes en español. Los tests de 1.1 pasan.
- [x] 1.3 Test de coherencia con `fnmatch`: para cada patrón con clase aceptado en 1.1, `fnmatch.fnmatch` matchea un path de ejemplo de la clase y no uno fuera de ella.

## 2. Reglas

- [x] 2.1 Tests de router en `backend/tests/test_rules_router.py`: `POST /rules` y `PUT /rules/{id}` con cada código de `pattern_*` responden 422 con `detail == {"code", "message"}`; ninguno persiste, incrementa `ruleset_version` ni publica `rule_sync`; `pattern_duplicate` en alta y en edición contra otra regla; editar una regla conservando su propio `pattern` sigue respondiendo 200.
- [x] 2.2 En `backend/app/modules/rules/service.py`, reemplazar el cuerpo de `validate_pattern` por `validate_rule_pattern` y lanzar `PathValidationError("pattern_duplicate", ...)` en el chequeo de duplicado de alta y edición (excluyendo la propia regla).
- [x] 2.3 En `backend/app/modules/rules/router.py`, traducir `PathValidationError` a `HTTPException(422, detail={code, message})` (design D-4) en alta y edición; los demás `ValueError` conservan su manejo.
- [x] 2.4 Adaptar los tests existentes que crean reglas con patrones relativos vía API o asertan `"pattern must not be empty"`/`"duplicate pattern"`; anotar en cada uno por qué cambió.

## 3. watch_paths

- [x] 3.1 Tests en un archivo nuevo `backend/tests/test_agent_config_validation.py`: cada código de `watch_path*` con su `index`, y que `agents.watch_paths`, `ruleset_version`, `audit_log` y el stream `commands` no cambian ante un rechazo; ruta inexistente aceptada.
- [x] 3.2 En `backend/app/modules/agents/service.py` (`update_agent_config`), invocar `validate_watch_paths` antes de cualquier escritura; en `agents/router.py`, traducir `PathValidationError` a 422 con `index`.
- [x] 3.3 Reemplazar el test del escenario «watch_paths vacío es válido» por el de rechazo, con nota (D91/RN-185).

## 4. Filtro path_prefix (D91/RN-185)

- [x] 4.1 Tests en el módulo de tests de `GET /events` (PostgreSQL real del harness): `path_prefix=%` devuelve `total == 0`; `/srv/a_b` no matchea `/srv/axb/x`; un prefijo con `\` es literal; `/etc/` sigue funcionando. Verificar que el primero falla hoy.
- [x] 4.2 En `backend/app/modules/events/router.py:169`, usar `Event.path.startswith(path_prefix, autoescape=True)`; confirmar que el `COUNT` usa la misma subconsulta.

## 5. Rate limit del login e IP real (D92/RN-186)

- [x] 5.1 Tests de `backend/app/core/client_ip.py` (unitarios, con `Request` sintético): par de confianza + XFF simple, XFF con entrada falsificada a la izquierda, par no confiable con XFF, header ausente, header con basura, IPv6.
- [x] 5.2 Crear `backend/app/core/client_ip.py` (design D-7) y el setting `trusted_proxy_cidrs` en `backend/app/core/config.py` con validador CSV que nombra la entrada inválida; test de settings inválidos.
- [x] 5.3 Tests de login en `backend/tests/test_auth.py`: 10 éxitos seguidos sin 429 y sin key; 4 fallos + éxito + 4 fallos sin 429; 5 fallos → 6.º con contraseña correcta es 429 con `login_rate_limited` y `Retry-After` igual al TTL; 5 fallos desde una IP no bloquean otra IP (vía XFF con par de confianza); 401 con `invalid_credentials`; 403 con `account_disabled`; TTL presente tras un fallo con `count > 1`. Verificar que los dos primeros fallan hoy.
- [x] 5.4 Reescribir `backend/app/core/rate_limit.py` del login (design D-6): `login_retry_after`, `record_failed_login`, `clear_login_attempts`; docstring con la semántica de fallidos y fixed-window. `check_api_rate_limit` sin cambios.
- [x] 5.5 Actualizar `POST /auth/login` en `backend/app/modules/auth/router.py` al orden del spec y usar `client_ip` también en el `audit_log` (`extra=f"ip={ip}"`).
- [x] 5.6 Adaptar `backend/tests/conftest.py` y los tests que dependían de `check_login_rate_limit` o del texto `"Too many login attempts"`, con nota.
- [ ] 5.7 Agregar `TRUSTED_PROXY_CIDRS=10.0.0.0/8,172.16.0.0/12,192.168.0.0/16` al servicio `backend` de `docker-compose.yml`, `docker-compose.tls.yml`, `docker-compose.acceptance-lab.yml` y `docker-compose.us02-us20-us31-lab.yml`, y documentarla en `.env.example` con el riesgo residual de D92/RN-186.

## 6. Cambio de contraseña (D89/RN-183)

- [x] 6.1 Tests en `backend/tests/test_auth.py` (o el módulo de `change-password` existente): `password_reuse` con `password_hash` intacto y token aún válido; `current_password_invalid` y `password_policy` con `detail.code` y `message` en español; respuesta 200 sin `access_token`; refresh posterior con el refresh token anterior responde 401.
- [x] 6.2 `password_policy_error` en `backend/app/core/security.py` devuelve `(code, message)` en español; adaptar sus llamadores (`users/router.py` en `change-password` y en el alta de admins de C20).
- [x] 6.3 En `POST /users/change-password` (`backend/app/modules/users/router.py`), agregar el chequeo de reutilización después de la política (design D-8) y los `detail` `{code, message}`; la revocación no cambia.
- [x] 6.4 Adaptar los tests existentes que asertan `"Incorrect current password"` o los mensajes en inglés de la política, con nota.

## 7. Contrato de error (D90/RN-184)

- [x] 7.1 Test de contrato `backend/tests/test_error_body_contract.py`: para cada código nuevo de esta change, el body es `{"detail": {"code": str, "message": str}}` sin `code` en la raíz; `pending_events_exist` conserva `{"code", "count"}`, y `absent_confirmation_required`, `release_in_progress` y `quarantine_not_releasable` conservan su `code`.
- [x] 7.2 Actualizar el aviso del rate limit en `README.md` (~línea 489): mensaje en español, sólo intentos fallidos, IP real y `TRUSTED_PROXY_CIDRS`.

## 8. Cierre

- [x] 8.1 Correr la suite de backend completa: todos los tests previos pasan (salvo los adaptados con nota) y los nuevos pasan; registrar el conteo final frente a la línea base.
- [x] 8.2 Correr `ruff`/el linter configurado del backend sobre los archivos tocados, si existe en el proyecto.
- [x] 8.3 Correr `openspec validate backend-input-validation-hardening --strict` y `python3 scripts/check_spec_integrity.py`.
- [x] 8.4 Commits convencionales por grupo (`fix(rules): ...`, `fix(agents): ...`, `fix(events): ...`, `fix(auth): ...`, `test: ...`), sin atribución a IA.
