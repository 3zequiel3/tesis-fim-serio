-- =============================================================================
-- 01-create-databases.sql
--
-- Inicialización de las bases de datos para FIM Platform.
-- Este script es ejecutado automáticamente por la imagen oficial de PostgreSQL
-- durante el PRIMER arranque del contenedor (cuando pg_data está vacío).
-- En reinicios posteriores NO se vuelve a ejecutar (comportamiento estándar
-- de docker-entrypoint-initdb.d/).
--
-- RN-67: el sistema usa UNA instancia de PostgreSQL con DOS bases separadas:
--   - fim       → base de la aplicación FIM Platform (backend FastAPI)
--   - fim_n8n   → base exclusiva de n8n (notificaciones)
-- Los datos de n8n y de la aplicación NO comparten tablas. La separación es
-- a nivel de base, no de usuario (D-03).
--
-- D-03: se usa un ÚNICO usuario aplicativo `fim` como owner de ambas bases.
-- No se crea un usuario separado para n8n en M1. Ver design.md D-03 para
-- el razonamiento y el trigger de revisión.
-- =============================================================================

-- -----------------------------------------------------------------------------
-- Base: fim
-- La imagen crea `fim` automáticamente vía POSTGRES_DB=fim, pero mantenemos
-- el bloque DO por defensa: si POSTGRES_DB se desactiva en el futuro, el
-- script sigue siendo autocontenido.
-- -----------------------------------------------------------------------------
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_database WHERE datname = 'fim'
    ) THEN
        PERFORM dblink_exec('dbname=postgres', 'CREATE DATABASE fim OWNER fim');
    END IF;
END
$$;

ALTER DATABASE fim OWNER TO fim;

-- -----------------------------------------------------------------------------
-- Base: fim_n8n
-- Esta base es para uso exclusivo de n8n (workflows, credenciales, historial).
-- El servicio n8n recibe DB_POSTGRESDB_DATABASE=fim_n8n para que no acceda
-- jamás a la base `fim` por error de configuración.
-- -----------------------------------------------------------------------------
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_database WHERE datname = 'fim_n8n'
    ) THEN
        CREATE DATABASE fim_n8n;
    END IF;
END
$$;

ALTER DATABASE fim_n8n OWNER TO fim;

-- D-03: n8n necesita ALL PRIVILEGES sobre fim_n8n para crear su propio schema,
-- tablas e índices al arrancar (migraciones internas de n8n).
GRANT ALL PRIVILEGES ON DATABASE fim_n8n TO fim;
