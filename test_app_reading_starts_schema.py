"""El DDL de reading_starts está duplicado (código + init del contenedor): estos tests
existen para que no diverjan en silencio."""

from pathlib import Path

from app.storage import _SCHEMA

_SQL_FILE = Path(__file__).parent / "docker" / "initdb" / "05-reading-starts.sql"


def _statement():
    for statement in _SCHEMA:
        if "reading_starts" in statement and "CREATE TABLE" in statement:
            return statement
    raise AssertionError("reading_starts no está en _SCHEMA")


def test_schema_incluye_reading_starts():
    ddl = _statement()
    assert "user_id" in ddl
    assert "reading_id" in ddl


def test_no_guarda_contenido():
    """La cuota se cuenta sin persistir ni el audio ni el resultado del assessment."""
    ddl = _statement().lower()
    for forbidden in ("body", "excerpt", "audio", "scores", "words"):
        assert forbidden not in ddl


def test_hay_indice_por_user_id():
    """Sin él, contar la cuota escanea la tabla entera en cada evaluación."""
    assert any(
        "CREATE INDEX" in s and "reading_starts" in s and "user_id" in s for s in _SCHEMA
    )


def test_el_sql_del_contenedor_coincide_con_el_schema():
    sql = _SQL_FILE.read_text()
    assert "CREATE TABLE IF NOT EXISTS reading_starts" in sql
    assert "reading_starts_user_idx" in sql
