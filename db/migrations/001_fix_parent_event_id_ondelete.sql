-- Migration 001: Fix parent_event_id FK to use ON DELETE SET NULL
--
-- Idempotente: detecta si la constraint ya tiene ON DELETE SET NULL antes de actuar.
-- Safe para re-ejecución: no falla si el constraint ya fue actualizado.
--
-- Para bases de datos existentes creadas antes de C9 (backend-critical-fixes).
-- Bases nuevas reciben la definición correcta vía SQLModel.metadata.create_all().

DO $$
DECLARE
    v_constraint_name TEXT;
    v_has_set_null    BOOLEAN;
BEGIN
    -- Buscar el nombre de la FK constraint sobre events.parent_event_id
    SELECT tc.constraint_name
    INTO v_constraint_name
    FROM information_schema.table_constraints tc
    JOIN information_schema.key_column_usage kcu
        ON tc.constraint_name = kcu.constraint_name
        AND tc.table_schema   = kcu.table_schema
    WHERE tc.constraint_type = 'FOREIGN KEY'
      AND tc.table_name       = 'events'
      AND kcu.column_name     = 'parent_event_id'
      AND tc.table_schema     = current_schema()
    LIMIT 1;

    IF v_constraint_name IS NULL THEN
        RAISE NOTICE 'No FK constraint found on events.parent_event_id — nothing to do';
        RETURN;
    END IF;

    -- Verificar si la constraint ya tiene ON DELETE SET NULL
    SELECT (confdeltype = 'n')
    INTO v_has_set_null
    FROM pg_constraint
    WHERE conname      = v_constraint_name
      AND conrelid     = 'events'::regclass
      AND contype      = 'f';

    IF v_has_set_null THEN
        RAISE NOTICE 'Constraint % already has ON DELETE SET NULL — skipping', v_constraint_name;
        RETURN;
    END IF;

    -- Recrear la constraint con ON DELETE SET NULL
    EXECUTE format(
        'ALTER TABLE events DROP CONSTRAINT %I',
        v_constraint_name
    );

    ALTER TABLE events
        ADD CONSTRAINT events_parent_event_id_fkey
        FOREIGN KEY (parent_event_id)
        REFERENCES events(id)
        ON DELETE SET NULL;

    RAISE NOTICE 'Constraint recreated with ON DELETE SET NULL';
END$$;
