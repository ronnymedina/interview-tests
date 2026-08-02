-- Tabla del feedback del piloto (app/feedback). Postgres ejecuta los .sql de
-- docker-entrypoint-initdb.d una sola vez, al crear el volumen de datos.
-- Debe coincidir con el DDL de PostgresStorage.init_schema() (app/storage.py).

CREATE TABLE IF NOT EXISTS pilot_feedback (
    id            INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    user_id       TEXT NOT NULL,
    liked         BOOLEAN,                  -- like / dislike
    rating        INTEGER,                  -- 1..5
    comment       TEXT NOT NULL DEFAULT '',
    wants_more    BOOLEAN,                  -- ¿te interesarían más funciones?
    suggestions   TEXT NOT NULL DEFAULT ''  -- cuáles
);
