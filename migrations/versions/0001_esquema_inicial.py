"""Esquema inicial

Es el esquema que el proyecto ya tenia, transcrito tal cual desde el _SCHEMA de
app/storage.py y los .sql de docker/initdb, que esta migracion reemplaza.

Va con IF NOT EXISTS a proposito. La base de Railway YA tiene estas tablas: una migracion
idempotente se aplica ahi sin romper nada y deja escrita la fila en alembic_version, asi
que no hace falta un `alembic stamp head` manual contra produccion. De la 0002 en adelante
las migraciones se escriben normales, sin IF NOT EXISTS, porque Alembic ya sabe desde
donde arranca.

Revision ID: 0001
Revises:
"""

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
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
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS conversation_starts (
            id              INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            user_id         TEXT NOT NULL,
            conversation_id TEXT NOT NULL
        );
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS pilot_feedback (
            id            INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
            user_id       TEXT NOT NULL,
            liked         BOOLEAN,                  -- like / dislike
            rating        INTEGER,                  -- 1..5
            comment       TEXT NOT NULL DEFAULT '',
            wants_more    BOOLEAN,                  -- ¿te interesarian mas funciones?
            suggestions   TEXT NOT NULL DEFAULT ''  -- cuales
        );
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS reading_texts (
            id           INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
            source       TEXT NOT NULL,            -- que scraper lo trajo, p.ej. 'engoo'
            source_url   TEXT NOT NULL UNIQUE,     -- clave natural: hace idempotente la ingesta
            title        TEXT NOT NULL,
            level        INTEGER,                  -- 1..9 en Engoo; NULL si la fuente no lo informa
            category     TEXT NOT NULL DEFAULT '',
            published_at TEXT NOT NULL DEFAULT '', -- fecha tal como la publica la fuente
            body         TEXT NOT NULL             -- articulo COMPLETO e intacto
        );
        """
    )
    # El filtro por rango de nivel es la consulta principal al servir un texto al azar.
    op.execute(
        "CREATE INDEX IF NOT EXISTS reading_texts_level_idx ON reading_texts (level);"
    )
    # Sin FK a reading_texts a proposito: si un articulo desaparece del catalogo, borrar en
    # cascada un registro de cuota ya cobrada seria incorrecto.
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS reading_starts (
            id         INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            user_id    TEXT NOT NULL,
            reading_id INTEGER NOT NULL
        );
        """
    )
    # Sin este indice, contar la cuota escanea la tabla entera en cada evaluacion.
    op.execute(
        "CREATE INDEX IF NOT EXISTS reading_starts_user_idx ON reading_starts (user_id);"
    )


def downgrade() -> None:
    """Sin vuelta atras a proposito.

    Revertir el esquema inicial es dropear todas las tablas del proyecto, o sea perder
    todos los datos. No hay ningun escenario en que eso sea lo que alguien queria.
    """
    raise NotImplementedError("El esquema inicial no se revierte: seria borrar toda la base.")
