"""Punto de entrada de cada corrida de Alembic.

La URL sale SIEMPRE de `settings.sqlalchemy_url`, nunca de alembic.ini: la regla del
proyecto es que las variables de entorno se leen en un unico lugar (config.py), y ademas
un DSN con credenciales no puede vivir en un archivo versionado.

`target_metadata` es None porque no hay modelos de SQLAlchemy: las migraciones se escriben
a mano con op.execute(). Sin metadata, --autogenerate no produce nada, que es lo correcto.
"""

from logging.config import fileConfig

from alembic import context
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine

from config import settings

# Solo el CLI trae un archivo de configuracion (alembic.ini). app/schema.py arma su Config
# en memoria, sin archivo, para no depender de el en runtime: ahi `config_file_name` es
# None y no hay nada que configurar (la app ya tiene su propio logging en
# app/logconfig.py). Sin este chequeo, `uv run alembic upgrade head` corre en silencio
# absoluto: los bloques [loggers]/[handlers]/[formatters] de alembic.ini quedan sin usar.
if context.config.config_file_name is not None:
    fileConfig(context.config.config_file_name)

target_metadata = None


def process_revision_directives(context_, revision, directives):
    """Numera los archivos nuevos 0002, 0003... en vez del hash aleatorio que genera
    Alembic por default.

    El docstring de 0001 promete esta numeracion ("de la 0002 en adelante...") y el
    README y CLAUDE.md documentan `alembic revision`: sin este hook ese comando produce
    un id tipo '8f3a2b1c4d5e' y quedan dos convenciones conviviendo en
    migrations/versions/. Requiere `revision_environment = true` en alembic.ini para que
    el CLI ejecute este env.py tambien al generar una revision, no solo al aplicarlas.
    """
    script = directives[0]
    head_revision = ScriptDirectory.from_config(context_.config).get_current_head()
    proximo = 1 if head_revision is None else int(head_revision.lstrip("0") or "0") + 1
    script.rev_id = f"{proximo:04d}"


def run_migrations_offline() -> None:
    """Modo offline (`alembic upgrade --sql`): emite el SQL sin conectarse a la base."""
    context.configure(
        url=settings.sqlalchemy_url,
        literal_binds=True,
        process_revision_directives=process_revision_directives,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Modo normal: abre una conexion y aplica lo que falte."""
    engine = create_engine(settings.sqlalchemy_url)
    try:
        with engine.connect() as connection:
            context.configure(
                connection=connection,
                process_revision_directives=process_revision_directives,
            )
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
