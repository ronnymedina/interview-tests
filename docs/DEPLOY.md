# Deploy

Como se construye la imagen, que hace cada stage del Dockerfile, que corre el CI y los pasos
para poner la app en un proveedor.

## El Dockerfile es multistage

`base` → `development` → `test` → `production`

| Stage | Que tiene | Para que |
|---|---|---|
| `base` | Deps de **produccion** (`uv sync --no-dev`), `app/` y `config.py` | Capa cacheada; se reconstruye solo si cambian `pyproject.toml` o `uv.lock` |
| `development` | `base` + el grupo `dev` (pytest, coverage, mypy…) | Hot reload. Es el que usa `docker-compose.yml` |
| `test` | `development` + `tests/` | Corre pytest con coverage. Falla el build si rompen los tests o si baja la cobertura |
| `production` | Solo el venv de prod, `app/` y `config.py` | La imagen que se despliega. Sin `uv`, sin deps de dev, sin tests |

```bash
docker build --target test .                            # tests + coverage
docker build --target production -t review-ingles:prod .  # imagen final
```

### Detalles de la imagen de produccion

- Corre como usuario **non-root** (`appuser`, uid 10001).
- No lleva `uv` ni dependencias de desarrollo: copia el venv ya armado desde `base`.
- El `.env` **nunca** se hornea en la imagen. Las variables se inyectan en runtime.
- El `CMD` es `sh -c "exec uvicorn ... --port ${PORT:-8000}"`. Los dos detalles importan:
  - **`${PORT:-8000}`** expande el puerto que el proveedor inyecta en runtime (Railway lo
    hace). Sin eso, el proveedor no puede rutear trafico al contenedor.
  - **`exec`** hace que uvicorn reemplace al shell y quede como PID 1, asi recibe el
    `SIGTERM` y se apaga ordenadamente en vez de morir de golpe.

## CI

[`.github/workflows/ci.yml`](../.github/workflows/ci.yml) corre en push y PR contra `main` y
`develop`, en cuatro jobs:

1. **Lint (ruff)**, **Tipos (mypy)**, **Tests unitarios y coverage** y **Tests de
   integracion**, en paralelo. Los cuatro bloquean.
2. **Imagen de produccion** — solo si los cuatro anteriores pasaron. Nunca se publica una
   imagen verde sobre una suite roja.

Van en paralelo a proposito: un error de estilo no debe tapar un test roto, ni al reves.

El job de tests unitarios no instala nada por su cuenta: construye el stage `test` del
Dockerfile. Por eso un fallo remoto se reproduce local con un solo comando
(`docker build --target test .`) en vez de tener que adivinar en que se diferencia el
runner de tu maquina.

Lint y tipos son la excepcion: corren `ruff` y `mypy` directo, sin Docker, porque tardan
segundos y no necesitan el entorno completo. Local es `uv run ruff check .` y
`uv run mypy app config.py`.

**Tests de integracion.** El job de tests unitarios corre dentro del stage `test`, que no
levanta infraestructura: todo lo que prueba sobre las migraciones lee el TEXTO del archivo
(`assert "..." in sql`). El unico test que ejecuta SQL de verdad
(`test_upgrade_head_crea_las_tablas`, marcado `@pytest.mark.integration`) queda afuera de
ese stage y corre en un job aparte, que levanta un Postgres real como `services:` del job y
corre `uv run pytest -m integration` directo (no via Docker: el stage `test` no tiene forma
de hablarle a un servicio hermano del runner). Bloquea `build` igual que los demas: el
lifespan aplica las migraciones sin try/except a proposito, y esta es la unica compuerta de
CI para esa politica antes de que una migracion rota llegue a Railway.

Si la cobertura baja del **68 %** (`fail_under` en `pyproject.toml`), `coverage report` sale
con codigo != 0 y el build falla.

El cache de capas se guarda en GitHub Actions (`type=gha`), asi que las deps no se
reinstalan en cada run.

## Desplegar

1. **Aprovisiona un Postgres** y pasa su cadena de conexion en `DATABASE_URL`. No hay que
   crear el esquema a mano: la app corre las migraciones de Alembic al arrancar, tanto en
   una base vacia como en una que ya tiene datos.

   Si la migracion falla, el contenedor no arranca y el deploy queda rojo — a proposito,
   para que el proveedor siga sirviendo la version anterior en vez de una app con el
   esquema desactualizado.

2. **Carga las variables de entorno** en el panel del servicio. Como minimo:
   `DATABASE_URL`, `AZURE_SPEECH_KEY`, `AZURE_SPEECH_REGION`, `GEMINI_API_KEY`.

   Revisa tambien `DAILY_BUDGET_USD` / `TOTAL_BUDGET_USD` y las cuotas por usuario **antes**
   de abrir el acceso: son el freno de gasto. Ver [ENVS.md](ENVS.md).

3. **Despliega** el `Dockerfile` con `--target production`.

## Deuda pendiente: `conversation_configs`

La tabla `conversation_configs` quedo obsoleta cuando se elimino su CRUD (nadie la usaba) y
la migracion inicial de Alembic (`migrations/versions/0001_esquema_inicial.py`) no la crea
a proposito. No hay, ni va a haber, una migracion que la borre: es una decision de diseño,
no un olvido.

Efecto practico: una base nueva no la tiene, pero las bases que ya existian en Railway
antes de esta migracion todavia la arrastran, porque Alembic solo crea lo que falta y
nunca borra lo que no menciona. Hay que eliminarla **a mano, una sola vez**, en cada base
que ya existia:

```sql
DROP TABLE IF EXISTS conversation_configs;
```

Mientras eso no se haga, produccion y una base nueva difieren en una tabla que ninguna
migracion describe — justo lo que esta unificacion del esquema vino a evitar.

## Antes de exponerlo en internet

El servidor **no tiene autenticacion**. La identidad es un `X-User-Id` que manda el
navegador: sirve para separar cuotas, no para proteger nada — cualquiera puede mandar otro.

Lo unico que limita el gasto son el presupuesto (`DAILY_BUDGET_USD`, `TOTAL_BUDGET_USD`) y
el rate limit por IP (`RATE_LIMIT_*`). Tenelo presente antes de publicar la URL.
