# Código — agent/detector.py (hacelo primero)
```
def _get_uid(pid: int) -> int | None:
    try:
        with open(f"/proc/{pid}/status") as f:
            for line in f:
                if line.startswith("Uid:"):
                    return int(line.split()[1])
    except OSError:
        pass
    return None        # antes: 0
```
Y el tipo del campo en la dataclass: uid: int | None (línea 55). El modelo Event del backend ya declara process_uid: int | None, así que no hay migración. En agent/decision.py línea 151, el "process_uid": 0 del camino de rehidratación también pasa a None —ahí el proceso original ya no existe por definición—.

Sin esto, el texto de la Variante B sería falso: diría que la atribución puede fallar cuando en realidad el sistema la resuelve siempre a root.

## Tests — ojo con esto

El cambio en `agent/decision.py:151` **no queda cubierto por ningún test existente**. Los tests que ejercen `engine.rehydrate()` son `test_rehydrate_action_error_propagates` (`agent/tests/test_decision.py:220`), `test_rehydrate_auto_restore_pending` (:364), `test_rehydrate_manual_review_pending` (:399) y `test_rehydrate_no_pending` (:419), y ninguno assertea sobre `process_uid`.

Las fixtures con `process_uid: 0` que aparecen en `test_decision.py:73`, `test_restore_metadata.py:77` y `test_symlink_hardening.py:565` **no** son del camino de rehidratación: son helpers `_make_change()` con `process_pid: 100` que alimentan `evaluate_and_act()`. Representan un proceso real y siguen siendo correctas. No tocarlas.

Lo que hay que agregar es la aserción que falta, p. ej. en `test_rehydrate_auto_restore_pending`:

```python
assert payload["process_uid"] is None
```

Y el test nuevo de `_get_uid` sobre un pid inexistente, que es el que sostiene la afirmación de la tesis.
