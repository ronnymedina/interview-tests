-- Cuota de la practica de lectura: una fila por evaluacion.
-- No guarda contenido (ni audio ni resultado del assessment), solo la contabilidad.
-- Sin FK a reading_texts a proposito: si un articulo desaparece del catalogo, borrar en
-- cascada un registro de cuota ya cobrada seria incorrecto.
CREATE TABLE IF NOT EXISTS reading_starts (
    id         INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    user_id    TEXT NOT NULL,
    reading_id INTEGER NOT NULL
);

-- Sin este indice, contar la cuota escanea la tabla entera en cada evaluacion.
CREATE INDEX IF NOT EXISTS reading_starts_user_idx ON reading_starts (user_id);
