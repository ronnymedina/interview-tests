# review-ingles

Practica de ingles hablado con evaluacion automatica de pronunciacion. Dos modalidades:

- **`/` — conversacion**: un tutor (LLM) te hace preguntas, vos respondes hablando y al
  final recibis un feedback escrito y el score de pronunciacion.
- **`/reading` — lectura en voz alta**: la app te da un texto real, lo lees, y Azure Speech
  (Pronunciation Assessment) evalua tu pronunciacion **contra ese texto**, palabra por
  palabra y fonema por fonema.

FastAPI + Postgres en el backend, LangGraph con Gemini para el tutor, Azure Speech para la
evaluacion, y HTML server-side con Jinja2 (sin framework de frontend).

## Requisitos

| | Version | Para que |
|---|---|---|
| **Docker** + Compose | 24+ / v2+ | Camino recomendado: levanta Postgres y la app juntos |
| **Python** | 3.11+ (probado en 3.13) | Solo si corres sin Docker |
| **[uv](https://docs.astral.sh/uv/)** | 0.5+ | Gestor de deps y del entorno virtual |
| **Postgres** | 17 (probado) | Lo levanta Compose; si corres local, necesitas uno propio |
| **Google Chrome** de escritorio | — | Las voces del tutor y el dictado dependen de la Web Speech API de Chrome. En otros navegadores la app no funciona. |

Ademas, dos credenciales externas:

- **Azure Speech** — evaluacion de pronunciacion. Gratis con el tier `F0` (5 h de audio al
  mes). En el [portal de Azure](https://portal.azure.com) → *Create a resource* → **Speech**
  → tier **Free F0**, eligiendo la region mas cercana para bajar la latencia. Despues, en el
  recurso → **Keys and Endpoint**, copia **KEY 1** y la **Region**.
- **Gemini** — el tutor. Key en <https://aistudio.google.com/apikey>.

Son secretos: viven solo en tu `.env`, que esta en `.gitignore`.

## Configuracion

```bash
cp .env.example .env
```

Todas las variables tienen un default razonable salvo las credenciales. El minimo para
arrancar es:

```bash
AZURE_SPEECH_KEY=...        # sin esto, la evaluacion de pronunciacion falla
AZURE_SPEECH_REGION=eastus
GEMINI_API_KEY=...          # sin esto, el tutor no responde
DATABASE_URL=postgresql://review:review@localhost:5432/review_ingles
```

Con Compose no hace falta `DATABASE_URL`: la define el propio `docker-compose.yml`
apuntando al servicio `db`.

Antes de exponer la app a otras personas, revisa tambien `DAILY_BUDGET_USD`,
`TOTAL_BUDGET_USD` y las cuotas por usuario: **son el unico freno de gasto**. El detalle de
cada variable esta en [docs/ENVS.md](docs/ENVS.md); todas se leen en un unico lugar,
[`config.py`](config.py).

## Correr la app

### Con Docker (recomendado)

Levanta Postgres + la app con hot reload, y aplica los scripts de `docker/initdb/` la
primera vez:

```bash
docker compose up --build
```

### Con uv (entorno virtual local)

Necesitas un Postgres corriendo por tu cuenta y `DATABASE_URL` apuntando a el.

```bash
uv sync                                      # crea .venv/ e instala las deps del lock
uv run uvicorn app.cmd.server:app --reload
```

`uv sync` crea el entorno virtual solo; no hace falta `python -m venv` ni activar nada, y
`uv run` ejecuta siempre dentro de el.

En ambos casos, abri <http://127.0.0.1:8000> **en Chrome**.

### Poblar el catalogo de lectura

El catalogo se puebla solo desde Engoo Daily News: el servidor corre la ingesta al arrancar
si la tabla esta vacia, y despues cada `READING_INGEST_INTERVAL_HOURS`. Si `/reading`
responde **503**, el catalogo esta vacio; podes forzarla:

```bash
uv run python -m app.reading.ingest
```

## Tests

Los tests viven en `tests/`, con la misma estructura que `app/`: un subpaquete por modulo
(`tests/reading/`, `tests/speech/`, `tests/limits/`…), mas `tests/cmd/` para los endpoints.
Los dobles compartidos por varios tests de un modulo estan en su `doubles.py`; los fixtures,
en `conftest.py`.

```bash
uv run pytest                                              # la suite entera
uv run coverage run -m pytest && uv run coverage report    # con cobertura
docker build --target test .                               # igual que en CI
```

El piso de cobertura es **68 %** (`fail_under` en `pyproject.toml`): si baja de ahi, el
build falla. Los tests que necesiten infraestructura real (Postgres, Azure, red) van
marcados con `@pytest.mark.integration` y quedan fuera del stage `test`, que no levanta
servicios.

## Lint y tipos

[ruff](https://github.com/astral-sh/ruff) como linter y [mypy](https://mypy-lang.org/) para
el chequeo estatico de tipos. Ambos configurados en `pyproject.toml` y ambos bloquean el CI:

```bash
uv run ruff check .          # lo mismo que corre el CI
uv run ruff check . --fix    # arregla lo que se pueda solo
uv run mypy app config.py    # tipos
```

No se corre `ruff format`: reformatear todo el proyecto es un cambio aparte, no un efecto
colateral del linter.

**Tipado gradual.** Los type hints no hacen nada en runtime — Python los ignora; su valor lo
desbloquea mypy, que los verifica antes de ejecutar. La base global es permisiva para que el
chequeo pase hoy, y el modo estricto ya esta activo en los modulos que lo cumplen (`limits`,
`feedback`, `logconfig`, `config`, y casi todo `reading` y `conversation`). Falta llevar a
estricto `cmd/server.py`, `speech/*`, `storage.py`, `ratelimit.py`, `conversation/graph.py`
y `service.py`, y `reading/service.py` y `repository.py`: la lista esta en `pyproject.toml`
y la idea es que solo crezca.

> Cuidado al editar esa config: `strict = true` dentro de una seccion per-module de mypy
> **se aplica al proyecto entero**, no al modulo. Por eso los flags estan expandidos a mano.

## Estructura

Todo el codigo vive en [`app/`](app/); en la raiz solo quedan `config.py` y los archivos de
proyecto.

| Ruta | Que hace |
|---|---|
| `app/cmd/server.py` | Servidor FastAPI: rutas, middlewares (request id, rate limit) y wiring de dependencias |
| `app/conversation/` | Grafo LangGraph del tutor, prompts, repositorio y servicio |
| `app/reading/` | Catalogo de textos: ingesta, extractos, scheduler y servicio |
| `app/speech/` | Azure Speech: cliente, evaluacion (con y sin texto de referencia) y scoring |
| `app/limits/` | Presupuesto en dolares y cuota por usuario |
| `app/feedback/` | Feedback del piloto |
| `app/web/` | Plantillas Jinja2 y assets estaticos |
| `app/storage.py`, `app/logconfig.py`, `app/ratelimit.py` | Pool de Postgres, structlog y rate limiter |
| `config.py` | **Unico** lugar del proyecto que lee variables de entorno |
| `tests/` | Espejo de `app/` |
| `docker/initdb/` | Scripts SQL que crean el esquema |

## Documentacion

| Documento | Contenido |
|---|---|
| [docs/DEPLOY.md](docs/DEPLOY.md) | Construccion de la imagen, stages del Dockerfile, CI y pasos para desplegar |
| [docs/ENVS.md](docs/ENVS.md) | Cada variable de entorno, su default y para que sirve |
| [docs/AZURE-PRONUNCIATION.md](docs/AZURE-PRONUNCIATION.md) | Como funciona el Pronunciation Assessment de Azure y que configuracion usa este proyecto |
| [docs/superpowers/](docs/superpowers/) | Planes y specs de cada feature |

> El servidor **no tiene autenticacion**. La identidad es un `X-User-Id` que manda el
> navegador, util para separar cuotas, no para proteger nada.
