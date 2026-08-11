# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Idioma

**El código va en inglés**: comentarios, docstrings, identificadores, nombres de test y los
prompts al LLM. **Los mensajes de commit y las descripciones de los pull requests también
van en inglés**, siguiendo conventional commits con scope:
`feat(reading): filter the catalog by maximum level`.

**`docs/` va en inglés**, con nombres de archivo en minúscula y kebab-case
(`environments.md`, `pending-changes.md`). **En español quedan solo este archivo y
`README.md`**, que son la puerta de entrada al repo.

Excepción: `docs/superpowers/specs/` y `docs/superpowers/plans/` son documentos históricos
fechados. Se dejan como están —incluido el español— porque registran lo que se decidió en su
momento; no se traducen ni se actualizan cuando el código cambia después.

Estas convenciones cambiaron sobre la marcha: buena parte del código todavía tiene
comentarios y docstrings en español. La migración es orgánica — cuando toques un archivo por
otro motivo, pasá a inglés lo que estés modificando. No hace falta traducir un archivo entero
solo por pasar por ahí.

## Comandos

```bash
uv sync                                       # entorno virtual + deps del lock
uv run uvicorn app.cmd.server:app --reload    # servidor local (necesita Postgres propio)
docker compose up --build                     # Postgres + app con hot reload

uv run pytest                                 # suite completa
uv run pytest tests/reading/test_service.py::test_nombre   # un solo test
uv run pytest -m "not integration"            # lo que corre el CI (sin infra real)
uv run coverage run -m pytest && uv run coverage report    # con piso de cobertura
docker build --target test .                  # exactamente lo que corre el CI

uv run ruff check .                           # lint (bloquea el CI)
uv run ruff check . --fix
uv run mypy app config.py                     # tipos (bloquea el CI)

uv run alembic revision -m "descripcion"      # nueva migracion numerada (necesita Postgres arriba)
uv run alembic current                        # version del esquema en la base

uv run python -m app.reading.ingest           # fuerza la ingesta del catálogo de lectura
```

El CI corre lint, mypy y el stage `test` del Dockerfile en paralelo; los tres bloquean, y
la imagen de producción solo se construye si los tres pasan. `docker build --target test .`
reproduce el job de tests localmente con el mismo Python y el mismo `uv.lock`.

## Reglas del repo

- **`config.py` es el único lugar que lee variables de entorno.** Todo lo demás hace
  `from config import settings` y recibe valores ya tipados por pydantic-settings. Un
  `os.getenv` fuera de ahí es un bug de arquitectura. Los tests parchean con
  `monkeypatch.setattr(settings, "CAMPO", ...)`.
- **`app/reading/*` y todo lo que corra dentro del event loop usa I/O asíncrono.** psycopg
  async (`AsyncPostgresStorage`), `httpx.AsyncClient`, y lo bloqueante (el SDK de Azure, los
  repositorios sincrónicos de `limits`) se aparta con `asyncio.to_thread`. Ver los endpoints
  `async def` de `server.py`.
- **El piso de cobertura (`fail_under = 68` en `pyproject.toml`) es apretado a propósito.**
  Un cambio grande normalmente tiene que traer sus tests en el mismo commit.
- **mypy es gradual.** La base global es permisiva y los módulos que ya cumplen estricto
  están en la lista de `[[tool.mypy.overrides]]` de `pyproject.toml`. La lista solo crece.
  **No pongas `strict = true` en una sección per-module**: mypy lo aplica al proyecto entero
  en lugar de al módulo; por eso los flags están expandidos a mano.
- Los tests marcados `@pytest.mark.integration` necesitan Postgres/Azure/red y quedan fuera
  del stage `test`.
- `behave` y `mutmut` están en dev deps sin usar todavía, a propósito: se van a adoptar.
- **El esquema vive solo en `migrations/`.** La app corre `upgrade head` al arrancar
  (`app/schema.py`, llamado desde el `lifespan`), y si falla el arranque se cae a propósito.
  Las migraciones se escriben a mano con `op.execute()`; nunca `--autogenerate`, porque no
  hay modelos de SQLAlchemy.

## Arquitectura

FastAPI + Postgres, LangGraph con Gemini para el tutor, Azure Speech para la evaluación de
pronunciación, y HTML server-side con Jinja2 (sin framework de frontend, requiere Chrome por
la Web Speech API).

**`app/cmd/server.py` es el composition root y el único entrypoint.** Al importarse construye
una vez cada servicio y los inyecta a los endpoints con `Depends`. La construcción **degrada
en vez de fallar**: sin `GEMINI_API_KEY` el servicio de conversación queda en `None` y sus
endpoints responden 503; sin `AZURE_SPEECH_KEY` se omite el scoring y la conversación sigue
funcionando. `LimitsService` siempre se construye. El servidor arranca igual en todos los
casos.

Cada módulo de dominio repite la misma forma: `__init__.py` expone la fachada y un
`build_*` que arma el adaptador real, `service.py` tiene la lógica y recibe interfaces por
constructor, `repository.py` la persistencia, `model.py`/`schemas.py` los tipos. Los tests
inyectan dobles en memoria (`tests/*/doubles.py`) en vez de tocar infraestructura.

| Módulo | Rol |
|---|---|
| `app/conversation/` | Grafo LangGraph (`graph.py`: la clase `ConversationGraph` con los nodos `ask`/`review` como métodos y `compile()`, checkpointer en memoria por `thread_id`), `synthesizer.py` que normaliza el contexto libre del alumno al brief fijo, `service.py`, `__init__.py` (composition root: `build_conversation_graph_service`, `build_chat_model` y `api_key_for`, único lugar del módulo que lee `settings`), `schemas.py` (validación de entrada), `messages.py` y `prompts/` (los prompts en archivos `v<N>_<nombre>.md`, cargados con `prompts.load`) |
| `app/reading/` | Catálogo de textos: `sources/` obtiene → `ingest` orquesta → `repository` persiste; `scheduler` repite cada N horas dentro del servidor; `excerpt.py` recorta |
| `app/speech/` | `azure_client.py` habla con el SDK; `assessment.py` tiene los dos modos (unscripted para la conversación, scripted contra referencia para la lectura); `scoring.py` la cola diferida |
| `app/limits/` | Presupuesto en dólares (diario y total) y cuota por usuario. Precedencia: total → diario → cuota |
| `app/web/` | Plantillas Jinja2 y JS plano. `shared.js` es transversal (identidad, cliente API, grabación WAV, TTS) y no referencia ids de una página concreta; lo propio de cada modalidad va en su archivo |
| `app/storage.py` | `PostgresStorage` (sync) y `AsyncPostgresStorage` conviven. No define el esquema: eso es de Alembic, ver `app/schema.py` y `migrations/` |

**Decisiones que no hay que re-litigar:**

- El texto de referencia de una lectura se **recalcula** desde la base con el `reading_id`;
  el cliente nunca lo manda. Si lo mandara, podría evaluar un audio de "hello" contra una
  referencia "hello" y sacar 100 siempre. `make_excerpt` es determinista, así que releer la
  fila devuelve exactamente lo que se mostró.
- **El proveedor del LLM sale del prefijo del modelo, y cada proveedor trae su propia key.**
  `PROVIDER_API_KEY_FIELDS` en `config.py` mapea `"google_genai"` → `GEMINI_API_KEY`; un
  `field_validator` rechaza al arrancar cualquier prefijo que no esté en el mapa. La
  *presencia* de la key no se valida ahí a propósito: se chequea en `api_key_for()` solo
  para los proveedores que los modelos configurados nombran, así correr el revisor en otro
  proveedor no exige una key que nadie usa. Agregar un proveedor = un campo nuevo en
  `Settings` más una entrada en el mapa; el código de construcción nunca nombra proveedores.
- El `session_brief` (el contexto del alumno ya sintetizado) entra como primer
  `HumanMessage` y las reglas fijas del tutor como `SystemMessage`, con precedencia
  explícita sobre el `session_brief`. Sin "kickoff" artificial.
- El feedback final es Markdown libre + `words`/`phrases` estructurados vía
  `with_structured_output`.
- En la conversación, el audio se encola para Azure **sin esperar** y el `transcript` del
  navegador mueve la conversación; el scoring se agrega recién en el turno final.
- Los límites se chequean **antes** de gastar y la cuota se registra **después** de que el
  proveedor responda: un fallo de Azure no debe gastarle una lectura al usuario. Si la
  consulta de límites falla, se corta conservador con 429 `paused`.
- La ingesta corre como tarea de fondo del servidor (`lifespan`), no en un proceso aparte, y
  la primera corrida solo ocurre si el catálogo está vacío.

**Identidad y errores.** No hay autenticación: la identidad es el header `X-User-Id` que
genera el navegador (UUID en localStorage), útil solo para separar cuotas. Los errores de
dominio son excepciones propias con `status` HTTP (`ConversationError`, `ReadingError`,
`SpeechError`) que el endpoint traduce; los 429 llevan un motivo tipado (`quota`, `paused`,
`rate_limited`) que el frontend usa para pintar el banner.

## Documentación

`docs/environments.md` (cada variable: si es requerida, valores aceptados y qué poner en
producción), `docs/deploy.md`, `docs/azure-pronunciation.md`, `docs/learning.md` (roadmap de
LangGraph aplicado al proyecto) y `docs/pending-changes.md`. Cada feature tiene su diseño y su
plan en `docs/superpowers/specs/` y `docs/superpowers/plans/`, nombrados por fecha.
