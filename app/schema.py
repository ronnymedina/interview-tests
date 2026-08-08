"""Unica puerta a Alembic desde la aplicacion.

El resto del codigo (el lifespan del servidor) llama a `apply_migrations` y no sabe que
por debajo hay un Alembic: si algun dia se cambia de herramienta, se cambia aca.

El `Config` se arma en memoria en vez de leer alembic.ini. Ese archivo es para el CLI, y
depender de el en runtime significaria que la imagen de produccion tiene que copiarlo y
que el working directory tiene que ser el correcto. Asi, lo unico que hace falta en la
imagen es el directorio `migrations/`.
"""

from pathlib import Path

from alembic import command
from alembic.config import Config

# migrations/ vive junto a app/, tanto en el repo como en la imagen (donde app/ esta en
# /app/app y migrations/ en /app/migrations).
_MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"


def _alembic_config() -> Config:
    """Config minima: solo donde estan las migraciones.

    La URL no se pasa aca. La lee `migrations/env.py` de `settings.sqlalchemy_url`, para
    que haya un solo lugar del que sale, sirva desde la app o desde el CLI.
    """
    config = Config()
    config.set_main_option("script_location", str(_MIGRATIONS_DIR))
    return config


def apply_migrations() -> None:
    """Aplica las migraciones pendientes hasta `head`.

    Es BLOQUEANTE (Alembic abre su propia conexion sincronica): desde codigo asincrono hay
    que llamarla con `asyncio.to_thread`.

    No captura nada a proposito. Si la migracion falla, la excepcion sube y el arranque se
    cae: es preferible a un servidor arriba respondiendo 500 en todo lo que toque Postgres.
    """
    command.upgrade(_alembic_config(), "head")
