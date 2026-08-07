"""Punto de entrada de cada corrida de Alembic.

La URL sale SIEMPRE de `settings.sqlalchemy_url`, nunca de alembic.ini: la regla del
proyecto es que las variables de entorno se leen en un unico lugar (config.py), y ademas
un DSN con credenciales no puede vivir en un archivo versionado.

`target_metadata` es None porque no hay modelos de SQLAlchemy: las migraciones se escriben
a mano con op.execute(). Sin metadata, --autogenerate no produce nada, que es lo correcto.
"""

from alembic import context
from sqlalchemy import create_engine

from config import settings

target_metadata = None


def run_migrations_offline() -> None:
    """Modo offline (`alembic upgrade --sql`): emite el SQL sin conectarse a la base."""
    context.configure(url=settings.sqlalchemy_url, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Modo normal: abre una conexion y aplica lo que falte."""
    engine = create_engine(settings.sqlalchemy_url)
    try:
        with engine.connect() as connection:
            context.configure(connection=connection)
            with context.begin_transaction():
                context.run_migrations()
    finally:
        # Sin esto el pool queda abierto: en el arranque del servidor son conexiones
        # retenidas para siempre, porque este engine no se vuelve a usar.
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
