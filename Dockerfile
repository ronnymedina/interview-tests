# syntax=docker/dockerfile:1
#
# Dockerfile multistage para el módulo migrado `app/` (no el código legacy de la
# raíz). Etapas: base -> development -> test -> production.
#
#   docker build --target development -t review-ingles:dev .
#   docker build --target test .          # corre pytest + coverage; falla si rompen
#   docker build --target production -t review-ingles:prod .
#
# El .env NUNCA se hornea en la imagen: las variables se inyectan en runtime.

# ---------------------------------------------------------------------------
# base — deps de producción sobre python slim, con uv. Capa cacheada.
# ---------------------------------------------------------------------------
FROM python:3.13-slim AS base

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy

# Solo deps: se recachea mientras no cambien pyproject/uv.lock.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

# Fuente del módulo migrado + su único módulo de env.
COPY app ./app
COPY config.py ./config.py

ENV PATH="/app/.venv/bin:$PATH"

# ---------------------------------------------------------------------------
# development — hot reload. El código se monta como volumen (docker-compose).
# ---------------------------------------------------------------------------
FROM base AS development

# Agrega el grupo dev (pytest, httpx) al mismo venv.
RUN uv sync --frozen --no-install-project

EXPOSE 8000
CMD ["uvicorn", "app.cmd.server:app", "--reload", "--host", "0.0.0.0", "--port", "8000"]

# ---------------------------------------------------------------------------
# test — pytest + coverage del módulo app/. Runnable: `docker build --target test .`
# falla acá si rompen los tests, pero NO participa del build de producción.
# ---------------------------------------------------------------------------
FROM development AS test

# Solo el test dedicado a app/. NO se copia el conftest.py de la raíz (importa
# módulos legacy db/scoring que no viven en la imagen).
COPY test_app_conversation_service.py ./test_app_conversation_service.py

RUN coverage run --source=app,config -m pytest test_app_conversation_service.py \
    && coverage report -m

# ---------------------------------------------------------------------------
# production — imagen mínima, non-root, sin uv ni deps de dev.
# ---------------------------------------------------------------------------
FROM python:3.13-slim AS production

WORKDIR /app
RUN useradd --create-home --uid 10001 appuser

# Solo el venv de prod (armado en base) y la fuente. Sin uv, sin dev.
COPY --from=base /app/.venv ./.venv
COPY --from=base /app/app ./app
COPY --from=base /app/config.py ./config.py

ENV PATH="/app/.venv/bin:$PATH"
USER appuser
EXPOSE 8000
CMD ["uvicorn", "app.cmd.server:app", "--host", "0.0.0.0", "--port", "8000"]
