"""app/schema.py es la unica puerta a Alembic desde la app. Estos tests verifican el
cableado (que se le pida `head`, con el script_location correcto) sin tocar Postgres."""

from pathlib import Path

import pytest

from app import schema


def test_apply_migrations_pide_head(monkeypatch):
    llamadas = []
    monkeypatch.setattr(
        schema.command, "upgrade", lambda config, revision: llamadas.append((config, revision))
    )

    schema.apply_migrations()

    assert len(llamadas) == 1
    _config, revision = llamadas[0]
    assert revision == "head"


def test_el_script_location_existe(monkeypatch):
    """Si la ruta no apunta al directorio real, Alembic no encuentra ninguna revision y
    `upgrade head` no hace nada, en silencio. Es el fallo mas caro de este modulo."""
    capturado = {}
    monkeypatch.setattr(
        schema.command, "upgrade", lambda config, revision: capturado.update(config=config)
    )

    schema.apply_migrations()

    location = Path(capturado["config"].get_main_option("script_location"))
    assert (location / "env.py").is_file()
    assert (location / "versions" / "0001_esquema_inicial.py").is_file()


def test_propaga_el_error_de_alembic(monkeypatch):
    """No se traga la excepcion: el arranque tiene que caerse si la migracion falla."""

    def explota(config, revision):
        raise RuntimeError("no se pudo conectar")

    monkeypatch.setattr(schema.command, "upgrade", explota)

    with pytest.raises(RuntimeError, match="no se pudo conectar"):
        schema.apply_migrations()
