"""SQLAlchemy resuelve `postgresql://` al driver psycopg2, que este proyecto no instala.
La propiedad reescribe el esquema para que apunte a psycopg 3, el que sí está."""

import pytest

from config import settings


def test_reescribe_el_esquema_a_psycopg(monkeypatch):
    monkeypatch.setattr(settings, "DATABASE_URL", "postgresql://review:review@db:5432/x")
    assert settings.sqlalchemy_url == "postgresql+psycopg://review:review@db:5432/x"


def test_acepta_el_alias_postgres(monkeypatch):
    """Algunos proveedores (Railway entre ellos) entregan la URL con el esquema `postgres://`."""
    monkeypatch.setattr(settings, "DATABASE_URL", "postgres://review:review@db:5432/x")
    assert settings.sqlalchemy_url == "postgresql+psycopg://review:review@db:5432/x"


def test_respeta_un_driver_ya_explicito(monkeypatch):
    monkeypatch.setattr(settings, "DATABASE_URL", "postgresql+psycopg://u@h/d")
    assert settings.sqlalchemy_url == "postgresql+psycopg://u@h/d"


def test_rechaza_una_url_que_no_es_postgres(monkeypatch):
    """Fallar acá da un mensaje claro; dejarlo pasar da un error opaco dentro de Alembic."""
    monkeypatch.setattr(settings, "DATABASE_URL", "mysql://u@h/d")
    with pytest.raises(ValueError, match="Postgres"):
        settings.sqlalchemy_url  # noqa: B018 -- el acceso a la propiedad es el disparador del raise
