# Deploy

Como se construye la imagen, que hace cada stage del Dockerfile, que corre el CI y los pasos
para poner la app en un proveedor.

## El Dockerfile es multistage

`base` → `development` → `test` → `production`

| Stage | Que tiene | Para que |
|---|---|---|
| `base` | Deps de **produccion** (`uv sync --no-dev`), `app/` y `config.py` | Capa cacheada; se reconstruye solo si cambian `pyproject.toml` o `uv.lock` |
| `development` | `base` + el grupo `dev` (pytest, coverage, mypy…) | Hot reload. Es el que usa `docker-compose.yml` |
| `test` | `development` + `tests/` + `docker/initdb/` | Corre pytest con coverage. Falla el build si rompen los tests o si baja la cobertura |
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
`develop`, en dos jobs encadenados:

1. **Tests unitarios y coverage** — construye el stage `test`.
2. **Imagen de produccion** — solo si el anterior paso. Nunca se publica una imagen verde
   sobre una suite roja.

El CI no instala nada por su cuenta: usa el mismo Dockerfile que vos. Por eso un fallo
remoto se reproduce local con un solo comando (`docker build --target test .`) en vez de
tener que adivinar en que se diferencia el runner de tu maquina.

El cache de capas se guarda en GitHub Actions (`type=gha`), asi que las deps no se
reinstalan en cada run.

## Desplegar

1. **Aprovisiona un Postgres** y aplica los scripts de [`docker/initdb/`](../docker/initdb/)
   **en orden numerico**. En Compose se ejecutan solos al crear el volumen por primera vez,
   pero en un Postgres gestionado hay que correrlos a mano una vez:

   ```bash
   for f in docker/initdb/*.sql; do psql "$DATABASE_URL" -f "$f"; done
   ```

2. **Carga las variables de entorno** en el panel del servicio. Como minimo:
   `DATABASE_URL`, `AZURE_SPEECH_KEY`, `AZURE_SPEECH_REGION`, `GEMINI_API_KEY`.

   Revisa tambien `DAILY_BUDGET_USD` / `TOTAL_BUDGET_USD` y las cuotas por usuario **antes**
   de abrir el acceso: son el freno de gasto. Ver [ENVS.md](ENVS.md).

3. **Despliega** el `Dockerfile` con `--target production`.

## Antes de exponerlo en internet

El servidor **no tiene autenticacion**. La identidad es un `X-User-Id` que manda el
navegador: sirve para separar cuotas, no para proteger nada — cualquiera puede mandar otro.

Lo unico que limita el gasto son el presupuesto (`DAILY_BUDGET_USD`, `TOTAL_BUDGET_USD`) y
el rate limit por IP (`RATE_LIMIT_*`). Tenelo presente antes de publicar la URL.
