# Esquema con fuente única en Alembic — Plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Dejar una sola fuente del esquema de Postgres — migraciones de Alembic — aplicada por un único camino que funciona igual en Compose, en Railway y sin Docker, y eliminar de paso la tabla `conversation_configs` y su CRUD, que no usa nadie.

**Architecture:** Migraciones versionadas escritas a mano con `op.execute()`, sin modelos de SQLAlchemy y sin autogeneración. `app/schema.py` encapsula la llamada a Alembic; el `lifespan` de FastAPI la invoca en un hilo aparte y deja propagar la excepción si falla. Desaparecen `_SCHEMA`, los dos `init_schema()`, `docker/initdb/` y el paso manual de `psql` del DEPLOY.

**Tech Stack:** Python 3.11+, FastAPI, psycopg 3, Alembic (arrastra SQLAlchemy como dependencia dura), pytest, uv, Docker.

**Spec:** `docs/superpowers/specs/2026-08-07-esquema-fuente-unica-alembic-design.md`

## Global Constraints

- Todo el texto del proyecto va en español: docstrings, comentarios, mensajes de commit. Identificadores en inglés.
- `config.py` es el **único** lugar que lee variables de entorno. Nada de `os.getenv` fuera de ahí.
- Nada bloqueante dentro del event loop: lo sincrónico va con `asyncio.to_thread`.
- `ruff` con `line-length = 100`. Se corre `uv run ruff check .`; **no** se corre `ruff format`.
- `mypy` se corre sobre `app config.py`. Los módulos de la lista de estrictos en `pyproject.toml` no pueden salir de ella; los módulos nuevos entran.
- Cobertura: `fail_under = 68` en `pyproject.toml`. Verificar con `uv run coverage run -m pytest -m "not integration" && uv run coverage report` antes de cada commit que borre o agregue código.
- Alembic va en `[project] dependencies`, **no** en el grupo `dev`: la imagen de producción hace `uv sync --no-dev` y el proceso web tiene que importarlo.
- Las migraciones se escriben a mano con `op.execute()`. Nunca `alembic revision --autogenerate`.
- Los tests que necesitan Postgres real van marcados `@pytest.mark.integration`.

---

## File Structure

| Archivo | Responsabilidad |
|---|---|
| `alembic.ini` | Config del **CLI** de Alembic (`uv run alembic revision`). Sin `sqlalchemy.url` |
| `migrations/env.py` | Punto de entrada de cada corrida: toma la URL de `settings.sqlalchemy_url` y abre la conexión |
| `migrations/script.py.mako` | Plantilla de las migraciones nuevas |
| `migrations/versions/0001_esquema_inicial.py` | El esquema actual, idempotente |
| `app/schema.py` | **Nuevo.** Única puerta a Alembic desde la app: `apply_migrations()` |
| `config.py` | Suma la propiedad `sqlalchemy_url` |
| `app/cmd/server.py` | El `lifespan` llama a `apply_migrations`; se van los 5 endpoints de configs |
| `app/storage.py` | Pierde `_SCHEMA` y los dos `init_schema()`; queda como fábrica de conexiones |
| `app/conversation/repository.py`, `app/conversation/model.py` | **Se borran** |

---

### Task 1: Eliminar `conversation_configs` y su CRUD

Código muerto: el frontend nunca llama a `/conversation/configs` y no hay un solo test que lo cubra. Va primero y solo, para que el diff de la migración a Alembic no venga mezclado con borrado.

**Files:**
- Delete: `app/conversation/repository.py`, `app/conversation/model.py`, `docker/initdb/01-conversation_configs.sql`
- Modify: `app/conversation/schemas.py`, `app/conversation/__init__.py`, `app/cmd/server.py`, `app/storage.py`, `app/feedback/repository.py:1-8`, `app/limits/repository.py:61`, `pyproject.toml`

**Interfaces:**
- Consumes: nada.
- Produces: `app.conversation` deja de exportar `ConversationConfig`, `ConversationRepository`, `ConfigRequest` y `AnswerRequest`. Solo quedan `AnswerRequest`→(borrado), `StartRequest`, y el resto del grafo/servicio.

- [ ] **Step 1: Confirmar que nada lo usa**

Run:
```bash
grep -rn "conversation_configs\|ConversationConfig\|ConfigRequest\|AnswerRequest\|ConversationRepository\|/configs" app tests --include="*.py" --include="*.js" --include="*.html"
```

Esperado: los únicos hits están en los archivos que este task toca (`app/cmd/server.py`, `app/conversation/*`, `app/storage.py`) más dos docstrings que mencionan `ConversationRepository` como referencia de patrón (`app/feedback/repository.py`, `app/limits/repository.py`). **Cero** hits en `tests/` y cero en `app/web/`. Si aparece alguno más, parar y reportarlo.

- [ ] **Step 2: Borrar los archivos muertos**

```bash
git rm app/conversation/repository.py app/conversation/model.py docker/initdb/01-conversation_configs.sql
```

- [ ] **Step 3: Sacar los esquemas muertos de `app/conversation/schemas.py`**

Borrar por completo las clases `AnswerRequest` y `ConfigRequest`. Queda solo `_stripped_non_empty` y `StartRequest`. Actualizar el docstring del módulo, que hoy habla en plural de "los esquemas":

```python
"""Esquema de entrada de la API de conversación, con validación en Pydantic.

La validación vive en la clase (no en `if`s dispersos por los endpoints): los campos se
normalizan y validan con `field_validator` / restricciones de `Field`. Si algo no cumple,
Pydantic lanza `ValidationError` y FastAPI responde 422 automáticamente. El endpoint
recibe datos ya limpios y confiables.

`POST /conversation/answer` no tiene esquema: recibe multipart (audio + transcript) y
valida sus campos inline.
"""
```

- [ ] **Step 4: Limpiar `app/conversation/__init__.py`**

Reemplazar el archivo entero por:

```python
"""Módulo de conversación: el grafo de práctica y su orquestación."""

from .graph import (
    FeedbackReport,
    PhraseSuggestion,
    PracticeWord,
    State,
    build_graph,
    initial_state,
)
from .schemas import StartRequest
from .service import ConversationError, ConversationService, build_service
from .synthesizer import Synthesizer

__all__ = [
    "ConversationError",
    "ConversationService",
    "FeedbackReport",
    "PhraseSuggestion",
    "PracticeWord",
    "StartRequest",
    "State",
    "Synthesizer",
    "build_graph",
    "build_service",
    "initial_state",
]
```

- [ ] **Step 5: Limpiar `app/cmd/server.py`**

Cinco ediciones:

1. En el import de `app.conversation` (líneas ~40-45), dejar solo lo que sobrevive:

```python
from app.conversation import ConversationError, ConversationService
```

2. Borrar la línea `_repository = ConversationRepository(_storage)` y el comentario de dos líneas que la precede ("El almacenamiento es perezoso…"). Ese comentario explica por qué `_storage` puede construirse sin conectar, así que **moverlo** arriba de `_storage = PostgresStorage(settings.DATABASE_URL)` en vez de borrarlo.

3. Borrar la función `get_repository()` entera.

4. Borrar el bloque completo desde el comentario `# --- configuraciones guardadas (CRUD sobre conversation_configs) ---` hasta el final de `config_delete`, o sea las cinco funciones `config_create`, `config_list`, `config_get`, `config_update`, `config_delete`.

5. En el docstring del módulo, la línea que dice:

```
Composition root: al arrancar se construyen UNA vez el servicio de conversación (grafo +
sintetizador) y el repositorio de configuraciones guardadas (Postgres), y se inyectan a
los endpoints.
```

pasa a:

```
Composition root: al arrancar se construye UNA vez el servicio de conversación (grafo +
sintetizador) y se inyecta a los endpoints.
```

Y la línea `La validación de entrada vive en los esquemas Pydantic (`StartRequest`, `ConfigRequest`);` pasa a `La validación de entrada vive en el esquema Pydantic `StartRequest`;`.

- [ ] **Step 6: Sacar la tabla de `_SCHEMA` en `app/storage.py`**

Borrar el primer elemento de la tupla `_SCHEMA`, el `CREATE TABLE IF NOT EXISTS conversation_configs (...)`. Los otros seis quedan. (`_SCHEMA` entero desaparece en el Task 5; acá solo se lo mantiene coherente para que los tests sigan pasando.)

- [ ] **Step 7: Corregir los docstrings que citan `ConversationRepository`**

En `app/feedback/repository.py`, el docstring del módulo dice "Mismo patrón que `ConversationRepository`." — borrar esa oración. En `app/limits/repository.py:61`, dice "Sigue el mismo patrón que ConversationRepository: abre una conexión nueva por operación" — cambiar a "Abre una conexión nueva por operación".

- [ ] **Step 8: Sacar los módulos borrados de la lista de estrictos de mypy**

En `pyproject.toml`, dentro del `[[tool.mypy.overrides]]` de módulos estrictos, borrar estas dos líneas:

```toml
    "app.conversation.model",
    "app.conversation.repository",
```

- [ ] **Step 9: Verificar que todo pasa**

Run:
```bash
uv run ruff check . && uv run mypy app config.py && uv run pytest -m "not integration"
```
Esperado: los tres en verde. Ningún test referenciaba lo borrado, así que no debería fallar nada.

- [ ] **Step 10: Verificar que la cobertura subió**

Run:
```bash
uv run coverage run -m pytest -m "not integration" && uv run coverage report
```
Esperado: total **por encima** de 70,35 % (el valor de antes del cambio). Se borró código sin tests, así que el porcentaje tiene que subir. Si bajó, algo que sí estaba cubierto se borró de más — parar y revisar.

- [ ] **Step 11: Commit**

```bash
git add -A
git commit -m "refactor: elimina conversation_configs y su CRUD sin uso

El frontend nunca llamo a /conversation/configs y no habia un solo test
que lo cubriera. Se van el repositorio, el modelo, los cinco endpoints y
los esquemas ConfigRequest y AnswerRequest, que tampoco se usaba.

La tabla en Railway se borra a mano."
```

---

### Task 2: Instalar Alembic y montar el andamiaje

Alembic queda instalado y el CLI funciona, pero todavía no hay migraciones ni cambia el arranque de la app.

**Files:**
- Create: `alembic.ini`, `migrations/env.py`, `migrations/script.py.mako`
- Modify: `pyproject.toml`, `config.py`
- Test: `tests/test_config_sqlalchemy_url.py`

**Interfaces:**
- Consumes: nada del Task 1.
- Produces: `settings.sqlalchemy_url -> str`, propiedad de `Settings` en `config.py`. Devuelve `DATABASE_URL` con el esquema reescrito a `postgresql+psycopg://`. La consumen `migrations/env.py` (Task 2) y nada más.

- [ ] **Step 1: Escribir el test de la URL**

Crear `tests/test_config_sqlalchemy_url.py`:

```python
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
        settings.sqlalchemy_url
```

- [ ] **Step 2: Correr el test para verlo fallar**

Run: `uv run pytest tests/test_config_sqlalchemy_url.py -v`
Esperado: FAIL con `AttributeError: 'Settings' object has no attribute 'sqlalchemy_url'`.

- [ ] **Step 3: Agregar la propiedad a `config.py`**

Justo debajo de la propiedad `log_format_resolved`, dentro de la clase `Settings`:

```python
    @property
    def sqlalchemy_url(self) -> str:
        """`DATABASE_URL` en el dialecto que entiende SQLAlchemy, que es lo que usa Alembic.

        psycopg lee `postgresql://` sin problema, pero SQLAlchemy resuelve ese esquema al
        driver psycopg2, que este proyecto no instala. Hay que pedirle psycopg 3 de forma
        explicita con `postgresql+psycopg://`. Se acepta ademas el alias `postgres://`,
        que es como lo entregan algunos proveedores gestionados.
        """
        url = self.DATABASE_URL
        for prefix in ("postgresql+", "postgresql://", "postgres://"):
            if url.startswith(prefix):
                if prefix == "postgresql+":
                    return url
                return "postgresql+psycopg://" + url[len(prefix) :]
        raise ValueError(
            f"DATABASE_URL no apunta a Postgres: {url!r}. El proyecto solo soporta Postgres."
        )
```

- [ ] **Step 4: Correr el test para verlo pasar**

Run: `uv run pytest tests/test_config_sqlalchemy_url.py -v`
Esperado: los 4 en PASS.

- [ ] **Step 5: Instalar Alembic como dependencia de producción**

Run:
```bash
uv add alembic
```

Verificar que quedó en `[project] dependencies` de `pyproject.toml` y **no** en `[dependency-groups] dev`. Agregarle el comentario que explica por qué, arriba de la línea, siguiendo el estilo del resto del bloque:

```toml
    # Migraciones del esquema. Va en produccion y no en dev porque el lifespan del servidor
    # corre `upgrade head` al arrancar. Arrastra SQLAlchemy como dependencia dura, aunque el
    # proyecto no lo use como ORM: las migraciones se escriben a mano con op.execute().
    "alembic>=1.16",
```

- [ ] **Step 6: Crear `alembic.ini`**

Es **solo para el CLI** (`uv run alembic revision`). La app no lo lee: `app/schema.py` arma su `Config` en memoria (Task 5).

```ini
# Configuracion del CLI de Alembic. La app NO lee este archivo: app/schema.py arma su
# propio Config en memoria, asi que el esquema se aplica igual aunque el .ini no este
# en la imagen.
#
#   uv run alembic revision -m "descripcion"   # crea una migracion vacia
#   uv run alembic upgrade head                # la aplica
#   uv run alembic current                     # que version tiene la base
#
# NO se usa --autogenerate: el proyecto no tiene modelos de SQLAlchemy de donde derivar
# el esquema. Las migraciones se escriben a mano con op.execute().

[alembic]
script_location = migrations

# Para que `from config import settings` funcione al correr el CLI desde la raiz.
prepend_sys_path = .

# sqlalchemy.url NO va aca a proposito: es un secreto y este archivo esta versionado.
# migrations/env.py la toma de settings.sqlalchemy_url.

[loggers]
keys = root,sqlalchemy,alembic

[handlers]
keys = console

[formatters]
keys = generic

[logger_root]
level = WARNING
handlers = console
qualname =

[logger_sqlalchemy]
level = WARNING
handlers =
qualname = sqlalchemy.engine

[logger_alembic]
level = INFO
handlers =
qualname = alembic

[handler_console]
class = StreamHandler
args = (sys.stderr,)
level = NOTSET
formatter = generic

[formatter_generic]
format = %(levelname)-5.5s [%(name)s] %(message)s
```

- [ ] **Step 7: Crear `migrations/env.py`**

```python
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
```

- [ ] **Step 8: Crear `migrations/script.py.mako`**

Plantilla de las migraciones nuevas. Sin el `import sqlalchemy as sa` del template por defecto: acá se escribe SQL a mano y ruff marcaría el import sin usar.

```mako
"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
"""

from alembic import op

revision = ${repr(up_revision)}
down_revision = ${repr(down_revision)}
branch_labels = ${repr(branch_labels)}
depends_on = ${repr(depends_on)}


def upgrade() -> None:
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    ${downgrades if downgrades else "pass"}
```

- [ ] **Step 9: Verificar que el CLI arranca**

Run: `uv run alembic heads`
Esperado: no imprime ninguna revisión (todavía no hay ninguna) y sale con código 0. Si falla con `ModuleNotFoundError: config`, revisar `prepend_sys_path = .` en `alembic.ini`.

- [ ] **Step 10: Verificar lint, tipos y suite**

Run:
```bash
uv run ruff check . && uv run mypy app config.py && uv run pytest -m "not integration"
```
Esperado: verde. Si ruff se queja de `migrations/env.py` por las llamadas a nivel de módulo, **no** silenciarlo con `# noqa` sin entender el motivo — reportarlo.

- [ ] **Step 11: Commit**

```bash
git add -A
git commit -m "build: agrega Alembic y el andamiaje de migraciones

Sin migraciones todavia y sin tocar el arranque de la app: solo la
dependencia, alembic.ini para el CLI, env.py y la plantilla.

La URL sale de settings.sqlalchemy_url, que reescribe el esquema a
postgresql+psycopg porque SQLAlchemy resuelve postgresql:// a psycopg2."
```

---

### Task 3: La migración inicial

**Files:**
- Create: `migrations/versions/0001_esquema_inicial.py`
- Test: `tests/test_migracion_inicial.py`
- Delete: `tests/test_storage_reading_texts.py`, `tests/test_storage_reading_starts.py`
- Modify: `tests/limits/test_repository.py`, `tests/feedback/test_schemas.py`

**Interfaces:**
- Consumes: el andamiaje del Task 2.
- Produces: la revisión `0001`, sin `down_revision`. Crea `usage_events`, `conversation_starts`, `pilot_feedback`, `reading_texts` (+ `reading_texts_level_idx`) y `reading_starts` (+ `reading_starts_user_idx`). Los tests posteriores la leen desde `migrations/versions/0001_esquema_inicial.py`.

- [ ] **Step 1: Escribir el test del contenido de la migración**

Crear `tests/test_migracion_inicial.py`. Reemplaza a los dos archivos que comparaban `_SCHEMA` contra los `.sql`; lo que sobrevive es la verificación de intención de diseño, ahora contra la única fuente.

```python
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
    ddl = sql[inicio : sql.index(")", inicio)].lower()
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
```

- [ ] **Step 2: Correr el test para verlo fallar**

Run: `uv run pytest tests/test_migracion_inicial.py -v`
Esperado: FAIL con `FileNotFoundError` en el fixture — la migración todavía no existe.

- [ ] **Step 3: Escribir la migración**

Crear `migrations/versions/0001_esquema_inicial.py`. El SQL es el de `docker/initdb/02-` a `05-` y `app/storage.py`, con sus comentarios. El nombre del archivo es fijo (no lo genera `alembic revision`) porque los tests lo leen por ruta.

```python
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
```

Nota sobre `line-length`: las líneas de comentario `-- 'synthesis' | 'question' | ...` pasan de 100 columnas. Si ruff se queja, agregar `migrations/versions/*.py` a `per-file-ignores` con `["E501"]` en `pyproject.toml`, con el mismo razonamiento que ya se usa para `app/conversation/graph.py`: recortar el SQL para que entre cambiaría el contenido.

- [ ] **Step 4: Correr el test para verlo pasar**

Run: `uv run pytest tests/test_migracion_inicial.py -v`
Esperado: todos en PASS.

- [ ] **Step 5: Borrar los tests que comparaban las dos fuentes**

```bash
git rm tests/test_storage_reading_texts.py tests/test_storage_reading_starts.py
```

Todo lo que verificaban y sigue teniendo valor está en `tests/test_migracion_inicial.py`. Lo que se pierde a propósito: `test_schema_has_index_as_separate_statement`, que exigía que el índice fuera un elemento aparte de la tupla porque psycopg ejecuta una sentencia por `execute()`. Con Alembic esa restricción no existe.

- [ ] **Step 6: Reapuntar las dos aserciones sueltas contra `_SCHEMA`**

En `tests/limits/test_repository.py`, reemplazar `test_storage_schema_includes_new_tables` por nada: sus dos tablas (`usage_events`, `conversation_starts`) ya están cubiertas por el `test_crea_todas_las_tablas` parametrizado del archivo nuevo. Borrar la función entera.

Lo mismo en `tests/feedback/test_schemas.py` con `test_schema_includes_pilot_feedback_table`: borrar la función entera.

- [ ] **Step 7: Escribir el test de integración**

Agregar al final de `tests/test_migracion_inicial.py`:

```python
@pytest.mark.integration
def test_upgrade_head_crea_las_tablas():
    """Corre la migracion de verdad contra el Postgres de settings.DATABASE_URL.

    Es lo unico que prueba que el SQL es valido: los tests de arriba leen texto. Queda
    fuera del stage `test` del Dockerfile, que no levanta servicios.
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
```

Este test depende de `app.schema.apply_migrations`, que se crea en el Task 4. Va a fallar al importar hasta entonces — por eso está marcado `integration` y no corre en la suite normal.

- [ ] **Step 8: Verificar la suite y el lint**

Run:
```bash
uv run ruff check . && uv run mypy app config.py && uv run pytest -m "not integration"
```
Esperado: verde. El test de integración no corre.

- [ ] **Step 9: Verificar la cobertura**

Run: `uv run coverage run -m pytest -m "not integration" && uv run coverage report`
Esperado: por encima de 68 %. `migrations/` no se mide (`source = ["app", "config"]`), así que el número no debería moverse mucho respecto del Task 1.

- [ ] **Step 10: Commit**

```bash
git add -A
git commit -m "feat: migracion inicial de Alembic con el esquema actual

Idempotente (IF NOT EXISTS) para que la base de Railway, que ya tiene las
tablas, la acepte sin un stamp manual.

Los tests que comparaban _SCHEMA contra los .sql se reemplazan por uno solo
que verifica intencion de diseño contra la migracion."
```

---

### Task 4: `app/schema.py` y el `lifespan`

Acá se corta el camino viejo: el arranque pasa a migrar y `_SCHEMA` desaparece.

**Files:**
- Create: `app/schema.py`
- Test: `tests/test_schema.py`, `tests/cmd/test_lifespan.py`
- Modify: `app/storage.py`, `app/cmd/server.py:130-160`, `app/feedback/repository.py`, `pyproject.toml`

**Interfaces:**
- Consumes: `settings.sqlalchemy_url` (Task 2), la revisión `0001` (Task 3).
- Produces: `app.schema.apply_migrations() -> None`. Sincrónica y bloqueante; el `lifespan` la llama con `asyncio.to_thread`. Propaga cualquier excepción de Alembic.
- Deja de existir: `app.storage._SCHEMA`, `PostgresStorage.init_schema()`, `AsyncPostgresStorage.init_schema()`.

- [ ] **Step 1: Escribir el test de `app/schema.py`**

Crear `tests/test_schema.py`:

```python
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
    config, revision = llamadas[0]
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
```

- [ ] **Step 2: Correr el test para verlo fallar**

Run: `uv run pytest tests/test_schema.py -v`
Esperado: FAIL con `ImportError: cannot import name 'schema' from 'app'`.

- [ ] **Step 3: Escribir `app/schema.py`**

```python
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
```

- [ ] **Step 4: Correr el test para verlo pasar**

Run: `uv run pytest tests/test_schema.py -v`
Esperado: los 3 en PASS.

- [ ] **Step 5: Agregar `app.schema` a los módulos estrictos de mypy**

En `pyproject.toml`, dentro del `[[tool.mypy.overrides]]` de estrictos, agregar en orden alfabético junto a los otros de `app`:

```toml
    "app.schema",
```

Run: `uv run mypy app config.py`
Esperado: verde. Si se queja de que `alembic` no tiene stubs, agregar un bloque de override como el que ya existe para `azure.*`:

```toml
[[tool.mypy.overrides]]
module = ["alembic.*"]
ignore_missing_imports = true
```

- [ ] **Step 6: Escribir el test del `lifespan`**

Crear `tests/cmd/test_lifespan.py`. Archivo aparte y no dentro de `test_web.py`: los tests de ahí usan `TestClient(...)` **sin** `with`, o sea que nunca disparan el `lifespan`. Estos son los primeros que lo ejercitan.

Ojo con el parche de `ingest_loop`: sin él, el `lifespan` levanta la tarea de ingesta de verdad. Si hay un Postgres corriendo en la URL por defecto y el catálogo está vacío, el test saldría a scrapear Engoo. Un test no puede hacer eso.

```python
"""Tests del lifespan: que el arranque aplique las migraciones y que se caiga si fallan.

Los otros tests del servidor usan TestClient sin `with`, asi que no disparan el lifespan.
Estos si, y por eso hay que neutralizar la tarea de ingesta: sin el parche, un Postgres
corriendo con el catalogo vacio haria que el test salga a scrapear la fuente real.
"""

import asyncio

import pytest
from fastapi.testclient import TestClient

from app.cmd import server


@pytest.fixture(autouse=True)
def _sin_ingesta(monkeypatch):
    async def no_hace_nada(source, store):
        await asyncio.sleep(3600)

    monkeypatch.setattr(server, "ingest_loop", no_hace_nada)


def test_el_arranque_migra(monkeypatch):
    """El lifespan aplica las migraciones antes de atender la primera request."""
    llamadas = []
    monkeypatch.setattr(server, "apply_migrations", lambda: llamadas.append(True))

    with TestClient(server.app):
        pass

    assert llamadas == [True]


def test_una_migracion_fallida_tira_el_arranque(monkeypatch):
    """Cambio deliberado respecto del init_schema() anterior, que logueaba y seguia: eso
    dejaba la app arriba respondiendo 500 en todo lo que tocaba Postgres."""

    def explota():
        raise RuntimeError("migracion rota")

    monkeypatch.setattr(server, "apply_migrations", explota)

    with pytest.raises(RuntimeError, match="migracion rota"):
        with TestClient(server.app):
            pass
```

- [ ] **Step 7: Correr el test para verlo fallar**

Run: `uv run pytest tests/cmd/test_lifespan.py -v`
Esperado: FAIL — `server` no tiene atributo `apply_migrations`.

- [ ] **Step 8: Cablear el `lifespan`**

En `app/cmd/server.py`, agregar el import junto a los otros de `app`:

```python
from app.schema import apply_migrations
```

Y reemplazar el bloque del `lifespan` que hoy llama a `init_schema()`:

```python
    try:
        _storage.init_schema()
    except Exception:
        logger.exception("No se pudo inicializar el esquema de Postgres; ¿está la BD arriba?")
```

por:

```python
    # Sin try/except a proposito: si la migracion falla, el arranque se cae. Un servidor
    # arriba con el esquema desactualizado responde 500 en todo lo que toque Postgres, y
    # en un deploy es preferible que quede rojo y siga corriendo la version anterior.
    # `to_thread` porque Alembic es sincronico y esto corre dentro del event loop.
    await asyncio.to_thread(apply_migrations)
```

Actualizar además el docstring del `lifespan`, que empieza con "Al arrancar intenta crear la tabla si falta (uso standalone); si Postgres está caído, lo registra y sigue: en docker-compose la tabla ya viene del init.sql.":

```python
    """Al arrancar aplica las migraciones pendientes. Si fallan, el arranque se cae: es el
    mismo camino en Compose, en Railway y corriendo uvicorn sin Docker.

    Ademas levanta la ingesta de textos de lectura como tarea de fondo. Va aca y no en un
    proceso aparte porque no necesita uno: es un `sleep` largo entre corridas. Se cancela al
    apagar, y el `await` posterior espera a que termine de verdad."""
```

- [ ] **Step 9: Correr el test para verlo pasar**

Run: `uv run pytest tests/cmd/test_lifespan.py -v`
Esperado: los 2 en PASS.

- [ ] **Step 10: Borrar `_SCHEMA` y los dos `init_schema()`**

En `app/storage.py`:

1. Borrar la tupla `_SCHEMA` entera y su comentario.
2. Borrar el método `PostgresStorage.init_schema`.
3. Borrar el método `AsyncPostgresStorage.init_schema`.
4. Borrar de los imports lo que quede sin usar: `LiteralString` de `typing` (seguía usándose solo en `_SCHEMA`). `cast` sigue haciendo falta en `connect`.
5. Actualizar el docstring del módulo, que dice "Se instancia una vez (en `main`, con `settings.DATABASE_URL`) y se inyecta a cada repositorio." — sigue siendo cierto; agregarle una línea:

```python
"""Adaptador de almacenamiento Postgres.

Envuelve la creación de conexiones para que los repositorios reciban esto por
inyección de dependencia y no sepan dónde ni cómo se abre la base. Se instancia
una vez (en `main`, con `settings.DATABASE_URL`) y se inyecta a cada repositorio.

No define ni crea el esquema: de eso se encarga Alembic (ver `app/schema.py`).
"""
```

6. En `app/feedback/repository.py`, el docstring dice "NO crea la tabla (eso lo hace `PostgresStorage.init_schema()` o el init del contenedor)". Cambiar a "NO crea la tabla (de eso se encarga Alembic)".

- [ ] **Step 11: Verificar todo**

Run:
```bash
uv run ruff check . && uv run mypy app config.py && uv run pytest -m "not integration"
```
Esperado: verde.

- [ ] **Step 12: Verificar la cobertura**

Run: `uv run coverage run -m pytest -m "not integration" && uv run coverage report`
Esperado: por encima de 68 %. Se borraron los dos `init_schema()` (que no tenían tests) y se agregó `app/schema.py` (que sí), así que debería subir.

- [ ] **Step 13: Probar el camino real contra Postgres**

Run:
```bash
docker compose up -d db
uv run pytest -m integration -v
```
Esperado: `test_upgrade_head_crea_las_tablas` en PASS. Después:

```bash
uv run alembic current
```
Esperado: imprime `0001 (head)`.

Nota: `docker-compose.yml` todavía monta `docker/initdb/`, así que la base ya viene con las tablas creadas. **Eso es justamente el caso que la migración idempotente tiene que soportar** — el mismo que la base de Railway. Si este paso pasa, está probado.

Limpiar después con `docker compose down`.

- [ ] **Step 14: Commit**

```bash
git add -A
git commit -m "feat: el arranque aplica las migraciones y se cae si fallan

app/schema.py encapsula Alembic y el lifespan lo llama con to_thread, sin
try/except: un esquema desactualizado da 500 en todo lo que toca Postgres,
asi que es mejor que el deploy quede rojo.

Se van _SCHEMA y los dos init_schema(): el DDL ya no vive en Python."
```

---

### Task 5: Borrar `docker/initdb/`, ajustar la imagen y la documentación

Último camino viejo que queda en pie.

**Files:**
- Delete: `docker/initdb/` (los cuatro `.sql` restantes)
- Modify: `docker-compose.yml`, `Dockerfile`, `docs/DEPLOY.md`, `README.md`, `CLAUDE.md`, `docs/APRENDIZAJE.md`

**Interfaces:**
- Consumes: todo lo anterior. La app ya migra sola al arrancar.
- Produces: nada de código.

- [ ] **Step 1: Borrar los `.sql` y su mount**

```bash
git rm -r docker/initdb
```

En `docker-compose.yml`, borrar del servicio `db` la línea del mount y su comentario:

```yaml
      # El .sql crea la tabla al inicializar el volumen por primera vez.
      - ./docker/initdb:/docker-entrypoint-initdb.d:ro
```

El volumen `pgdata` se queda.

- [ ] **Step 2: Ajustar el Dockerfile**

Tres ediciones:

1. En el stage `base`, después de `COPY config.py ./config.py`, agregar:

```dockerfile
# Las migraciones van a produccion: el lifespan corre `upgrade head` al arrancar.
COPY migrations ./migrations
COPY alembic.ini ./alembic.ini
```

2. En el stage `test`, borrar estas dos líneas (el directorio ya no existe):

```dockerfile
# Un par de tests comparan el schema del código contra los .sql que inicializan Postgres.
COPY docker/initdb ./docker/initdb
```

3. En el stage `production`, después de `COPY --from=base /app/config.py ./config.py`, agregar:

```dockerfile
COPY --from=base /app/migrations ./migrations
COPY --from=base /app/alembic.ini ./alembic.ini
```

- [ ] **Step 3: Verificar que la imagen de test se construye**

Run: `docker build --target test .`
Esperado: los tests corren dentro del contenedor y el build termina en verde. Es la misma verificación que hace el CI.

- [ ] **Step 4: Verificar que la imagen de producción se construye y arranca**

Run:
```bash
docker build --target production -t review-ingles:prod .
docker compose up -d db
docker run --rm --network host \
  -e DATABASE_URL=postgresql://review:review@localhost:5434/interview_ingles \
  review-ingles:prod
```
Esperado: en el log aparecen las líneas de Alembic (`Running upgrade -> 0001` la primera vez, o ninguna si ya está aplicada) y después el `Uvicorn running on...`. Cortar con Ctrl-C y limpiar con `docker compose down`.

Nota: `--network host` solo funciona en Linux. En macOS, usar `-e DATABASE_URL=postgresql://review:review@host.docker.internal:5434/interview_ingles` sin `--network host` y agregando `-p 8000:8000`.

- [ ] **Step 5: Probar el ciclo completo desde cero**

Es la verificación de que ya no hace falta el init de Postgres:

```bash
docker compose down -v      # borra el volumen: base vacia de verdad
docker compose up --build
```
Esperado: la app arranca, crea el esquema con Alembic y `http://127.0.0.1:8000` responde. Antes esto lo hacía el mount de `docker-entrypoint-initdb.d`, que ya no está.

- [ ] **Step 6: Actualizar `docs/DEPLOY.md`**

1. En la tabla de stages, la fila de `test` dice "`development` + `tests/` + `docker/initdb/`". Cambiar a "`development` + `tests/`".
2. En la sección "Desplegar", borrar el paso 1 entero (aprovisionar Postgres y correr los `.sql` con `psql`) y reemplazarlo por:

```markdown
1. **Aprovisiona un Postgres** y pasa su cadena de conexion en `DATABASE_URL`. No hay que
   crear el esquema a mano: la app corre las migraciones de Alembic al arrancar, tanto en
   una base vacia como en una que ya tiene datos.

   Si la migracion falla, el contenedor no arranca y el deploy queda rojo — a proposito,
   para que el proveedor siga sirviendo la version anterior en vez de una app con el
   esquema desactualizado.
```

3. Renumerar los pasos 2 y 3 si hiciera falta (siguen siendo 2 y 3).

- [ ] **Step 7: Actualizar `README.md`**

1. En la tabla de "Estructura", la fila `docker/initdb/` ("Scripts SQL que crean el esquema") pasa a:

```markdown
| `migrations/` | Migraciones de Alembic: la unica fuente del esquema |
```

2. Agregar una subsección corta después de "Con uv (entorno virtual local)":

```markdown
### El esquema de la base

Lo aplica la app al arrancar, con Alembic. No hay que correr nada a mano ni en local ni al
desplegar, y funciona igual sobre una base vacia que sobre una que ya tiene datos.

Para cambiarlo, se crea una migracion nueva:

```bash
uv run alembic revision -m "agrega la columna X"   # crea el archivo en migrations/versions/
uv run alembic current                             # que version tiene la base
```

Se escriben a mano con `op.execute("ALTER TABLE ...")`. **No** se usa `--autogenerate`: el
proyecto no tiene modelos de SQLAlchemy de donde derivar el esquema.
```

- [ ] **Step 8: Actualizar `CLAUDE.md`**

1. En la tabla de módulos, la fila de `app/storage.py` dice "el DDL de `_SCHEMA` duplica `docker/initdb/*.sql` y hay tests que los comparan". Reemplazar por:

```markdown
| `app/storage.py` | `PostgresStorage` (sync) y `AsyncPostgresStorage` conviven. No define el esquema: eso es de Alembic, ver `app/schema.py` y `migrations/` |
```

2. En "Comandos", agregar después del bloque de lint:

```bash
uv run alembic revision -m "descripcion"      # nueva migracion (se escribe a mano)
uv run alembic current                        # version del esquema en la base
```

3. En "Reglas del repo", agregar:

```markdown
- **El esquema vive solo en `migrations/`.** La app corre `upgrade head` al arrancar
  (`app/schema.py`, llamado desde el `lifespan`), y si falla el arranque se cae a propósito.
  Las migraciones se escriben a mano con `op.execute()`; nunca `--autogenerate`, porque no
  hay modelos de SQLAlchemy.
```

- [ ] **Step 9: Actualizar `docs/APRENDIZAJE.md`**

En el punto 2 del roadmap ("Checkpointer persistente"), el bloque "**Ojo (confusión común)**" dice que el SQLite actual es solo para las configs, no para el estado del grafo. Esa tabla ya no existe. Reemplazar ese bullet por:

```markdown
- **Ojo (confusión común)**: el Postgres del proyecto guarda uso, cuotas, feedback y el
  catalogo de lectura, NO el estado del grafo. Son dos persistencias distintas, y el
  checkpointer necesita la suya.
```

Y en el "Contexto del proyecto", la línea `- app/conversation/repository.py + model.py — CRUD de conversation_configs.` se borra; agregar en su lugar:

```markdown
- `migrations/` — el esquema de Postgres, en migraciones de Alembic escritas a mano.
```

- [ ] **Step 10: Verificar que no quedaron referencias colgadas**

Run:
```bash
grep -rn "initdb\|init_schema\|_SCHEMA\|conversation_configs" . \
  --include="*.py" --include="*.md" --include="*.yml" --include="*.toml" \
  --exclude-dir=.venv --exclude-dir=.git --exclude-dir=docs/superpowers
```
Esperado: cero hits, salvo dentro de `docs/superpowers/` (el spec y este plan describen el cambio, y los planes viejos son registro histórico que no se reescribe).

- [ ] **Step 11: Verificación final completa**

Run:
```bash
uv run ruff check . && uv run mypy app config.py
uv run coverage run -m pytest -m "not integration" && uv run coverage report
docker build --target test .
```
Esperado: todo verde y la cobertura por encima de 68 %.

- [ ] **Step 12: Commit**

```bash
git add -A
git commit -m "chore: elimina docker/initdb y documenta el esquema con Alembic

Ultimo camino viejo que quedaba: el mount de docker-entrypoint-initdb.d
solo corria bajo Compose y solo al crear el volumen, y el paso manual de
psql del DEPLOY era redundante con el lifespan.

migrations/ y alembic.ini pasan a la imagen de produccion."
```

---

## Verificación del plan completo

Al terminar los cinco tasks, el estado esperado:

- `grep -rn "_SCHEMA\|init_schema\|initdb" app tests` → cero hits.
- `uv run alembic current` contra una base migrada → `0001 (head)`.
- `docker compose down -v && docker compose up --build` → la app arranca sobre una base vacía.
- `docker build --target test .` → verde.
- Cobertura por encima de 68 %.
