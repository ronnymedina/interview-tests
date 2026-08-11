# Deploy

How the image is built, what each Dockerfile stage does, what CI runs, and the steps to put
the app on a provider.

## The Dockerfile is multistage

`base` → `development` → `test` → `production`

| Stage | What it has | What for |
|---|---|---|
| `base` | **Production** deps (`uv sync --no-dev`), `app/` and `config.py` | Cached layer; rebuilt only when `pyproject.toml` or `uv.lock` change |
| `development` | `base` + the `dev` group (pytest, coverage, mypy…) | Hot reload. The one `docker-compose.yml` uses |
| `test` | `development` + `tests/` | Runs pytest with coverage. Fails the build if tests break or coverage drops |
| `production` | Only the prod venv, `app/` and `config.py` | The image that gets deployed. No `uv`, no dev deps, no tests |

```bash
docker build --target test .                              # tests + coverage
docker build --target production -t review-ingles:prod .  # final image
```

### Production image details

- Runs as a **non-root** user (`appuser`, uid 10001).
- Carries no `uv` and no development dependencies: it copies the venv already built in `base`.
- The `.env` is **never** baked into the image. Variables are injected at runtime.
- The `CMD` is `sh -c "exec uvicorn ... --port ${PORT:-8000}"`. Both details matter:
  - **`${PORT:-8000}`** expands the port the provider injects at runtime (Railway does).
    Without it the provider cannot route traffic to the container.
  - **`exec`** makes uvicorn replace the shell and become PID 1, so it receives `SIGTERM`
    and shuts down cleanly instead of being killed outright.

## CI

[`.github/workflows/ci.yml`](../.github/workflows/ci.yml) runs on push and PR against `main`
and `develop`, in four jobs:

1. **Lint (ruff)**, **Types (mypy)**, **Unit tests and coverage** and **Integration tests**,
   in parallel. All four block.
2. **Production image** — only if the previous four passed. A green image is never published
   on top of a red suite.

They run in parallel on purpose: a style error must not mask a broken test, or the reverse.

The unit test job installs nothing on its own: it builds the Dockerfile's `test` stage. That
is why a remote failure reproduces locally with a single command
(`docker build --target test .`) instead of having to guess how the runner differs from your
machine.

Lint and types are the exception: they run `ruff` and `mypy` directly, without Docker,
because they take seconds and do not need the full environment. Locally that is
`uv run ruff check .` and `uv run mypy app config.py`.

**Integration tests.** The unit test job runs inside the `test` stage, which brings up no
infrastructure: everything it checks about migrations reads the file's TEXT
(`assert "..." in sql`). The only test that executes real SQL
(`test_upgrade_head_crea_las_tablas`, marked `@pytest.mark.integration`) stays out of that
stage and runs in a separate job, which brings up a real Postgres as a `services:` entry and
runs `uv run pytest -m integration` directly (not via Docker: the `test` stage has no way to
talk to a sibling service of the runner). It blocks `build` like the others: the lifespan
applies migrations without a try/except on purpose, and this is the only CI gate on that
policy before a broken migration reaches Railway.

If coverage drops below **68 %** (`fail_under` in `pyproject.toml`), `coverage report` exits
non-zero and the build fails.

The layer cache lives in GitHub Actions (`type=gha`), so deps are not reinstalled on every
run.

## Deploying

1. **Provision a Postgres** and pass its connection string in `DATABASE_URL`. The schema does
   not need to be created by hand: the app runs the Alembic migrations at startup, both on an
   empty database and on one that already holds data.

   If a migration fails the container does not start and the deploy goes red — on purpose, so
   the provider keeps serving the previous version instead of an app with an outdated schema.

2. **Load the environment variables** in the service panel. At minimum: `DATABASE_URL`,
   `AZURE_SPEECH_KEY`, `AZURE_SPEECH_REGION`, `GEMINI_API_KEY`.

   Also review `DAILY_BUDGET_USD` / `TOTAL_BUDGET_USD` and the per-user quotas **before**
   opening access: they are the spend brake. See [environments.md](environments.md).

3. **Deploy** the `Dockerfile` with `--target production`.

## Outstanding debt: `conversation_configs`

The `conversation_configs` table became obsolete when its CRUD was removed (nobody used it),
and the initial Alembic migration (`migrations/versions/0001_esquema_inicial.py`) does not
create it, on purpose. There is not, and will not be, a migration that drops it: that is a
design decision, not an oversight.

Practical effect: a fresh database does not have it, but databases that already existed on
Railway before this migration still carry it, because Alembic only creates what is missing
and never drops what it does not mention. It has to be removed **by hand, once**, on every
pre-existing database:

```sql
DROP TABLE IF EXISTS conversation_configs;
```

Until that is done, production and a fresh database differ by one table that no migration
describes — exactly what unifying the schema set out to avoid.

## Before exposing it on the internet

The server **has no authentication**. Identity is an `X-User-Id` the browser sends: useful to
separate quotas, not to protect anything — anyone can send a different one.

The only things capping spend are the budget (`DAILY_BUDGET_USD`, `TOTAL_BUDGET_USD`) and the
per-IP rate limit (`RATE_LIMIT_*`). Keep that in mind before publishing the URL.
