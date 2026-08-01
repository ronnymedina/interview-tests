-- Esquema inicial del módulo migrado (app/). Postgres ejecuta los .sql de
-- docker-entrypoint-initdb.d una sola vez, al crear el volumen de datos.
-- Debe coincidir con el DDL de PostgresStorage.init_schema() (app/storage.py).

CREATE TABLE IF NOT EXISTS conversation_configs (
    id           INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL,
    name         TEXT NOT NULL,
    user_context TEXT NOT NULL
);
