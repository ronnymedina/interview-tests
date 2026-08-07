# Esquema con fuente única: Alembic + limpieza de código muerto

Fecha: 2026-08-07

## El problema

El DDL está escrito dos veces y se aplica por tres caminos distintos:

1. `_SCHEMA` en `app/storage.py` — una tupla de strings que aplican `PostgresStorage.init_schema()`
   y `AsyncPostgresStorage.init_schema()`. El servidor la llama en el `lifespan`, así que corre
   en cada arranque.
2. `docker/initdb/*.sql` — cinco archivos que Postgres ejecuta **una sola vez**, al crear el
   volumen, y solo bajo Compose.
3. El paso manual de `psql` documentado en `docs/DEPLOY.md`, para un Postgres gestionado.

Como las dos primeras pueden divergir, `tests/test_storage_reading_texts.py` y
`tests/test_storage_reading_starts.py` existen sobre todo para detectar esa divergencia. A eso
se suman aserciones sueltas contra `_SCHEMA` en `tests/limits/test_repository.py` y
`tests/feedback/test_schemas.py`, que no comparan las dos fuentes pero sí dependen de que
`_SCHEMA` exista.

En Railway no hay Compose: `docker/initdb/` ni siquiera se copia a la imagen de producción, así
que allí el esquema lo crea únicamente el `lifespan`. El camino 2 y el 3 son, en la práctica,
redundantes con el 1 — pero se siguen manteniendo.

Además, ninguno de los tres sabe modificar una tabla que ya tiene datos. `CREATE TABLE IF NOT
EXISTS` no agrega una columna a una tabla existente. Hoy eso obliga a entrar a la base de
Railway y correr el `ALTER` a mano, acordándose de reflejarlo en los dos DDL.

## Qué se busca

Una sola fuente del esquema, aplicada por un solo camino, que funcione igual en Compose, en
Railway y corriendo `uv run uvicorn` sin Docker, y que sepa evolucionar una base ya poblada.

## Decisión: Alembic sin ORM

Migraciones versionadas de Alembic, escritas a mano con `op.execute()` sobre el mismo SQL que
ya existe. Sin modelos de SQLAlchemy y sin autogeneración.

Se descartaron:

- **Unificar en `_SCHEMA` (Python) o en los `.sql`, sin migraciones.** Resuelven la duplicación
  pero no el `ALTER` sobre datos existentes, que es la mitad del problema.
- **Un ORM (SQLAlchemy).** No resuelve las migraciones — `create_all()` tiene exactamente la
  misma limitación que `_SCHEMA` — y obligaría a reescribir los cuatro repositorios, que hoy
  usan psycopg con SQL a mano y conviven en variante sync y async.

### Consecuencias asumidas

- **Alembic va en `[project] dependencies`, no en el grupo `dev`.** La imagen de producción hace
  `uv sync --no-dev` y el proceso web tiene que poder importarlo. Arrastra SQLAlchemy como
  dependencia dura, aunque no se use como ORM.
- **`alembic.ini` y `migrations/` hay que copiarlos a la imagen.** Hoy el stage `base` del
  Dockerfile solo copia `app/` y `config.py`, y `production` copia desde `base`.
- **Alembic es sincrónico y el `lifespan` es `async`.** El upgrade va envuelto en
  `asyncio.to_thread`, por la regla del proyecto de no bloquear el event loop.
- **SQLAlchemy resuelve `postgresql://` a psycopg2**, que no está instalado. `env.py` tiene que
  reescribir el esquema de la URL a `postgresql+psycopg://` antes de usarla.

## Componentes

| Archivo | Qué hace |
|---|---|
| `alembic.ini` | Config mínima. **Sin** `sqlalchemy.url`: la URL no puede vivir en un archivo versionado |
| `migrations/env.py` | Toma la URL de `settings.DATABASE_URL` y le reescribe el esquema a `postgresql+psycopg://`. `target_metadata = None` |
| `migrations/versions/0001_esquema_inicial.py` | El esquema actual, con los comentarios que hoy están en los `.sql` |
| `app/cmd/server.py` | El `lifespan` corre el upgrade en vez de `init_schema()` |
| `app/storage.py` | Pierde `_SCHEMA` y los dos `init_schema()`; queda solo como fábrica de conexiones |

Se eliminan: `docker/initdb/` completo, su mount en `docker-compose.yml`, el `COPY docker/initdb`
del stage `test` del Dockerfile y el paso 1 de `docs/DEPLOY.md`.

## La migración inicial

Crea seis objetos: `usage_events`, `conversation_starts`, `pilot_feedback`, `reading_texts` (más
`reading_texts_level_idx`) y `reading_starts` (más `reading_starts_user_idx`).

**No incluye `conversation_configs`** — ver la sección de limpieza.

Se escribe con `CREATE TABLE IF NOT EXISTS` / `CREATE INDEX IF NOT EXISTS`, o sea el SQL de hoy
tal cual. Es a propósito: la base de Railway **ya tiene esas tablas**, y una migración
idempotente se aplica ahí sin romper nada y escribe la fila en `alembic_version`. Así no hace
falta un `alembic stamp head` manual contra producción.

De la migración `0002` en adelante se escriben normales, sin `IF NOT EXISTS`, porque Alembic ya
sabe desde dónde arranca.

El `downgrade()` de `0001` queda vacío con un comentario: revertir el esquema inicial es
`DROP TABLE` de todo, y no hay ningún escenario en que se quiera.

## Limpieza: `conversation_configs` y compañía

La tabla no la usa nadie. Cero referencias en `app/web/` (el frontend nunca llama a
`/conversation/configs`) y cero tests en `tests/cmd/`.

Se elimina:

- `app/conversation/repository.py` — el archivo entero.
- `app/conversation/model.py` — el archivo entero.
- `ConfigRequest` y `AnswerRequest` de `app/conversation/schemas.py`. `AnswerRequest` también
  está muerto: `/conversation/answer` recibe `Form(...)` y valida inline.
- Los cinco endpoints CRUD de `app/cmd/server.py`, más `get_repository` y `_repository`.
- Los exports correspondientes de `app/conversation/__init__.py`.

**La tabla en Railway la borra el autor a mano.** No se agrega una migración de `DROP`.

Efecto sobre la cobertura: ese código no tiene tests, así que borrarlo la sube. Sin riesgo de
romper el piso de 68 %.

## Manejo de errores

Una migración fallida propaga la excepción desde el `lifespan` y uvicorn no arranca. En Railway
el deploy queda rojo y sigue corriendo la versión anterior.

Es un cambio deliberado respecto de hoy, donde el `lifespan` captura la excepción de
`init_schema()`, la loguea y arranca igual — dejando la app arriba y respondiendo 500 en todo lo
que toque Postgres.

**Fuera de alcance:** la carrera entre réplicas. Con más de una réplica, todas correrían el
upgrade al arrancar y Alembic no toma un lock por defecto. Con una sola réplica no aplica. Se
resuelve con un advisory lock de Postgres en `env.py` cuando haga falta.

## Tests

Al desaparecer `_SCHEMA` y los `.sql`, cuatro archivos de test dejan de compilar. No todo lo que
verifican es redundante.

- **Se borra** lo que compara las dos fuentes: `test_initdb_sql_matches_schema` y
  `test_el_sql_del_contenedor_coincide_con_el_schema`.
- **Se borra** `test_schema_has_index_as_separate_statement`: verificaba que el índice fuera un
  elemento aparte de la tupla porque psycopg ejecuta una sentencia por `execute()`. Con Alembic
  esa restricción deja de existir.
- **Se reapunta a la migración inicial** lo que verifica intención de diseño: `source_url` es
  UNIQUE, `level` admite NULL, `reading_starts` no guarda contenido, los dos índices existen, y
  las aserciones de `tests/limits/test_repository.py` y `tests/feedback/test_schemas.py` sobre
  `usage_events`, `conversation_starts` y `pilot_feedback`.
- **Se agrega** un test marcado `@pytest.mark.integration` que corre `upgrade head` contra un
  Postgres real y comprueba que las tablas quedaron creadas. Queda fuera del stage `test` del
  Dockerfile, que no levanta servicios.

La cobertura no cambia de forma: `source = ["app", "config"]` en `pyproject.toml`, así que
`migrations/` no se mide.

## Documentación a actualizar

- `docs/DEPLOY.md` — se cae el paso de correr los `.sql` con `psql`; se explica que el esquema se
  aplica solo al arrancar.
- `README.md` — la sección de estructura menciona `docker/initdb/`.
- `CLAUDE.md` — la nota sobre el DDL duplicado y los tests que lo comparan.
- `docs/APRENDIZAJE.md` — el punto 2 del roadmap (checkpointer persistente) advierte sobre no
  confundir la persistencia de las configs con la del grafo; esa aclaración cambia de sentido al
  desaparecer `conversation_configs`.
