"""La migracion inicial es la unica fuente del esquema. Estos tests no la re-transcriben:
verifican las decisiones de diseño que se tomaron al definir las tablas y que un cambio
descuidado podria revertir sin que nadie lo note."""

from pathlib import Path

import pytest

_MIGRACION = (
    Path(__file__).resolve().parents[1]
    / "migrations"
    / "versions"
    / "0001_esquema_inicial.py"
)


@pytest.fixture(scope="module")
def sql():
    return _MIGRACION.read_text()


@pytest.mark.parametrize(
    "tabla",
    [
        "usage_events",
        "conversation_starts",
        "pilot_feedback",
        "reading_texts",
        "reading_starts",
    ],
)
def test_crea_todas_las_tablas(sql, tabla):
    assert f"CREATE TABLE IF NOT EXISTS {tabla}" in sql


def test_no_crea_conversation_configs(sql):
    """Se elimino junto con su CRUD: nadie la usaba."""
    assert "conversation_configs" not in sql


def test_es_idempotente(sql):
    """La base de Railway ya tiene estas tablas. Sin IF NOT EXISTS, el primer upgrade
    revienta y habria que hacer un `alembic stamp head` a mano contra produccion."""
    assert "CREATE TABLE " not in sql.replace("CREATE TABLE IF NOT EXISTS ", "")
    assert "CREATE INDEX " not in sql.replace("CREATE INDEX IF NOT EXISTS ", "")


def test_source_url_es_unica(sql):
    """La unicidad de source_url es lo que hace idempotente al job de ingesta."""
    assert "source_url   TEXT NOT NULL UNIQUE" in sql


def test_level_admite_null(sql):
    """'No se el nivel' y 'nivel 0' son cosas distintas."""
    assert "level        INTEGER," in sql


def test_reading_starts_no_guarda_contenido(sql):
    """La cuota se cuenta sin persistir ni el audio ni el resultado del assessment."""
    inicio = sql.index("CREATE TABLE IF NOT EXISTS reading_starts")
    ddl = sql[inicio : sql.index(");", inicio)].lower()
    for prohibido in ("body", "excerpt", "audio", "scores", "words"):
        assert prohibido not in ddl


@pytest.mark.parametrize(
    "indice",
    ["reading_texts_level_idx", "reading_starts_user_idx"],
)
def test_crea_los_indices(sql, indice):
    """Sin ellos, filtrar por nivel y contar la cuota escanean la tabla entera."""
    assert f"CREATE INDEX IF NOT EXISTS {indice}" in sql


def test_es_la_primera_revision(sql):
    assert "down_revision = None" in sql


@pytest.mark.integration
def test_upgrade_head_crea_las_tablas():
    """Corre la migracion de verdad contra el Postgres de settings.DATABASE_URL.

    Es lo unico que prueba que el SQL es valido: los tests de arriba leen texto de la
    revision 0001 nomas, asi que una 0002 que revirtiera una decision de diseño (por
    ejemplo un `DROP CONSTRAINT reading_texts_source_url_key`) los dejaria en verde. Esta
    prueba, en cambio, mira el esquema RESULTANTE en information_schema/pg_indexes
    despues de `upgrade head`, asi que vale para cualquier revision futura y no solo para
    la inicial.

    Queda fuera del stage `test` del Dockerfile, que no levanta servicios.
    """
    import psycopg

    from app.schema import apply_migrations
    from config import settings

    apply_migrations()

    esperadas = {
        "usage_events",
        "conversation_starts",
        "pilot_feedback",
        "reading_texts",
        "reading_starts",
        "alembic_version",
    }
    with psycopg.connect(settings.DATABASE_URL) as conn:
        filas = conn.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
        ).fetchall()
        assert esperadas <= {fila[0] for fila in filas}

        # source_url tiene que seguir siendo UNIQUE: es lo que hace idempotente la
        # ingesta (el UPSERT del scraper depende de este constraint).
        unicidad = conn.execute(
            """
            SELECT 1
            FROM information_schema.table_constraints tc
            JOIN information_schema.constraint_column_usage ccu
                ON tc.constraint_name = ccu.constraint_name
            WHERE tc.table_name = 'reading_texts'
                AND tc.constraint_type = 'UNIQUE'
                AND ccu.column_name = 'source_url'
            """
        ).fetchone()
        assert unicidad is not None

        # level tiene que admitir NULL: "no se el nivel" y "nivel 0" son cosas distintas.
        nullability = conn.execute(
            """
            SELECT is_nullable
            FROM information_schema.columns
            WHERE table_name = 'reading_texts' AND column_name = 'level'
            """
        ).fetchone()
        assert nullability == ("YES",)

        # Sin estos indices, filtrar por nivel y contar la cuota escanean la tabla entera.
        indices = conn.execute(
            """
            SELECT indexname FROM pg_indexes
            WHERE indexname IN ('reading_texts_level_idx', 'reading_starts_user_idx')
            """
        ).fetchall()
        assert {fila[0] for fila in indices} == {
            "reading_texts_level_idx",
            "reading_starts_user_idx",
        }

        # reading_starts cuenta la cuota sin persistir contenido: ni audio, ni el texto,
        # ni el resultado del assessment.
        columnas = conn.execute(
            """
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'reading_starts'
            """
        ).fetchall()
        nombres_columnas = {fila[0] for fila in columnas}
        for prohibido in ("body", "excerpt", "audio", "scores", "words"):
            assert prohibido not in nombres_columnas
