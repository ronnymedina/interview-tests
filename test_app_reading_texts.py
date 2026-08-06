"""Verifica el DDL de reading_texts: que esté en el esquema de código y que el .sql del
contenedor no haya divergido. El DDL vive duplicado a propósito (app/storage.py para uso
standalone, docker/initdb para el arranque del contenedor); estos tests son la red que
detecta que uno de los dos se quedó atrás."""

from pathlib import Path

from app.storage import _SCHEMA

_INITDB_SQL = Path(__file__).parent / "docker" / "initdb" / "04-reading-texts.sql"

# Columnas que la fase 2 necesita para ingerir y servir textos.
_COLUMNS = (
    "created_at",
    "updated_at",
    "source",
    "source_url",
    "title",
    "level",
    "category",
    "published_at",
    "body",
)


def test_schema_includes_reading_texts():
    schema_sql = " ".join(_SCHEMA)
    assert "reading_texts" in schema_sql
    for column in _COLUMNS:
        assert column in schema_sql, f"falta la columna {column}"


def test_source_url_is_unique():
    """La unicidad de source_url es lo que hace idempotente al job de ingesta."""
    schema_sql = " ".join(_SCHEMA)
    assert "source_url   TEXT NOT NULL UNIQUE" in schema_sql


def test_level_is_nullable():
    """level debe admitir NULL: 'no sé el nivel' y 'nivel 0' son cosas distintas."""
    schema_sql = " ".join(_SCHEMA)
    assert "level        INTEGER," in schema_sql


def test_schema_has_index_as_separate_statement():
    """psycopg ejecuta una sentencia por execute(): el índice va en su propio elemento."""
    index_statements = [s for s in _SCHEMA if "CREATE INDEX" in s]
    assert len(index_statements) == 1
    assert "reading_texts_level_idx" in index_statements[0]


def test_initdb_sql_matches_schema():
    sql = _INITDB_SQL.read_text()
    assert "CREATE TABLE IF NOT EXISTS reading_texts" in sql
    assert "reading_texts_level_idx" in sql
    for column in _COLUMNS:
        assert column in sql, f"falta la columna {column} en el .sql del contenedor"
