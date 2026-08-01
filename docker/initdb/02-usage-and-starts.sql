-- Tablas operativas del piloto (app/limits): costo por evento y cuota por usuario.
-- Postgres ejecuta los .sql de docker-entrypoint-initdb.d una sola vez, al crear el volumen.
-- Debe coincidir con el DDL de PostgresStorage.init_schema() (app/storage.py).

CREATE TABLE IF NOT EXISTS usage_events (
    id              INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    user_id         TEXT NOT NULL,
    conversation_id TEXT NOT NULL,
    provider        TEXT NOT NULL,          -- 'gemini' | 'azure'
    kind            TEXT NOT NULL,          -- 'synthesis' | 'question' | 'feedback' | 'assessment'
    input_tokens    INTEGER NOT NULL DEFAULT 0,
    output_tokens   INTEGER NOT NULL DEFAULT 0,
    audio_seconds   REAL NOT NULL DEFAULT 0,
    cost_usd        NUMERIC(10,6) NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS conversation_starts (
    id              INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    user_id         TEXT NOT NULL,
    conversation_id TEXT NOT NULL
);
