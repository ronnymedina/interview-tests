# Dockerfile multistage + migración a Postgres — `review-ingles/app/`

Fecha: 2026-07-31
Estado: aprobado para implementar

## Objetivo

Empaquetar el módulo migrado `app/` (no el código legacy de la raíz) con un
Dockerfile multistage (development / test / production) y levantar el stack de
desarrollo con `docker-compose.yml` usando **Postgres** en lugar de SQLite.

Todos los cambios quedan **en local**: sin `commit`, sin `push`. El `.env` no se
hornea en ninguna imagen; las variables se inyectan en runtime.

## Alcance

Incluye únicamente `app/` y su dependencia real `config.py` (el módulo único de
variables de entorno). El código de la raíz (`main.py`, `conversation.py`,
`db.py`, `scoring.py`, `speech.py`, etc.) es la primera versión (legacy) y queda
fuera de la imagen.

Hallazgo que baja el riesgo: `ConversationRepository` y el adaptador de
almacenamiento **no están cableados** en la app que corre. `build_service()`
arma LLM → grafo → sintetizador y el estado de conversación vive en el
`InMemorySaver` de langgraph. La tabla `conversation_configs` es andamiaje para
un paso futuro. Por eso migrar a Postgres se limita a cambiar el adaptador y su
SQL, sin tocar el flujo de conversación en runtime.

## Entregable 1 — Dockerfile multistage

Ubicación: `review-ingles/Dockerfile` + `review-ingles/.dockerignore`.
Entrypoint: `app.cmd.server:app`. Puerto 8000.

### Stage `base` (interno)
- `FROM python:3.13-slim`, binario de `uv` copiado desde `ghcr.io/astral-sh/uv`.
- `WORKDIR /app`, `ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy`.
- Copia `pyproject.toml` + `uv.lock`; `uv sync --frozen --no-install-project --no-dev`
  (capa de deps de prod, cacheada mientras no cambien esos archivos).
- Copia `app/` + `config.py`.

### Stage `development` (hot reload)
- `FROM base`; `uv sync --frozen` (agrega el grupo dev: `pytest`, `httpx`).
- `CMD ["uvicorn", "app.cmd.server:app", "--reload", "--host", "0.0.0.0", "--port", "8000"]`.
- El código se monta como volumen desde `docker-compose.yml` para que `--reload`
  reaccione a los cambios.

### Stage `test` (runnable, NO bloquea prod)
- `FROM development`; copia solo `test_app_conversation_service.py` (único test de
  `app/`). **No** copia el `conftest.py` de la raíz (importa módulos legacy
  `db`/`scoring`).
- `RUN coverage run -m pytest test_app_conversation_service.py && coverage report -m`
  (source = `app` + `config`). `coverage` está disponible (dep transitiva vía
  `mutmut`).
- Se ejecuta con `docker build --target test .`; falla ahí si rompen los tests,
  pero el build de prod es independiente.

### Stage `production` (mínima, non-root)
- `FROM python:3.13-slim`; crea usuario non-root `appuser`.
- Copia **solo** el `.venv` del stage `base` + `app/` + `config.py`. Sin `uv`, sin
  deps de dev, sin fuente extra.
- `ENV PATH="/app/.venv/bin:$PATH"`, `USER appuser`, `EXPOSE 8000`.
- `CMD ["uvicorn", "app.cmd.server:app", "--host", "0.0.0.0", "--port", "8000"]`
  (sin `--reload`).

## Entregable 2 — Migración SQLite → Postgres en `app/`

- **Driver:** `psycopg` (psycopg3), síncrono. Encaja con el repositorio actual,
  que es sync. Se agrega a `[project].dependencies` en `pyproject.toml` y se
  regenera `uv.lock`.
- **`app/storage.py`:** `SqliteStorage` → `PostgresStorage`. Misma interfaz: un
  `connect()` context manager que entrega una conexión, hace commit al salir,
  rollback ante excepción y cierra. Recibe `DATABASE_URL` por DI. Rows como dict
  (`psycopg.rows.dict_row`) para que `row["col"]` siga funcionando.
  Incluye `init_schema()` con el `CREATE TABLE IF NOT EXISTS conversation_configs`
  (para uso standalone).
- **`app/conversation/repository.py`:** ajuste de SQL SQLite → Postgres:
  - placeholders `?` → `%s`
  - `INSERT ...` + `cursor.lastrowid` → `INSERT ... RETURNING id`
  - tipo de `id`: `INTEGER PRIMARY KEY AUTOINCREMENT` → `GENERATED ALWAYS AS IDENTITY`
  - la firma de tipo `SqliteStorage` → `PostgresStorage`
- **`config.py`:** `DB_PATH` → `DATABASE_URL` (única variable de conexión; se
  mantiene la regla de un solo módulo de env). Se actualiza `.env.example`.
- **Sin tests de repositorio** por ahora (igual que el estado actual; el repo no
  tiene tests hoy).
- El repositorio queda **Postgres-ready pero sin cablear** a los endpoints, fiel
  al estado actual.

## Entregable 3 — `docker-compose.yml`

Ubicación: `review-ingles/docker-compose.yml` (sin prefijo `dev`).

- **`db`:** `postgres:17-alpine`, volumen persistente, `healthcheck` (`pg_isready`),
  variables `POSTGRES_*`. Script de init en `docker-entrypoint-initdb.d` con el
  `CREATE TABLE conversation_configs` para que Postgres arranque con la tabla.
- **`app`:** `build` con `target: development`, hot reload, código montado como
  volumen, `DATABASE_URL` apuntando al servicio `db`, `env_file: .env`,
  `depends_on: db` con condición de healthcheck, puerto `8000:8000`.

## Fase 2 — Cableado del repositorio + frontend simplificado (2026-08-01)

Decisiones del usuario: un solo campo de contexto (como el legacy); la síntesis
al brief ocurre POR DENTRO de `start` (no es un endpoint que llame el frontend) y
no se muestra; la conversación corre el loop completo con feedback SOLO al final;
transcripción de voz por navegador (Web Speech API). Persistencia: sin columnas
nuevas (`name` + `user_context`).

### Deps de testing separadas
- `mutmut`, `mypy`, `hypothesis`, `behave` (+ `pytest`, `httpx`) movidas a
  `[dependency-groups] dev`. La imagen de prod las excluye con `--no-dev`.

### Backend (`app/`)
- `schemas.py`: `StartRequest` pasa a `user_context` (contexto crudo). Nuevos
  `AnswerRequest` (conversation_id + text) y `ConfigRequest` (name + user_context).
  Se elimina `GenerateRequest`.
- `service.py`: `start(user_context, max_questions)` sintetiza por dentro antes de
  sembrar el grafo. Se elimina `generate_brief`.
- `cmd/server.py`: se cablean `PostgresStorage` + `ConversationRepository`. Endpoints:
  - `POST /conversation/start` (síntesis interna → 1ª pregunta)
  - `POST /conversation/answer` (loop; feedback final)
  - CRUD `POST/GET/GET{id}/PUT{id}/DELETE{id}` en `/conversation/configs`
  - Se elimina la ruta `POST /conversation/prompt/generate`.
  - `lifespan` intenta `init_schema()` al arrancar (degrada si la BD está caída).
  - Sirve el frontend estático (`app/web/`) montado en `/`.

### Frontend (`app/web/index.html`)
- Un solo HTML autocontenido (CSS + JS inline), servido por la app.
- Config de voces client-side (elegir voz + velocidad, probar).
- Un campo de contexto + nombre; guardar/editar/borrar/seleccionar configs
  guardadas (consume el CRUD).
- Iniciar conversación, loop de voz (Web Speech API para transcribir la respuesta)
  y feedback final (texto + palabras + frases).

### Verificado end-to-end
- CRUD de configs por HTTP contra Postgres en compose.
- `start` + dos `answer` → feedback final con palabras y frases.
- Stages `test` (2 tests) y `production` (incluye `app/web/`) construyen OK.

## Follow-ups anotados (siguen fuera de alcance)

- Aligerar prod: azure SDK y otras deps pesadas siguen en `dependencies`.
- Tests de integración del repositorio contra Postgres.
- Transcripción con Azure como opción (hoy solo navegador).
- Persistir score de pronunciación por turno (Azure) si se decide más adelante.
