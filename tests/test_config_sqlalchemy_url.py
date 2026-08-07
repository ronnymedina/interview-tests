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
        _ = settings.sqlalchemy_url


def test_rechaza_un_driver_explicito_que_no_es_psycopg(monkeypatch):
    """`postgresql+psycopg2://` o `+asyncpg://` no revientan claro: SQLAlchemy los acepta y
    falla mucho más adentro, con un error que no dice que el proyecto solo instala psycopg 3."""
    monkeypatch.setattr(settings, "DATABASE_URL", "postgresql+asyncpg://u@h/d")
    with pytest.raises(ValueError, match="psycopg"):
        _ = settings.sqlalchemy_url


def test_rechaza_psycopg2_explicito(monkeypatch):
    monkeypatch.setattr(settings, "DATABASE_URL", "postgresql+psycopg2://u@h/d")
    with pytest.raises(ValueError, match="psycopg2"):
        _ = settings.sqlalchemy_url
