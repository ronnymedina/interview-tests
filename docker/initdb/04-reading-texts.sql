-- Catálogo de textos de lectura (app/reading). Se puebla con un job de ingesta desde
-- fuentes externas; acá solo se crea la estructura.
-- Postgres ejecuta los .sql de docker-entrypoint-initdb.d una sola vez, al crear el volumen.
-- Debe coincidir con el DDL de PostgresStorage.init_schema() (app/storage.py).

CREATE TABLE IF NOT EXISTS reading_texts (
    id           INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    source       TEXT NOT NULL,            -- qué scraper lo trajo, p.ej. 'engoo'
    source_url   TEXT NOT NULL UNIQUE,     -- clave natural: hace idempotente la ingesta
    title        TEXT NOT NULL,
    level        INTEGER,                  -- 1..9 en Engoo; NULL si la fuente no lo informa
    category     TEXT NOT NULL DEFAULT '',
    published_at TEXT NOT NULL DEFAULT '', -- fecha tal como la publica la fuente
    body         TEXT NOT NULL             -- artículo COMPLETO e intacto
);

-- El filtro por rango de nivel es la consulta principal al servir un texto al azar.
CREATE INDEX IF NOT EXISTS reading_texts_level_idx ON reading_texts (level);
