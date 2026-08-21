-- Migration 011: 19 columnas de fecha migran a timestamptz (D39/RN-133).
--
-- El instante que estas columnas guardan es UTC por convención, no por tipo:
-- hoy son `timestamp without time zone` y su significado depende de que la
-- zona de la sesión de PostgreSQL sea UTC (default de la imagen, nadie lo
-- configuró explícitamente). Esa dependencia implícita está por debajo de la
-- ventana anti-replay de RN-90/RN-131, que es un control de seguridad, y es
-- la causa estructural de que la API sirva instantes sin desfase y de que la
-- consola los muestre corridos por el huso horario del operador.
--
-- Después de este script, el tipo de la columna —no la configuración de la
-- sesión— es lo que declara el significado de un instante persistido.
--
-- CAST IMPLÍCITO, NO `USING columna AT TIME ZONE 'UTC'` (D-1 del design):
-- ambas formas producen valores idénticos (verificado con EXCEPT: 0 filas
-- divergentes), pero `USING` fuerza la reescritura completa de la tabla
-- (411 ms sobre 300k filas indexadas) mientras que el cast implícito bajo
-- una sesión en UTC es solo metadata (73 ms, mismo filenode). La semántica
-- de D39 se preserva exactamente; lo que cambia es la forma de expresarla.
--
-- PRECONDICIÓN QUE ESTE SCRIPT NO ASUME, VERIFICA: bajo el cast implícito,
-- una sesión que NO esté en UTC interpretaría los valores naive en la zona
-- equivocada y corrompería todos los instantes en silencio. Por eso la
-- primera sentencia fija la zona y la segunda aborta si no se pudo fijar
-- correctamente, antes de tocar una sola columna.
--
-- Idempotente: cada ALTER corre solo si la columna todavía es
-- `timestamp without time zone` (consultando information_schema.columns).
-- Ejecutar el script dos veces no produce error y la segunda corrida no
-- hace nada — lo que además la vuelve segura de repetir si la primera se
-- interrumpió a mitad.
--
-- Reversión (metadata-only, sin pérdida, bajo la misma precondición de
-- sesión UTC): ALTER TABLE <t> ALTER COLUMN <c> TYPE timestamp;
--
-- Aplicar manualmente contra la base de datos de producción o test (D3, sin Alembic),
-- con el backend detenido (docker compose stop backend) y un pg_dump previo:
--   psql $DATABASE_URL -f 011_timestamptz.sql

SET TimeZone = 'UTC';

DO $$
BEGIN
    IF current_setting('TimeZone') <> 'UTC' AND current_setting('TimeZone') <> 'Etc/UTC' THEN
        RAISE EXCEPTION
            'migration 011 requires an UTC session (TimeZone=%); aborting before altering any column to avoid silently corrupting naive instants under the implicit cast',
            current_setting('TimeZone');
    END IF;
END $$;

DO $$
DECLARE
    targets CONSTANT text[][] := ARRAY[
        ['agents', 'last_heartbeat'],
        ['alerts', 'created_at'],
        ['alerts', 'delivered_at'],
        ['alerts', 'failed_at'],
        ['audit_log', 'created_at'],
        ['baseline_entries', 'last_updated'],
        ['events', 'created_at'],
        ['events', 'detected_at'],
        ['events', 'received_at'],
        ['events', 'resolved_at'],
        ['published_commands', 'acked_at'],
        ['published_commands', 'published_at'],
        ['rejected_events_audit', 'detected_at'],
        ['rejected_events_audit', 'received_at'],
        ['revoked_certificates', 'revoked_at'],
        ['rules', 'created_at'],
        ['rules', 'updated_at'],
        ['ruleset_versions', 'updated_at'],
        ['users', 'created_at']
    ];
    t text;
    c text;
    i int;
BEGIN
    FOR i IN 1 .. array_length(targets, 1) LOOP
        t := targets[i][1];
        c := targets[i][2];

        IF EXISTS (
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = t
              AND column_name = c
              AND data_type = 'timestamp without time zone'
        ) THEN
            EXECUTE format('ALTER TABLE %I ALTER COLUMN %I TYPE timestamptz;', t, c);
        END IF;
    END LOOP;
END $$;
